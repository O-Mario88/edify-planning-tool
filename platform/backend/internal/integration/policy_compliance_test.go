//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Policy and Manual Compliance over acknowledgements the
// seed does not hold (every state, enough to page, read fully, partly, not
// at all and outside the viewer, overdue, a draft policy left out), compared
// whole for every reader who opens the page, and refused to those who may
// not. Skipped unless EDIFY_POLICY_COMPLIANCE_GOLDEN names a file
// internal/policycompliance/testdata/golden.py wrote today (overdue moves
// with the day).
func TestPolicyComplianceMatchesTheExistingFeedOverAcknowledgementsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_POLICY_COMPLIANCE_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_POLICY_COMPLIANCE_GOLDEN is not set")
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
	// Children first; only the golden's own rows (ids starting "gpl"). One
	// transaction each way: a document and its current version name each
	// other, and the foreign keys are checked when the transaction commits.
	children := []string{"document_acknowledgement", "document_version", "document_asset"}
	inTx := func(what string, rows func(exec func(sql string, args ...any) error) error) {
		tx, err := admin.Begin(ctx)
		if err != nil {
			t.Fatalf("%s: %v", what, err)
		}
		defer func() { _ = tx.Rollback(ctx) }()
		if err := rows(func(sql string, args ...any) error { _, err := tx.Exec(ctx, sql, args...); return err }); err != nil {
			t.Fatalf("%s: %v", what, err)
		}
		if err := tx.Commit(ctx); err != nil {
			t.Fatalf("%s: %v", what, err)
		}
	}
	clear := func() {
		inTx("clearing", func(exec func(string, ...any) error) error {
			for _, table := range children {
				if err := exec(`DELETE FROM "` + table + `" WHERE id LIKE 'gpl%'`); err != nil {
					return err
				}
			}
			return nil
		})
	}
	clear()
	t.Cleanup(clear)
	inTx("filing", func(exec func(string, ...any) error) error {
		for _, table := range []string{"document_asset", "document_version", "document_acknowledgement"} {
			for _, row := range golden.Rows[table] {
				if err := exec(`INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
					return err
				}
			}
		}
		return nil
	})
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	compareGolden(t, "/policy-compliance", answers)
}
