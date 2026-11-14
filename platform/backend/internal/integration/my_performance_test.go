//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Priorities page for every role that may open it, on
// each tab and for the year before (no cycle, no review), over a development
// item and a commitment with its behaviour, reflection and observation.
// Skipped unless EDIFY_MY_PERFORMANCE_GOLDEN names a file
// internal/myperformance/testdata/golden.py wrote today.
func TestMyPerformanceMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_MY_PERFORMANCE_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_MY_PERFORMANCE_GOLDEN is not set")
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
	tables := []string{"hr_development_plan_item", "hr_value_commitment"}
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gmp%'`); err != nil {
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
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	compareGolden(t, "/my-performance", answers)
}
