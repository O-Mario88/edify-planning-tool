//go:build integration

package integration

import (
	"context"
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

func TestClusterOversightIsNotThereForARoleOutsideItNorAtASectionsAddress(t *testing.T) {
	borrowAccount(t, "coordinator@edify.org")
	token := sessionOf(t, "coordinator@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, clusterOversight, nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Project Coordinator opening Cluster Oversight: %v, want not found", err)
	}
	borrowAccount(t, "admin@edify.org")
	token = sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	for _, path := range []string{"/cluster-oversight/ssa", "/cluster-oversight", "/cluster-oversight/scoring"} {
		if _, err := pageOf(token, path, nil); connect.CodeOf(err) != connect.CodeNotFound {
			t.Fatalf("%s: %v, want not found, as the existing feed answers", path, err)
		}
	}
}
