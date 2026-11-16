//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
)

// partnerPaymentTables is the order the golden's rows are filed in (a row
// before the rows that point at it) and, reversed, the order they leave.
var partnerPaymentTables = []string{"activity", "activity_schedule_cost_line", "partner_payment", "partner_invoice", "partner_invoice_item"}

// The existing feed's Partner Payment Queue over partner work and invoices
// the seed lacks (verified work awaiting payment at a school, with its 50%
// advance paid, cluster-wide with nobody responsible and with no costs;
// verified and paid; not yet verified; invoices the Programme Lead
// confirmed, with and without the partner's document, and one still with
// the Programme Lead), for the Accountant, the Admin, Impact Assessment and
// readers it refuses. Skipped unless EDIFY_PARTNER_PAYMENTS_GOLDEN names a
// file internal/partnerpayments/testdata/golden.py wrote.
func TestPartnerPaymentsMatchesTheExistingFeedOverWorkTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_PARTNER_PAYMENTS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PARTNER_PAYMENTS_GOLDEN is not set")
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
		for i := len(partnerPaymentTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gpp%%'`, partnerPaymentTables[i])); err != nil {
				t.Errorf("clearing %s: %v", partnerPaymentTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range partnerPaymentTables {
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
		t.Fatal("the golden asks nothing of Partner Payments")
	}
	compareGolden(t, "/accounts/partner-payments/", answers)
}
