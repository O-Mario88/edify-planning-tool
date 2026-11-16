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

// fundApprovalTables is the order the golden's rows are filed in (a row
// before the rows that point at it) and, reversed, the order they leave.
var fundApprovalTables = []string{
	"activity", "activity_schedule_cost_line", "weekly_fund_request", "weekly_fund_request_line", "audit_log",
}

// The existing feed's Fund Approvals over a team's weeks of fund plans the
// seed lacks (officers' requests in every state, partner-delivered work and
// provider-paid costs, work with no cost rate, a request waiting on the
// Country Director, an approval today and a return yesterday), for the
// Program Lead with each filter, officer, sort and week, the Country
// Director, the Admin and readers it refuses. Times sit a minute before the
// golden was written, so the answers hold for half an hour. Skipped unless
// EDIFY_FUND_APPROVALS_GOLDEN names a file internal/fundapprovals/testdata/
// golden.py wrote within the half hour.
func TestFundApprovalsMatchesTheExistingFeedOverPlansTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_FUND_APPROVALS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_FUND_APPROVALS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		hrRegisterGolden
		Written time.Time `json:"written"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden answers were written at %s; their times have moved", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(fundApprovalTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gfa%%'`, fundApprovalTables[i])); err != nil {
				t.Errorf("clearing %s: %v", fundApprovalTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range fundApprovalTables {
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
		t.Fatal("the golden asks nothing of Fund Approvals")
	}
	compareGolden(t, "/fund-approvals", answers)
}
