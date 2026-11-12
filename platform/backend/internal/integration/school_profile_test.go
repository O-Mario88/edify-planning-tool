//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

func profileClient() screensv1connect.SchoolProfileServiceClient {
	return screensv1connect.NewSchoolProfileServiceClient(http.DefaultClient, baseURL)
}

func profileOf(token, schoolID, tab string) (*screensv1.GetSchoolProfileResponse, error) {
	answer, err := profileClient().GetSchoolProfile(context.Background(),
		authed(&screensv1.GetSchoolProfileRequest{SchoolId: schoolID, Tab: tab}, token))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

// noBusinessTransformation leaves out schools whose panel is still the
// existing application's.
const noBusinessTransformation = `NOT EXISTS (SELECT 1 FROM bt_case c WHERE c.school_id = s.id)
  AND NOT EXISTS (SELECT 1 FROM bt_mfi_loan l WHERE l.school_id = s.id)`

// anOfficersSchool is one of the officer's open schools of type kind with no
// Business Transformation record.
func anOfficersSchool(t *testing.T, userID, kind string) (id, name string) {
	t.Helper()
	err := admin.QueryRow(context.Background(), `
SELECT s.id, s.name FROM school s
JOIN staff_school_assignment a ON a.school_id = s.id JOIN staff_profile sp ON sp.id = a.staff_id
WHERE sp.user_id = $1 AND `+operatingSchools+` AND s.school_type = $2 AND `+noBusinessTransformation+`
ORDER BY s.id LIMIT 1`, userID, kind).Scan(&id, &name)
	if err != nil {
		t.Skipf("the seeded officer holds no open %s school: %v", kind, err)
	}
	return id, name
}

func actionKeys(profile *screensv1.GetSchoolProfileResponse) map[string]bool {
	keys := map[string]bool{}
	for _, action := range profile.GetHeader().GetActions() {
		keys[action.GetKey()] = true
	}
	return keys
}

func TestGoAnswersAnOfficersSchoolDetails(t *testing.T) {
	userID := borrowAccount(t, "cceo@edify.org")
	id, name := anOfficersSchool(t, userID, "client")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()

	// No existing application is configured here: an answer is Go's.
	profile, err := profileOf(token, id, "details")
	if err != nil {
		t.Fatalf("the Details tab: %v", err)
	}
	if profile.GetHeader().GetTitle() != name || profile.GetWebPath() != "/schools/"+id {
		t.Fatalf("the header: %+v", profile.GetHeader())
	}
	tabs := profile.GetTabs()
	if len(tabs) != 7 || tabs[6].GetKey() != "details" || !tabs[6].GetActive() {
		t.Fatalf("the tabs: %v", tabs)
	}
	if keys := actionKeys(profile); !keys["edit_details"] || !keys["schedule"] || !keys["close_school"] || keys["reassign_owner"] {
		t.Fatalf("an officer's doors: %v", keys)
	}
	titles := []string{}
	for _, block := range profile.GetBlocks() {
		titles = append(titles, block.GetPanel().GetTitle())
	}
	if len(titles) != 3 || titles[0] != "School Demographics & Assignment" || titles[1] != "Business Transformation" || titles[2] != "Data Quality Score" {
		t.Fatalf("the panels: %v", titles)
	}
}

func TestTheRestOfTheProfileIsStillTheExistingApplications(t *testing.T) {
	userID := borrowAccount(t, "cceo@edify.org")
	client, _ := anOfficersSchool(t, userID, "client")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	// The SSA and Participation tabs are passed on; with no existing
	// application here, it says so.
	_, err := profileOf(token, client, "ssa")
	requireCode(t, err, connect.CodeUnavailable, "")
	_, err = profileOf(token, client, "activities")
	requireCode(t, err, connect.CodeUnavailable, "")
	// So is a Core school's profile, whose package rule has not moved.
	core, _ := anOfficersSchool(t, userID, "core")
	_, err = profileOf(token, core, "details")
	requireCode(t, err, connect.CodeUnavailable, "")
}

func TestASchoolOutsideTheScopeIsNotFound(t *testing.T) {
	// Another officer's school, asked by an officer who holds none, leads no
	// one and covers no one: it is held, so it is not one to take either.
	holder := borrowAccount(t, "cceo@edify.org")
	outside, _ := anOfficersSchool(t, holder, "client")
	var email string
	err := admin.QueryRow(context.Background(), `
SELECT u.email FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.active_role = 'CCEO' AND u.deleted_at IS NULL AND sp.deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM staff_school_assignment a WHERE a.staff_id = sp.id)
  AND NOT EXISTS (SELECT 1 FROM temporary_coverage_assignment c WHERE c.covering_staff_id = sp.id)
  AND NOT EXISTS (SELECT 1 FROM acting_assignment a WHERE a.appointee_id = u.id AND a.cancelled_at IS NULL)
ORDER BY u.email LIMIT 1`).Scan(&email)
	if err != nil {
		t.Skip("no seeded officer without schools")
	}
	borrowAccount(t, email)
	token := sessionOf(t, email, seededPassword).GetAccessToken()
	_, err = profileOf(token, outside, "details")
	requireCode(t, err, connect.CodeNotFound, "")
	_, err = profileOf(token, "no-such-school", "details")
	requireCode(t, err, connect.CodeNotFound, "")
}

func TestAPartnerCannotOpenSchoolProfiles(t *testing.T) {
	borrowAccount(t, "partner-admin@edify.org")
	token := sessionOf(t, "partner-admin@edify.org", seededPassword).GetAccessToken()
	_, err := profileOf(token, "any", "details")
	requireCode(t, err, connect.CodePermissionDenied, "")
}

func TestTheAdminSeesTheDangerZone(t *testing.T) {
	var id string
	if err := admin.QueryRow(context.Background(), `
SELECT s.id FROM school s WHERE `+operatingSchools+` AND s.school_type = 'client' AND `+noBusinessTransformation+`
ORDER BY s.id LIMIT 1`).Scan(&id); err != nil {
		t.Skip("no open client school")
	}
	profile, err := profileOf(adminSession(t), id, "details")
	if err != nil {
		t.Fatalf("the Details tab: %v", err)
	}
	blocks := profile.GetBlocks()
	if last := blocks[len(blocks)-1].GetPanel(); last.GetTitle() != "Danger Zone" {
		t.Fatalf("the Admin's last panel: %q", last.GetTitle())
	}
	if keys := actionKeys(profile); !keys["reassign_owner"] || keys["schedule"] || keys["enter_ssa_score"] {
		t.Fatalf("the Admin's doors: %v", keys)
	}
}

func TestGoAnswersTheEnginesTabs(t *testing.T) {
	userID := borrowAccount(t, "cceo@edify.org")
	id, _ := anOfficersSchool(t, userID, "client")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	for _, tab := range []string{"overview", "projects", "stories", "academic"} {
		profile, err := profileOf(token, id, tab)
		if err != nil {
			t.Fatalf("%s: %v", tab, err)
		}
		blocks := profile.GetBlocks()
		if len(blocks) < 4 || blocks[0].GetScopeLine() == "" || blocks[1].GetFacts() == nil ||
			blocks[2].GetFilters().GetHidden()["tab"] != tab {
			t.Fatalf("%s: the frame: %v", tab, blocks)
		}
		facts := map[string]string{}
		for _, f := range blocks[1].GetFacts().GetFacts() {
			facts[f.GetLabel()] = f.GetValue()
		}
		if facts["Status"] != "Operating" || facts["Fiscal Year"] == "" {
			t.Fatalf("%s: the facts: %v", tab, facts)
		}
	}
	// A past year and a quarter are read as asked; an unknown one is the
	// running year, the whole of it.
	profile, err := profileOf(token, id, "projects")
	if err != nil {
		t.Fatal(err)
	}
	running := profile.GetBlocks()[2].GetFilters().GetFilters()[0].GetValue()
	answer, err := profileClient().GetSchoolProfile(context.Background(),
		authed(&screensv1.GetSchoolProfileRequest{SchoolId: id, Tab: "projects", Fy: "1999", Period: "M13"}, token))
	if err != nil {
		t.Fatal(err)
	}
	if got := answer.Msg.GetBlocks()[2].GetFilters().GetFilters(); got[0].GetValue() != running || got[1].GetValue() != "" {
		t.Fatalf("an unknown year and period: %v", got)
	}
}

func TestNoTabIsTheOverview(t *testing.T) {
	userID := borrowAccount(t, "cceo@edify.org")
	id, _ := anOfficersSchool(t, userID, "client")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	for _, tab := range []string{"", "nonsense", "core"} {
		profile, err := profileOf(token, id, tab)
		if err != nil {
			t.Fatalf("%q: %v", tab, err)
		}
		if profile.GetTabs()[0].GetKey() != "overview" || !profile.GetTabs()[0].GetActive() {
			t.Fatalf("%q opens the Overview: %v", tab, profile.GetTabs())
		}
		titles := []string{}
		for _, block := range profile.GetBlocks() {
			if strip := block.GetStrip(); strip != nil {
				titles = append(titles, strip.GetTitle())
			}
		}
		if len(titles) < 2 || titles[0] != "Performance And Impact" || titles[1] != "Operations" {
			t.Fatalf("%q: the strips: %v", tab, titles)
		}
		last := profile.GetBlocks()[len(profile.GetBlocks())-1].GetRail()
		if last == nil || len(last.GetParts()) != 2 || len(last.GetParts()[0].GetMeters()) != 8 {
			t.Fatalf("%q: the rail: %v", tab, last)
		}
	}
}
