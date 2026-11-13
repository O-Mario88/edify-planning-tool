//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// hrRegisterGolden is what internal/hrregister/testdata/golden.py writes: the
// rows it filed and the existing feed's answers over them, register by
// register.
type hrRegisterGolden struct {
	Today   string                       `json:"today"`
	Rows    map[string][]json.RawMessage `json:"rows"`
	Answers []struct {
		Email  string            `json:"email"`
		Path   string            `json:"path"`
		Query  map[string]string `json:"query"`
		Status int               `json:"status"`
		Body   json.RawMessage   `json:"body"`
	} `json:"answers"`
}

// The existing feed's answers over People records the seed does not hold
// (enough to page, every lifecycle state, lines and none, another country, a
// deleted record and a deleted account), compared whole. Skipped unless
// EDIFY_HR_REGISTER_GOLDEN names a file internal/hrregister/testdata/
// golden.py wrote today.
func TestTheHRRegistersMatchTheExistingFeedOverPeopleTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_HR_REGISTER_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_HR_REGISTER_GOLDEN is not set")
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
	// Children first; only the golden's own rows (ids starting "ghr").
	children := []string{"document_acknowledgement", "document_version", "document_asset", "hr_employee_compliance_record", "hr_compliance_requirement", "hr_application", "hr_candidate", "hr_vacancy", "hr_onboarding_task", "hr_onboarding_plan", "hr_offboarding", "hr_safety_incident", "hr_staff_recognition",
		"staff_supervisor_assignment", "staff_profile", "user"}
	// One transaction each way: a document and its current version name each
	// other, and the foreign keys are checked when the transaction commits.
	clear := func() {
		tx, err := admin.Begin(ctx)
		if err != nil {
			t.Fatalf("clearing: %v", err)
		}
		defer func() { _ = tx.Rollback(ctx) }()
		for _, table := range children {
			if _, err := tx.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'ghr%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
				return
			}
		}
		if err := tx.Commit(ctx); err != nil {
			t.Errorf("clearing: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	tx, err := admin.Begin(ctx)
	if err != nil {
		t.Fatalf("filing: %v", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	for _, table := range []string{"user", "staff_profile", "staff_supervisor_assignment", "hr_staff_recognition", "hr_safety_incident",
		"hr_offboarding", "hr_onboarding_plan", "hr_onboarding_task", "hr_vacancy", "hr_candidate", "hr_application",
		"hr_compliance_requirement", "hr_employee_compliance_record", "document_asset", "document_version", "document_acknowledgement"} {
		for _, row := range golden.Rows[table] {
			if _, err := tx.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatalf("filing: %v", err)
	}
	byPath := map[string][]goldenAnswer{}
	for _, a := range golden.Answers {
		byPath[a.Path] = append(byPath[a.Path], goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	if len(byPath) == 0 {
		t.Fatal("no answer to compare")
	}
	for path, answers := range byPath {
		compareGolden(t, path, answers)
	}
}
