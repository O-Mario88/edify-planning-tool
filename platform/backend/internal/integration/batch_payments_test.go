//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
)

// batchPaymentTables is the order the golden's rows are filed in (a row
// before the rows that point at it) and, reversed, the order they leave.
var batchPaymentTables = []string{"activity", "activity_schedule_cost_line", "advance_request"}

// The existing feed's Batch Payments Center over payable work the seed lacks
// (staff work confirmed for an advance at a school, cluster-wide and with two
// advances; work already paid, awaiting confirmation or deleted; partner work
// verified and payable, verified and paid, and not yet verified), for the
// Accountant on each tab, the Admin, Impact Assessment and readers it
// refuses. Skipped unless EDIFY_BATCH_PAYMENTS_GOLDEN names a file
// internal/batchpayments/testdata/golden.py wrote.
func TestBatchPaymentsMatchesTheExistingFeedOverWorkTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_BATCH_PAYMENTS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_BATCH_PAYMENTS_GOLDEN is not set")
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
		for i := len(batchPaymentTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gbp%%'`, batchPaymentTables[i])); err != nil {
				t.Errorf("clearing %s: %v", batchPaymentTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range batchPaymentTables {
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
		t.Fatal("the golden asks nothing of Batch Payments")
	}
	compareGolden(t, "/accounts/batch-payments/", answers)
}
