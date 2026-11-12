//go:build integration

package integration

import (
	"testing"

	"connectrpc.com/connect"
)

// Core School Oversight's two tabs of planned work are My Plan's Core
// sheets of the schools shown, drawn by Go (no existing application is
// behind the gateway under test), and a download's format is not found.
// (FY 2026's visits hold the seed's completed partner visits, whose
// evidence Go may not read: that tab is the existing application's.)
func TestCoreOversightListsThePlannedWorkTabsThroughGo(t *testing.T) {
	borrowAccount(t, "admin@edify.org")
	token := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	for tab, want := range map[string]struct {
		title   string
		columns int
	}{"core_visits": {"Core School Visits, FY 2027", 15}, "core_trainings": {"Core School Trainings, FY 2027", 14}} {
		page, err := pageOf(token, "/core-schools-oversight/", map[string]string{"tab": tab, "fy": "2027"})
		if err != nil {
			t.Fatalf("%s: %v", tab, err)
		}
		var found bool
		for _, block := range page.GetBlocks() {
			if table := block.GetTable(); table != nil && table.GetTitle() == want.title {
				found = true
				if len(table.GetRows()) > 0 && len(table.GetColumns()) != want.columns {
					t.Errorf("%s: %d columns", tab, len(table.GetColumns()))
				}
				if len(table.GetRows()) == 0 && table.GetEmptyMessage() != "No planned work for the Core schools shown." {
					t.Errorf("%s: empty table %+v", tab, table)
				}
			}
		}
		if !found {
			t.Errorf("%s: no %q table in %v", tab, want.title, page.GetBlocks())
		}
	}
	if _, err := pageOf(token, "/core-schools-oversight/", map[string]string{"tab": "core_visits", "format": "xlsx"}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("format: got %v", err)
	}
}
