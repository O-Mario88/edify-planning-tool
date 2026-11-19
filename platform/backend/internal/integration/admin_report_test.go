//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestReportAProblemMatchesTheExistingPage files the tickets
// internal/adminops/testdata/report_golden.py filed (dated tomorrow), asks
// /support as each reader the golden asked, and compares the whole page.
// Skipped unless EDIFY_ADMIN_REPORT_GOLDEN names that file, written within
// the hour.
func TestReportAProblemMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_ADMIN_REPORT_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ADMIN_REPORT_GOLDEN is not set")
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
		if _, err := admin.Exec(ctx, `DELETE FROM admin_support_ticket WHERE id LIKE 'garp%'`); err != nil {
			t.Errorf("clearing the tickets: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Tables["admin_support_ticket"] {
		if _, err := admin.Exec(ctx, `INSERT INTO admin_support_ticket SELECT * FROM json_populate_record(NULL::admin_support_ticket, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a ticket: %v", err)
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/support", golden.Answers)
}
