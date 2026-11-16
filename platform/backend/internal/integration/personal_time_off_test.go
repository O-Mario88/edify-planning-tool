//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"
)

// ptoTables is what the golden files, in the order it files them.
var ptoTables = []string{"leave", "calendar_block", "temporary_coverage_assignment", "leave_balance"}

// The existing feed's Personal Time Off over leave the seed lacks: an
// officer's requests in every state, a cover each way, an upcoming blackout
// and every reader's balances as the existing service writes them, for each
// reader. Skipped unless EDIFY_PERSONAL_TIME_OFF_GOLDEN names a file
// internal/personaltimeoff/testdata/golden.py wrote within the last half
// hour (its covers and constraints are today's).
func TestPersonalTimeOffMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_PERSONAL_TIME_OFF_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PERSONAL_TIME_OFF_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden was written at %s; write it again", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(ptoTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gpto%%'`, ptoTables[i])); err != nil {
				t.Errorf("clearing %s: %v", ptoTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range ptoTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing of Personal Time Off")
	}
	compareGolden(t, "/personal-time-off/", golden.Answers)
}
