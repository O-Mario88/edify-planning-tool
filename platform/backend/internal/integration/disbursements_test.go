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

// disbursementTables is the order the golden's rows are filed in (a row
// before the rows that point at it) and, reversed, the order they leave.
var disbursementTables = []string{
	"activity", "activity_schedule_cost_line", "fund_request", "fund_request_item",
	"weekly_fund_request", "weekly_fund_request_line", "advance_request", "partner_payment",
}

// The existing feed's Fund Disbursement Dashboard over money the seed
// lacks (monthly plans and weekly advances in every queue state, the
// advance ledger behind the month's figures, partner work awaiting payment,
// a reimbursement claim and a partner payment), for the Accountant and the
// Admin with each filter, each item, other months and years, and for
// readers it refuses. Times sit a minute before the golden was written, so
// the answers hold for half an hour. Skipped unless EDIFY_DISBURSEMENTS_GOLDEN
// names a file internal/disbursements/testdata/golden.py wrote within the
// half hour.
func TestTheDisbursementDashboardMatchesTheExistingFeedOverMoneyTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_DISBURSEMENTS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_DISBURSEMENTS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		hrRegisterGolden
		Written time.Time `json:"written"`
		// EmptyAnswers were asked before any row was filed.
		EmptyAnswers []goldenAnswer `json:"empty_answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden answers were written at %s; their times have moved", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(disbursementTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gdb%%'`, disbursementTables[i])); err != nil {
				t.Errorf("clearing %s: %v", disbursementTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	if len(golden.EmptyAnswers) == 0 {
		t.Fatal("the golden asks nothing of an empty month")
	}
	compareGolden(t, "/disbursements", golden.EmptyAnswers)
	for _, table := range disbursementTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	if len(answers) == 0 {
		t.Fatal("the golden asks nothing of the dashboard")
	}
	compareGolden(t, "/disbursements", answers)
}
