//go:build integration

package integration

import (
	"context"
	"testing"

	"connectrpc.com/connect"
)

// The gateway under test has no existing application behind it, so a page
// answered at all here is Go's, and a page Go leaves to the existing
// application fails.

func TestMyPlanOpensEmptyForStaffWhoHoldNothing(t *testing.T) {
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/my-plan", map[string]string{"period": "week", "fy": "2026"})
	if err != nil {
		t.Skipf("the seeded Impact Assessment account holds work here: %v", err)
	}
	if page.GetHeader().GetTitle() != "My Plan" || page.GetHeader().GetActions()[0].GetHref() != "/my-plan/export-drawer?fy=2026&period=week" {
		t.Fatalf("header %+v", page.GetHeader())
	}
	tables := 0
	for _, block := range page.GetBlocks() {
		if table := block.GetTable(); table != nil {
			tables++
			if table.GetCount() != "0" || table.GetEmptyAction().GetHref() != "/planning" {
				t.Errorf("table %+v", table)
			}
		}
	}
	if tables != 4 || page.GetBlocks()[0].GetLinkTabs().GetTabs()[0].GetActive() != true {
		t.Fatalf("%d tables, tabs %+v", tables, page.GetBlocks()[0].GetLinkTabs())
	}
	if page.GetSelection().GetNoun() != "activities selected" {
		t.Fatalf("selection %+v", page.GetSelection())
	}
}

func TestMyPlanIsRefusedToRolesWithoutIt(t *testing.T) {
	borrowAccount(t, "business-transformation@edify.org")
	token := sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/my-plan", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("got %v", err)
	}
	// A ?format= the feed has no renderer for is not found for anyone.
	borrowAccount(t, "ia@edify.org")
	token = sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/my-plan", map[string]string{"format": "csv"}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("format: got %v", err)
	}
}

// A training ceiling set for the reader puts My Training Summary on their
// page, which is not Go's yet: the page is left to the existing application.
func TestMyPlanLeavesAPageWithATrainingCeilingToTheExistingApplication(t *testing.T) {
	ctx := context.Background()
	var staffID, trainingID string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'ia@edify.org'`).Scan(&staffID); err != nil {
		t.Skipf("no staff profile: %v", err)
	}
	if err := admin.QueryRow(ctx, `SELECT id FROM activity_catalogue_item ORDER BY id LIMIT 1`).Scan(&trainingID); err != nil {
		t.Skipf("no catalogue item: %v", err)
	}
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/my-plan", nil); err != nil {
		t.Skipf("the seeded Impact Assessment account holds work here: %v", err)
	}
	const id = "goparitymyplanceiling"
	if _, err := admin.Exec(ctx, `INSERT INTO training_ceiling (created_at, updated_at, id, fy, ceiling, set_by, set_by_role, note, staff_id, training_id)
VALUES (now(), now(), $1, '2027', 5, 'goparity', 'Admin', '', $2, $3)`, id, staffID, trainingID); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM training_ceiling WHERE id = $1`, id); err != nil {
			t.Errorf("removing the ceiling: %v", err)
		}
	})
	if _, err := pageOf(token, "/my-plan", nil); err == nil || connect.CodeOf(err) == connect.CodeNotFound {
		t.Fatalf("the page was answered by Go (or refused): %v", err)
	}
}
