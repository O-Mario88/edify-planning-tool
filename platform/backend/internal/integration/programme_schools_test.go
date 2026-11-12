//go:build integration

package integration

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func filterOf(page *screensv1.GetPageResponse, name string) *screensv1.PageFilter {
	for _, block := range page.GetBlocks() {
		for _, f := range block.GetFilters().GetFilters() {
			if f.GetName() == name {
				return f
			}
		}
	}
	return nil
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestProgrammeSchoolsListsTheCountrysThreeTypes(t *testing.T) {
	ctx := context.Background()
	var total, champions int
	if err := admin.QueryRow(ctx, `
SELECT count(*), count(*) FILTER (WHERE school_type = 'champion') FROM school
WHERE deleted_at IS NULL AND operational_status IN ('active', 'reopened')
  AND school_type IN ('core_trained', 'core_graduate', 'champion')`).Scan(&total, &champions); err != nil {
		t.Fatal(err)
	}
	if total == 0 {
		t.Skip("the seed has no programme school")
	}
	borrowAccount(t, "admin@edify.org")
	token := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/programme-schools", nil)
	if err != nil {
		t.Fatal(err)
	}
	if page.GetHeader().GetTitle() != "Programme Schools" {
		t.Fatalf("the header: %v", page.GetHeader())
	}
	figures := page.GetBlocks()[0].GetStrip().GetMetrics()
	if figures[0].GetValue() != fmt.Sprint(total) {
		t.Fatalf("Programme schools %s, want %d", figures[0].GetValue(), total)
	}
	types := filterOf(page, "school_type")
	if types == nil || len(types.GetOptions()) != 4 || types.GetOptions()[3].GetLabel() != fmt.Sprintf("Champion (%d)", champions) {
		t.Fatalf("the type filter: %v", types)
	}
	table := tableOf(page)
	if table == nil || len(table.GetRows()) != min(total, 50) || len(table.GetColumns()) != 10 {
		t.Fatalf("the table: %d rows", len(table.GetRows()))
	}
	// An Admin plans nothing, so each row offers View.
	for _, row := range table.GetRows() {
		cells := row.GetCells()
		if cells[9].GetText() != "View" || !strings.HasPrefix(cells[9].GetHref(), "/schools/") {
			t.Fatalf("the row's action: %v", cells[9])
		}
		if !strings.Contains(cells[6].GetText(), "/") {
			t.Fatalf("the entitlement: %q", cells[6].GetText())
		}
	}

	none, err := pageOf(token, "/programme-schools", map[string]string{"q": "zzz no such school"})
	if err != nil {
		t.Fatal(err)
	}
	if tableOf(none) != nil || len(none.GetHeader().GetActions()) != 1 ||
		!strings.HasPrefix(none.GetBlocks()[2].GetEmpty(), "Clear the filters") {
		t.Fatalf("a search that matches nothing: %v", none.GetBlocks()[2:])
	}
}

func TestAPlannersProgrammeSchoolsOfferSchedule(t *testing.T) {
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/programme-schools", nil)
	if err != nil {
		t.Fatal(err)
	}
	table := tableOf(page)
	if table == nil {
		t.Skip("the seeded officer holds no programme school")
	}
	if action := table.GetRows()[0].GetCells()[9]; action.GetText() != "Schedule" || action.GetHref() != "" {
		t.Fatalf("a planner's row: %v", action)
	}
}

func TestARoleOutsideProgrammeSchoolsIsTurnedAway(t *testing.T) {
	borrowAccount(t, "coordinator@edify.org")
	token := sessionOf(t, "coordinator@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/programme-schools", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Project Coordinator opening Programme Schools: %v, want not found", err)
	}
}
