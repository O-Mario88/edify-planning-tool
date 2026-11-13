//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"

	"connectrpc.com/connect"
)

func TestProjectMonitoringOpensOneProjectATabForTheCoordinator(t *testing.T) {
	borrowAccount(t, "coordinator@edify.org")
	token := sessionOf(t, "coordinator@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/projects/monitoring", nil)
	if err != nil {
		t.Fatal(err)
	}
	if page.GetHeader().GetTitle() != "Project Monitoring" || !strings.HasPrefix(page.GetHeader().GetDescription(), "Every school in your projects") {
		t.Fatalf("the header: %v", page.GetHeader())
	}
	blocks := page.GetBlocks()
	if len(blocks[0].GetFilters().GetFilters()) != 7 || blocks[0].GetFilters().GetHidden()["project"] == "" {
		t.Fatalf("the filters: %v", blocks[0])
	}
	if blocks[1].GetLinkTabs().GetLabel() != "Project Monitoring" {
		t.Fatalf("the workspace strip: %v", blocks[1])
	}
	tabs := blocks[3].GetLinkTabs().GetTabs()
	table := tableOf(page)
	if len(tabs) == 0 || !tabs[0].GetActive() || table == nil || len(table.GetRows()) == 0 {
		t.Fatalf("the project tabs %v and table %v", tabs, table)
	}
	row := table.GetRows()[0]
	cells := row.GetCells()
	if len(cells) != 19 || cells[10].GetText() != "Awaiting Project Coordinator Action" || row.GetPickId() == "" {
		t.Fatalf("a school awaiting the coordinator: %v", row)
	}
	labels := []string{}
	for _, a := range cells[18].GetActions() {
		labels = append(labels, a.GetLabel())
	}
	if strings.Join(labels, ",") != "View,Schedule,Assign,Withdraw from project" {
		t.Fatalf("the coordinator's doors: %v", labels)
	}
	empty, err := pageOf(token, "/projects/monitoring", map[string]string{"district": "No such district"})
	if err != nil {
		t.Fatal(err)
	}
	if rows := tableOf(empty).GetRows(); len(rows) != 1 || rows[0].GetCells()[0].GetText() != "No school in this project matches these filters." {
		t.Fatalf("a filter no school matches: %v", rows)
	}
}

func TestProjectMonitoringIsRefusedToRolesWithoutIt(t *testing.T) {
	borrowAccount(t, "business-transformation@edify.org")
	token := sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/projects/monitoring", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("Business Transformation opening Project Monitoring: %v, want not found", err)
	}
}

// A school allocation is not drawn by Go yet: the page is passed on to the
// existing application (absent here), never answered short.
func TestProjectMonitoringPassesOnAPageWithAllocations(t *testing.T) {
	ctx := context.Background()
	var projectID, staffID string
	if err := admin.QueryRow(ctx, `
SELECT p.id, sp.id FROM project p, staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE p.deleted_at IS NULL AND u.email = 'cceo@edify.org' ORDER BY p.name LIMIT 1`).Scan(&projectID, &staffID); err != nil {
		t.Skipf("no project or officer: %v", err)
	}
	if _, err := admin.Exec(ctx, `
INSERT INTO project_staff_capacity (id, created_at, updated_at, max_schools, set_by, set_by_role, project_id, staff_id)
VALUES ('goparitypm1', now(), now(), 3, 'goparity', 'ProjectCoordinator', $1, $2)`, projectID, staffID); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM project_staff_capacity WHERE id = 'goparitypm1'`); err != nil {
			t.Errorf("removing the test's allocation: %v", err)
		}
	})
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/projects/monitoring", nil)
	if err == nil || connect.CodeOf(err) == connect.CodeNotFound {
		t.Fatalf("a page with an allocation: %v %v, want it passed on", page, err)
	}
}
