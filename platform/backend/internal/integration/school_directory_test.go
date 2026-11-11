//go:build integration

package integration

import (
	"context"
	"net/http"
	"slices"
	"testing"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

func directoryClient() screensv1connect.SchoolDirectoryScreenServiceClient {
	return screensv1connect.NewSchoolDirectoryScreenServiceClient(http.DefaultClient, baseURL)
}

func directoryOf(t *testing.T, token string, request *screensv1.GetSchoolDirectoryRequest) *screensv1.GetSchoolDirectoryResponse {
	t.Helper()
	answer, err := directoryClient().GetSchoolDirectory(context.Background(), authed(request, token))
	if err != nil {
		t.Fatalf("the directory: %v", err)
	}
	return answer.Msg
}

const operatingSchools = `s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')`

func TestAnOfficerReadsTheirOwnSchoolsAPageAtATime(t *testing.T) {
	ctx := context.Background()
	userID := borrowAccount(t, "cceo@edify.org")
	var held int
	_ = admin.QueryRow(ctx, `
SELECT count(*) FROM school s WHERE `+operatingSchools+` AND s.id IN (
  SELECT a.school_id FROM staff_school_assignment a JOIN staff_profile sp ON sp.id = a.staff_id WHERE sp.user_id = $1)`, userID).Scan(&held)
	if held == 0 {
		t.Skip("the seeded officer holds no school")
	}
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	first := directoryOf(t, token, &screensv1.GetSchoolDirectoryRequest{})

	if first.GetPage().GetTotal() != int64(held) || first.GetTabs()[0].GetCount() != int32(held) {
		t.Fatalf("the officer holds %d schools; the directory lists %d (tab %d)", held, first.GetPage().GetTotal(), first.GetTabs()[0].GetCount())
	}
	tabs := map[string]int32{}
	for _, tab := range first.GetTabs() {
		tabs[tab.GetKey()] = tab.GetCount()
	}
	if tabs["unclustered"]+tabs["clustered"] > tabs["all"] || tabs["assigned"]+tabs["not_assigned"] != tabs["all"] {
		t.Fatalf("the tabs do not add up: %v", tabs)
	}
	want := min(held, 50)
	if len(first.GetSchools()) != want || first.GetPage().GetPageSize() != 50 {
		t.Fatalf("a page holds %d rows, want %d", len(first.GetSchools()), want)
	}
	names := []string{}
	for _, school := range first.GetSchools() {
		names = append(names, school.GetName())
		if school.GetStaffName() == "" || school.GetVisitStatusLabel() == "" || school.GetClusterTrainingLabel() == "" {
			t.Fatalf("a row without its facts: %+v", school)
		}
	}
	if !slices.IsSorted(names) {
		t.Fatalf("an officer's schools are listed by name: %v", names)
	}
	if first.GetReadOnly() || !first.GetMayOpenProfile() {
		t.Fatalf("an officer works their directory: read only %v, opens profiles %v", first.GetReadOnly(), first.GetMayOpenProfile())
	}

	// Every page, each school once.
	seen := map[string]bool{}
	for page := int32(1); page <= first.GetPage().GetTotalPages(); page++ {
		for _, school := range directoryOf(t, token, &screensv1.GetSchoolDirectoryRequest{Page: page}).GetSchools() {
			if seen[school.GetId()] {
				t.Fatalf("%s is on two pages", school.GetName())
			}
			seen[school.GetId()] = true
		}
	}
	if len(seen) != held {
		t.Fatalf("the pages list %d of %d schools", len(seen), held)
	}

	// A School ID finds its school.
	someone := first.GetSchools()[0]
	if someone.GetSchoolId() != "" {
		found := directoryOf(t, token, &screensv1.GetSchoolDirectoryRequest{Q: someone.GetSchoolId()})
		hit := false
		for _, school := range found.GetSchools() {
			hit = hit || school.GetId() == someone.GetId()
		}
		if !hit {
			t.Fatalf("searching %s does not find it", someone.GetSchoolId())
		}
	}
}

func TestTheCountryReadsEveryOperatingSchool(t *testing.T) {
	ctx := context.Background()
	var operating int
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM school s WHERE `+operatingSchools).Scan(&operating)
	directory := directoryOf(t, adminSession(t), &screensv1.GetSchoolDirectoryRequest{})
	if directory.GetPage().GetTotal() != int64(operating) {
		t.Fatalf("the Admin reads %d of %d operating schools", directory.GetPage().GetTotal(), operating)
	}
	if !directory.GetMayTransferSchool() || !directory.GetCanAddSchool() {
		t.Fatalf("the Admin may add and transfer schools: %+v", directory)
	}
}

func TestOnlyTheRolesThePageAdmitsReadTheDirectory(t *testing.T) {
	borrowAccount(t, "partner-admin@edify.org")
	token := sessionOf(t, "partner-admin@edify.org", seededPassword).GetAccessToken()
	_, err := directoryClient().GetSchoolDirectory(context.Background(), authed(&screensv1.GetSchoolDirectoryRequest{}, token))
	requireCode(t, err, connect.CodePermissionDenied, "")
}

func TestSomeoneActingIsStillServedByTheExistingApplication(t *testing.T) {
	ctx := context.Background()
	leadUser := borrowAccount(t, "pl1@edify.org")
	_, leadSeat := staffOf(t, "pl1@edify.org")
	cceoUser, cceo := aCCEOOf(t, leadSeat)
	var email string
	_ = admin.QueryRow(ctx, `SELECT email FROM "user" WHERE id = $1`, cceoUser).Scan(&email)
	borrowAccount(t, email)
	clearAppointments(t, leadUser, cceoUser)
	this, _, _ := months()
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	if _, err := actingClient().Appoint(ctx, authed(&identityv1.AppointRequest{AppointeeStaffId: cceo, Month: this}, lead)); err != nil {
		t.Fatal(err)
	}
	appointee := sessionOf(t, email, seededPassword).GetAccessToken()
	// The existing application presents an acting leader in the acting seat;
	// the gateway sends them there (here none is configured, so it says so).
	_, err := directoryClient().GetSchoolDirectory(ctx, authed(&screensv1.GetSchoolDirectoryRequest{}, appointee))
	requireCode(t, err, connect.CodeUnavailable, "")
}
