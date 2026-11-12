//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"

	"connectrpc.com/connect"
)

// Core School Oversight's two tabs of planned work are My Plan's Core
// sheets of the schools shown, drawn by Go (no existing application is
// behind the gateway under test), and a download's format is not found.
// FY 2026's visits hold the seed's completed partner visits, whose forms
// Go reads through gateway_read.activity_evidence_kind.
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
	if _, err := pageOf(token, "/core-schools-oversight/", map[string]string{"tab": "core_visits", "fy": "2026"}); err != nil {
		t.Errorf("FY 2026's visits, a partner's completed work among them: %v", err)
	}
	if _, err := pageOf(token, "/core-schools-oversight/", map[string]string{"tab": "core_visits", "format": "xlsx"}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("format: got %v", err)
	}
}

// The gateway reads evidence only through gateway_read.activity_evidence_kind:
// each activity's uploaded, unquarantined kinds. A quarantined upload is not
// in it, and neither is anything else of the record (its storage key, file
// name, uploader); evidence_record itself stays refused.
func TestTheEvidenceViewShowsOnlyUploadedKinds(t *testing.T) {
	ctx := context.Background()
	var activityID string
	if err := admin.QueryRow(ctx, `SELECT id FROM activity WHERE deleted_at IS NULL ORDER BY id LIMIT 1`).Scan(&activityID); err != nil {
		t.Skip("the test database has no activity")
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM evidence_record WHERE id LIKE 'gev9%'`); err != nil {
			t.Errorf("removing the test's evidence: %v", err)
		}
	})
	for _, e := range []struct {
		id, kind    string
		quarantined bool
	}{{"gev900001", "visit_form", false}, {"gev900002", "visit_form", false}, {"gev900003", "attendance_form", true}} {
		if _, err := admin.Exec(ctx, `
INSERT INTO evidence_record (created_at, updated_at, id, kind, uri, original_name, storage_provider, uploaded_by, status,
  scan_status, quarantined, preview_status, view_count, activity_id)
VALUES (now(), now(), $1, $2, 'private/secret-key', 'secret.pdf', 'local', 'someone', 'pending', 'clean', $3, 'none', 0, $4)`,
			e.id, e.kind, e.quarantined, activityID); err != nil {
			t.Fatalf("filing evidence %s: %v", e.id, err)
		}
	}
	rows, err := gateway.Query(ctx, `SELECT * FROM gateway_read.activity_evidence_kind WHERE activity_id = $1`, activityID)
	if err != nil {
		t.Fatal(err)
	}
	columns := []string{}
	for _, f := range rows.FieldDescriptions() {
		columns = append(columns, f.Name)
	}
	var kinds []string
	for rows.Next() {
		var id, kind string
		if err := rows.Scan(&id, &kind); err != nil {
			t.Fatal(err)
		}
		kinds = append(kinds, kind)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	if strings.Join(columns, ",") != "activity_id,kind" {
		t.Errorf("the view shows %v, want the activity and the kind only", columns)
	}
	if strings.Join(kinds, ",") != "visit_form" {
		t.Errorf("the kinds in: %v, want one visit form (two uploads) and no quarantined attendance form", kinds)
	}
	if _, err := gateway.Exec(ctx, `SELECT uri FROM evidence_record LIMIT 1`); err == nil {
		t.Error("the gateway reads evidence_record itself")
	}
}
