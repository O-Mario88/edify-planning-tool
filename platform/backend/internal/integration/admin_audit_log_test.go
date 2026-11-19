//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestTheAuditLogMatchesTheExistingPage files the rows
// internal/adminpanel/testdata/audit_golden.py filed (a hundred and one audit
// rows dated tomorrow, a quarter of an hour apart), asks
// /admin-panel/audit-log as each reader the golden asked, on each page, and
// compares the whole page. Skipped unless EDIFY_ADMIN_AUDIT_LOG_GOLDEN names
// that file, written within the hour.
func TestTheAuditLogMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_ADMIN_AUDIT_LOG_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ADMIN_AUDIT_LOG_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM audit_log WHERE id LIKE 'gaud%'`); err != nil {
			t.Errorf("clearing the audit rows: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Tables["audit_log"] {
		if _, err := admin.Exec(ctx, `INSERT INTO audit_log SELECT * FROM json_populate_record(NULL::audit_log, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing an audit row: %v", err)
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/admin-panel/audit-log", golden.Answers)
}
