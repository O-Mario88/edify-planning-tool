//go:build integration

package integration

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

const clusterOversight = "/cluster-oversight/"

func oversightTable(t *testing.T, page *screensv1.GetPageResponse) *screensv1.PageTable {
	t.Helper()
	if len(page.GetBlocks()) != 3 || page.GetBlocks()[2].GetTable() == nil {
		t.Fatalf("the page is its sections, its year filter and its table: %v", page.GetBlocks())
	}
	return page.GetBlocks()[2].GetTable()
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestClusterOversightOpensOnTheOfficersCommandCenter(t *testing.T) {
	var owned int
	if err := admin.QueryRow(context.Background(), `
SELECT count(*) FROM cluster c JOIN staff_profile sp ON sp.id = c.responsible_staff_id OR sp.user_id = c.responsible_staff_id
JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'cceo@edify.org' AND c.deleted_at IS NULL`).Scan(&owned); err != nil || owned == 0 {
		t.Skip("the seeded officer owns no cluster")
	}
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, clusterOversight, nil)
	if err != nil {
		t.Fatal(err)
	}
	if h := page.GetHeader(); h.GetEyebrow() != "Cluster Oversight" || h.GetTitle() != "Command Center" || len(h.GetActions()) != 0 {
		t.Fatalf("the header: %v", h)
	}
	tabs := page.GetBlocks()[0].GetLinkTabs()
	if !tabs.GetScrolls() || !tabs.GetTabs()[0].GetActive() || !strings.HasPrefix(tabs.GetTabs()[0].GetHref(), "/cluster-oversight/command?fy=") {
		t.Fatalf("the sections: %v", tabs)
	}
	if door := tabs.GetTabs()[1]; door.GetLabel() != "Clusters" || door.GetHref() != "/clusters" {
		t.Fatalf("an officer who holds every cluster shown is offered the Clusters door next, not My Clusters: %v", door)
	}
	table := oversightTable(t, page)
	if len(table.GetColumns()) != 19 || len(table.GetRows()) < min(owned, 50) || table.GetFootnote() == "" {
		t.Fatalf("%d columns, %d rows for %d clusters owned, note %q", len(table.GetColumns()), len(table.GetRows()), owned, table.GetFootnote())
	}
	for _, row := range table.GetRows() {
		name, maturity := row.GetCells()[0], row.GetCells()[18]
		if !strings.HasPrefix(name.GetHref(), "/clusters/") || strings.Contains(name.GetHref(), "/profile") {
			t.Fatalf("a cluster's name opens the cluster: %v", name)
		}
		if !strings.HasSuffix(maturity.GetHref(), "&part=maturity") || !strings.Contains(maturity.GetText(), " · ") {
			t.Fatalf("its maturity opens the scores tab: %v", maturity)
		}
	}
}

func TestClusterOversightKeepsToTheYearsItOffers(t *testing.T) {
	borrowAccount(t, "admin@edify.org")
	token := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	opened, err := pageOf(token, clusterOversight, nil)
	if err != nil {
		t.Fatal(err)
	}
	year := opened.GetBlocks()[1].GetFilters().GetFilters()[0]
	if year.GetName() != "fy" || len(year.GetOptions()) < 3 || year.GetOptions()[0].GetValue() <= year.GetOptions()[1].GetValue() {
		t.Fatalf("the year filter, newest first: %v", year)
	}
	unknown, err := pageOf(token, clusterOversight, map[string]string{"fy": "1999"})
	if err != nil {
		t.Fatal(err)
	}
	if got := unknown.GetBlocks()[1].GetFilters().GetFilters()[0].GetValue(); got != year.GetValue() {
		t.Fatalf("a year the page does not offer reads as %s, want the running year %s", got, year.GetValue())
	}
	earlier := year.GetOptions()[len(year.GetOptions())-1].GetValue()
	asked, err := pageOf(token, clusterOversight, map[string]string{"fy": earlier})
	if err != nil {
		t.Fatal(err)
	}
	if got := asked.GetBlocks()[0].GetLinkTabs().GetTabs()[0].GetHref(); !strings.HasSuffix(got, "?fy="+earlier) {
		t.Fatalf("the sections follow the year asked: %s", got)
	}
}

func TestAnOfficerWithNoClustersReadsAnEmptyCommandCenter(t *testing.T) {
	borrowAccount(t, "cceo1@edify.org")
	token := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, clusterOversight, nil)
	if err != nil {
		t.Fatal(err)
	}
	table := oversightTable(t, page)
	if len(table.GetRows()) != 0 {
		t.Skip("the seeded officer has clusters")
	}
	if table.GetEmptyMessage() != "No cluster is in your scope." || len(table.GetColumns()) != 0 || table.GetFootnote() != "" ||
		!strings.HasPrefix(table.GetSubtitle(), "0 clusters · 0 schools · no attendance") {
		t.Fatalf("the empty table: %v", table)
	}
}

func TestClusterOversightServesAllSectionsScoringAndCSVWithoutDjango(t *testing.T) {
	borrowAccount(t, "coordinator@edify.org")
	coordToken := sessionOf(t, "coordinator@edify.org", seededPassword).GetAccessToken()
	for _, path := range []string{clusterOversight, "/cluster-oversight/ssa", "/cluster-oversight/scoring"} {
		if _, err := pageOf(coordToken, path, nil); connect.CodeOf(err) != connect.CodeNotFound {
			t.Fatalf("a Project Coordinator opening %s: %v, want not found", path, err)
		}
	}

	borrowAccount(t, "cceo@edify.org")
	cceoToken := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(cceoToken, "/cluster-oversight/scoring", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a CCEO opening /cluster-oversight/scoring: %v, want not found", err)
	}

	borrowAccount(t, "admin@edify.org")
	adminToken := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()

	// Unknown sections must fail cleanly, never silently falling back to Command Center.
	for _, bad := range []string{"/cluster-oversight/nonexistent", "/cluster-oversight/ssa/extra"} {
		if _, err := pageOf(adminToken, bad, nil); connect.CodeOf(err) != connect.CodeNotFound {
			t.Fatalf("%s: %v, want not found", bad, err)
		}
	}

	// Every in-workspace section opens its own title, active tab, and table.
	sections := map[string]string{
		"command":    "Command Center",
		"my":         "My Clusters",
		"meetings":   "Meetings",
		"training":   "Training",
		"attendance": "Attendance",
		"schools":    "Schools",
		"ssa":        "SSA Performance",
		"teachers":   "Teacher Impact",
		"leaders":    "Leader Impact",
		"students":   "Student Impact",
		"academic":   "Academic Impact",
		"loans":      "Loans & BT",
		"stories":    "MSCS",
		"impact":     "Impact Analytics",
		"planning":   "Planning",
		"evidence":   "Evidence",
		"reports":    "Reports",
	}
	for key, wantTitle := range sections {
		got, err := pageOf(adminToken, "/cluster-oversight/"+key, nil)
		if err != nil {
			t.Fatalf("section %s failed: %v", key, err)
		}
		if got.GetHeader().GetTitle() != wantTitle {
			t.Errorf("section %s: title %q, want %q", key, got.GetHeader().GetTitle(), wantTitle)
		}
		if got.GetWebPath() != "/cluster-oversight/"+key {
			t.Errorf("section %s: web_path %q", key, got.GetWebPath())
		}
		if tbl := oversightTable(t, got); tbl.GetTitle() == "" {
			t.Errorf("section %s: empty table title", key)
		}
	}

	// SSA area filter & Impact courses view work with real seeded data.
	ssaFiltered, err := pageOf(adminToken, "/cluster-oversight/ssa", map[string]string{"area": "leadership"})
	if err != nil {
		t.Fatalf("ssa filtered: %v", err)
	}
	if !strings.Contains(oversightTable(t, ssaFiltered).GetTitle(), "Leadership") {
		t.Fatalf("ssa filtered table title: %q", oversightTable(t, ssaFiltered).GetTitle())
	}
	impactCourses, err := pageOf(adminToken, "/cluster-oversight/impact", map[string]string{"view": "courses"})
	if err != nil {
		t.Fatalf("impact courses: %v", err)
	}
	if !strings.Contains(oversightTable(t, impactCourses).GetTitle(), "SSA Movement After Each Training") {
		t.Fatalf("impact courses title: %q", oversightTable(t, impactCourses).GetTitle())
	}

	// Scoring opens for Admin.
	scoring, err := pageOf(adminToken, "/cluster-oversight/scoring", nil)
	if err != nil {
		t.Fatalf("scoring failed for Admin: %v", err)
	}
	if scoring.GetHeader().GetTitle() != "Cluster Scoring" || len(scoring.GetBlocks()) != 6 {
		t.Fatalf("scoring: title=%q blocks=%d", scoring.GetHeader().GetTitle(), len(scoring.GetBlocks()))
	}

	// CSV endpoint serves real CSV for Admin and refuses CCEO (Export=false).
	req, _ := http.NewRequest("GET", baseURL+"/api/v1/cluster-oversight/command/csv", nil)
	req.Header.Set("Authorization", "Bearer "+adminToken)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("csv request: %v", err)
	}
	body, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusOK || !strings.Contains(resp.Header.Get("Content-Type"), "text/csv") || !strings.Contains(string(body), "Cluster,District,CCEO") {
		t.Fatalf("admin csv: status=%d ct=%q body=%q", resp.StatusCode, resp.Header.Get("Content-Type"), string(body[:min(len(body), 120)]))
	}

	reqDenied, _ := http.NewRequest("GET", baseURL+"/api/v1/cluster-oversight/command/csv", nil)
	reqDenied.Header.Set("Authorization", "Bearer "+cceoToken)
	respDenied, err := http.DefaultClient.Do(reqDenied)
	if err != nil {
		t.Fatalf("cceo csv request: %v", err)
	}
	_ = respDenied.Body.Close()
	if respDenied.StatusCode != http.StatusForbidden {
		t.Fatalf("cceo csv: status=%d, want 403", respDenied.StatusCode)
	}
}
