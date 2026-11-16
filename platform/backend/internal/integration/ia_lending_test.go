//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Lending Evidence over loans and evidence the seed
// lacks (reported use, enrolment, outputs and teacher completions; impact
// conclusions in every state; disbursements in two years, one reversed), for
// every reader the page opens for and those it refuses, each tab, each state,
// a page past the end and values the page does not offer. Skipped unless
// EDIFY_IA_LENDING_GOLDEN names a file internal/iapages/testdata/
// lending_golden.py wrote today.
func TestLendingEvidenceMatchesTheExistingFeedOverLoansTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_IA_LENDING_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_IA_LENDING_GOLDEN is not set")
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
	// Only the golden's own rows (ids starting "gle"), children first.
	children := []string{"bt_loan_disbursement_reversal", "bt_loan_impact_assessment", "bt_teacher_degree_beneficiary",
		"bt_purpose_asset_output", "bt_enrolment_snapshot", "bt_loan_purpose_allocation", "bt_loan_disbursement",
		"bt_funding_facility_allocation", "bt_mfi_loan", "bt_case"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gle%'`); err != nil {
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
	if len(answers) == 0 {
		t.Fatal("the golden asks nothing of Lending Evidence")
	}
	compareGolden(t, "/ia/lending-evidence/", answers)
}
