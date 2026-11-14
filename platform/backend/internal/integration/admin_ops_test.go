//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's platform-operations registers over records the seed
// does not hold (tickets in every kind of status, the queue read as its one
// form and as a list, incidents of every severity, maintenance work of both
// kinds), compared whole, and refused to a reader who may not open them.
// Skipped unless EDIFY_ADMIN_OPS_GOLDEN names a file internal/adminops/
// testdata/golden.py wrote today.
func TestTheAdminOpsRegistersMatchTheExistingFeedOverRecordsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_ADMIN_OPS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ADMIN_OPS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden hrRegisterGolden
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s", golden.Today)
	}
	ctx := context.Background()
	// Only the golden's own rows (ids starting "gao").
	tables := []string{"admin_ops_work_item", "admin_support_ticket", "admin_system_incident", "admin_maintenance_template"}
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gao%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range tables {
		for _, row := range golden.Rows[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	byPath := map[string][]goldenAnswer{}
	for _, a := range golden.Answers {
		byPath[a.Path] = append(byPath[a.Path], goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	for path, answers := range byPath {
		compareGolden(t, path, answers)
	}
}
