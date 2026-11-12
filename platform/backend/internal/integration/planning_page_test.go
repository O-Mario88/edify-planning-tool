//go:build integration

package integration

import (
	"context"
	"testing"

	"connectrpc.com/connect"
)

// The gateway under test has no existing application behind it, so every
// answer here is Go's, and a tab Go does not answer is unavailable.
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
	var table bool
	for _, b := range page.GetBlocks() {
		if tb := b.GetTable(); tb != nil {
			table = true
			if want := min(listed, 15); len(tb.GetRows()) != want {
				t.Fatalf("%d rows on the first page, want %d", len(tb.GetRows()), want)
			}
		}
	}
	if !table || page.GetSelection().GetNoun() != "schools selected" {
		t.Fatalf("table %v, selection %v", table, page.GetSelection())
	}
	if _, err := pageOf(token, "/planning", map[string]string{"tab": "clusters"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("the Clusters tab is still the existing application's: %v", err)
	}
}

func TestARoleWithoutPlanningIsTurnedAway(t *testing.T) {
	borrowAccount(t, "business-transformation@edify.org")
	token := sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/planning", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Business Transformation officer opening Planning: %v, want not found", err)
	}
}
