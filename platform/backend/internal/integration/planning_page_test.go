//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"

	"connectrpc.com/connect"
)

// The gateway under test has no existing application behind it, so every
// answer here is Go's, and what Go does not answer is unavailable.
func TestThePlanningPageListsTheOfficersClusteredClientSchools(t *testing.T) {
	var listed int
	if err := admin.QueryRow(context.Background(), `
SELECT count(*) FROM school s JOIN staff_school_assignment a ON a.school_id = s.id JOIN staff_profile sp ON sp.id = a.staff_id
JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo@edify.org' AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
  AND s.school_type IN ('client', 'core_trained', 'core_graduate') AND s.cluster_status = 'clustered'
  AND s.cluster_id IS NOT NULL AND s.cluster_id <> ''`).Scan(&listed); err != nil || listed == 0 {
		t.Skip("the seeded officer has no clustered client school")
	}
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/planning", nil)
	if err != nil {
		t.Fatal(err)
	}
	if page.GetHeader().GetTitle() != "Planning" || page.GetBlocks()[0].GetFilters().GetHidden()["tab"] != "client" {
		t.Fatalf("header %v, filters %v", page.GetHeader(), page.GetBlocks()[0])
	}
	var table, note, sized bool
	for _, b := range page.GetBlocks() {
		if item := b.GetPanel().GetItems(); len(item) == 1 && item[0].GetLead() != "" {
			// The workload line read whole: its bold opening, then the share-out.
			note = strings.HasPrefix(item[0].GetText(), item[0].GetLead()+" Core ") && strings.Contains(item[0].GetText(), " · Client ")
		}
		if b.GetPager().GetSize().GetName() == "per_page" {
			sized = true
		}
		if b.GetFilters() != nil && b.GetFilters().GetFilters()[0].GetCaption() != "FY" {
			t.Errorf("the year filter's short word: %v", b.GetFilters().GetFilters()[0])
		}
		if tb := b.GetTable(); tb != nil {
			table = true
			if want := min(listed, 15); len(tb.GetRows()) != want {
				t.Fatalf("%d rows on the first page, want %d", len(tb.GetRows()), want)
			}
		}
	}
	if !note || !sized {
		t.Errorf("workload line read whole %v, pager's rows-a-page chooser %v", note, sized)
	}
	if !table || page.GetSelection().GetNoun() != "schools selected" {
		t.Fatalf("table %v, selection %v", table, page.GetSelection())
	}
	clusters, err := pageOf(token, "/planning", map[string]string{"tab": "clusters"})
	if err != nil || len(recordsOf(clusters)) == 0 {
		t.Fatalf("the Clusters tab lists the officer's clusters as cards: %v", err)
	}
	if _, err := pageOf(token, "/planning", map[string]string{"priority_allocation": "x"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("a page opened from a priority allocation is still the existing application's: %v", err)
	}
}

func TestARoleWithoutPlanningIsTurnedAway(t *testing.T) {
	borrowAccount(t, "business-transformation@edify.org")
	token := sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/planning", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Business Transformation officer opening Planning: %v, want not found", err)
	}
}
