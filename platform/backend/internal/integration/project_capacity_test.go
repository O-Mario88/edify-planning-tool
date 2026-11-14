//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Project Capacity over projects and allocations the
// seed does not hold (enough staff to page, full, near capacity and
// available, a paused project, one without allocations, a closed one, staff
// of every planning role and none, a deleted People record), compared whole.
// Skipped unless EDIFY_PROJECT_CAPACITY_GOLDEN names a file
// internal/projectcapacity/testdata/golden.py wrote today (the visits are
// the operational year's).
func TestProjectCapacityMatchesTheExistingFeedOverAllocationsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_PROJECT_CAPACITY_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PROJECT_CAPACITY_GOLDEN is not set")
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
	// Only the golden's own rows (ids starting "gpc"), children first.
	children := []string{"activity", "project_school_assignment", "project_staff_capacity", "project", "staff_profile", "user"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpc%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for i := len(children) - 1; i >= 0; i-- {
		table := children[i]
		for _, row := range golden.Rows[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	compareGolden(t, "/projects/capacity", answers)
}
