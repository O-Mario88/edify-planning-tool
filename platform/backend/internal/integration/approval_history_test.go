//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
)

// approvalHistoryTables is what the golden files, and the order it leaves.
var approvalHistoryTables = []string{"weekly_fund_request"}

// The existing feed's Finance Approval History over weekly fund requests the
// seed lacks (one in every stage of the chain, one whose owner has no
// account, one in an early week that the seed's requests push to the second
// page), for the Accountant on each page, the Admin, Impact Assessment and
// readers it refuses. Skipped unless EDIFY_APPROVAL_HISTORY_GOLDEN names a
// file internal/approvalhistory/testdata/golden.py wrote.
func TestApprovalHistoryMatchesTheExistingFeedOverRequestsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_APPROVAL_HISTORY_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_APPROVAL_HISTORY_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden hrRegisterGolden
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(approvalHistoryTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gah%%'`, approvalHistoryTables[i])); err != nil {
				t.Errorf("clearing %s: %v", approvalHistoryTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range approvalHistoryTables {
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
		t.Fatal("the golden asks nothing of Approval History")
	}
	compareGolden(t, "/accounts/approval-history/", answers)
}
