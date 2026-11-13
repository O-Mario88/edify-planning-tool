//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func trainingSummaryOf(t *testing.T, email string, query map[string]string) *screensv1.GetPageResponse {
	t.Helper()
	borrowAccount(t, email)
	page, err := pageOf(sessionOf(t, email, seededPassword).GetAccessToken(), "/team-planning-oversight/", query)
	if err != nil {
		t.Fatalf("%s opening the Training Summary: %v", email, err)
	}
	return page
}

func summaryTable(t *testing.T, page *screensv1.GetPageResponse) *screensv1.PageTable {
	t.Helper()
	blocks := page.GetBlocks()
	table := blocks[len(blocks)-1].GetTable()
	if table == nil {
		t.Fatalf("the last block is not the summary table: %v", blocks)
	}
	return table
}

// fileHandover files one training hand-over still waiting for the
// Partner's date, monitored by the account's staff profile, at a school and
// for a training no project delivers (removed when the test ends): what
// makes a training a row of the summary.
func fileHandover(t *testing.T, email string) {
	t.Helper()
	ctx := context.Background()
	if _, err := admin.Exec(ctx, `
INSERT INTO partner_assignment
SELECT (jsonb_populate_record(NULL::partner_assignment, to_jsonb(p) || jsonb_build_object(
  'id', 'gpts900002', 'status', 'assigned', 'project_id', NULL, 'source_activity_id', NULL, 'scheduled_activity_id', NULL,
  'replaces_assignment_id', NULL, 'support_type', NULL, 'visit_number', NULL, 'training_number', NULL,
  'monitoring_staff_id', (SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = $1),
  'school_id', (SELECT id FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1),
  'training_course_id', (SELECT ci.id FROM activity_catalogue_item ci WHERE ci.is_training_course
    AND ci.id NOT IN (SELECT catalogue_item_id FROM activity_project_mapping) ORDER BY ci.id LIMIT 1)))).*
FROM partner_assignment p ORDER BY p.id LIMIT 1`, email); err != nil {
		t.Fatalf("filing a hand-over: %v", err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM partner_assignment WHERE id = 'gpts900002'`); err != nil {
			t.Errorf("removing the test's hand-over: %v", err)
		}
	})
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTheTrainingSummaryReadsTheCountryCeilingAdminSets(t *testing.T) {
	fileHandover(t, "pl1@edify.org")
	page := trainingSummaryOf(t, "admin@edify.org", map[string]string{"view": "trainings"})
	if page.GetHeader().GetTitle() != "Planning Oversight" || page.GetBlocks()[0].GetLinkTabs() == nil {
		t.Fatalf("the page: %v", page.GetHeader())
	}
	table := summaryTable(t, page)
	if len(table.GetRows()) == 0 {
		t.Fatal("the hand-over filed for the test is not listed")
	}
	fy := page.GetBlocks()[1].GetFilters().GetFilters()[0].GetValue()
	first := table.GetRows()[0].GetCells()[2]
	if !strings.HasSuffix(first.GetText(), " / Set") || !strings.HasPrefix(first.GetHref(), "/team-planning-oversight/?view=trainings&tab=schools") {
		t.Fatalf("Total Covered with no Country Ceiling, for Admin: %q %q", first.GetText(), first.GetHref())
	}
	training := strings.SplitN(strings.SplitN(first.GetHref(), "training=", 2)[1], "&", 2)[0]
	ctx := context.Background()
	if _, err := admin.Exec(ctx, `INSERT INTO training_country_ceiling (id, created_at, updated_at, fy, country, ceiling, set_by, set_by_role, note, training_id)
VALUES ('gpts900001', now(), now(), $1, 'Uganda', 1000, '', 'Admin', '[Go parity check]', $2)`, fy, training); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM training_country_ceiling WHERE id = 'gpts900001'`); err != nil {
			t.Errorf("removing the test's ceiling: %v", err)
		}
	})
	cells := summaryTable(t, trainingSummaryOf(t, "admin@edify.org", map[string]string{"view": "trainings"})).GetRows()[0].GetCells()
	if !strings.HasSuffix(cells[2].GetText(), " / 1,000") || cells[5].GetText() == "—" {
		t.Fatalf("with a Country Ceiling of 1,000: %q, remaining %q", cells[2].GetText(), cells[5].GetText())
	}
	lead := summaryTable(t, trainingSummaryOf(t, "pl1@edify.org", map[string]string{"view": "trainings"})).GetRows()[0].GetCells()
	if !strings.HasSuffix(lead[2].GetText(), " / 1,000") || lead[2].GetHref() != "" {
		t.Fatalf("a Programme Lead reads the country's ceiling and opens nothing from it: %q %q", lead[2].GetText(), lead[2].GetHref())
	}
	if lead[4].GetText() != "1" || lead[4].GetTone() != "warning" || !strings.HasPrefix(lead[6].GetText(), "1") {
		t.Fatalf("the hand-over awaits the partner, in the Lead's own column: %q %q", lead[4].GetText(), lead[6].GetText())
	}
}

func TestTheTrainingSummaryTurnsAwayAnOfficer(t *testing.T) {
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/team-planning-oversight/", map[string]string{"view": "trainings"}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a CCEO opening the Training Summary: %v, want not found", err)
	}
}
