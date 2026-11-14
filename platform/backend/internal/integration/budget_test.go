//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Budget for a CCEO and a Program Lead over planned
// costs the seed lacks (a shared day's own rates, trainings fed by their
// headcount, a meeting dated only by its month, the Admin category, a
// monitored partner training, an unowned line, the week that crosses
// 1 October, and work that draws nothing), by month, quarter and year,
// both scopes, and a reader the page refuses; and the country's Budget
// over advances and month budgets (locked, approved, and a month with none,
// which the existing page creates as it reads and Go only reads). Skipped unless
// EDIFY_BUDGET_GOLDEN names a file internal/budgetpage/testdata/golden.py
// wrote today.
func TestBudgetMatchesTheExistingFeedOverPlannedCostsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_BUDGET_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_BUDGET_GOLDEN is not set")
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
	// Only the golden's own rows (ids starting "gbg"), children first.
	children := []string{"advance_request", "monthly_work_plan_budget", "activity_schedule_cost_line", "activity", "daily_visit_batch"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gbg%'`); err != nil {
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
	compareGolden(t, "/budget", answers)
}
