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

// cpdLearningTables is the order the golden's rows are filed in (a row
// before the rows that point at it) and, reversed, the order they leave.
var cpdLearningTables = []string{
	"pd_role_allocation", "pd_allocation", "pd_request", "pd_certificate",
}

// The existing feed's HR Professional Development Dashboard over courses the
// seed lacks (officers' courses in every part of their life, last year's,
// another country's, a self-funded one, allocations, a role's default and
// certificates), for HR with each filter, the Admin, the Country Director,
// the Regional VP, Impact Assessment and a reader it refuses. Dates sit
// around the day the golden was written, so the answers hold for half an
// hour. Skipped unless EDIFY_CPD_LEARNING_GOLDEN names a file
// internal/cpdlearning/testdata/golden.py wrote within the half hour.
func TestCPDLearningMatchesTheExistingFeedOverCoursesTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_CPD_LEARNING_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_CPD_LEARNING_GOLDEN is not set")
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
		for i := len(cpdLearningTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gcp%%'`, cpdLearningTables[i])); err != nil {
				t.Errorf("clearing %s: %v", cpdLearningTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range cpdLearningTables {
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
		t.Fatal("the golden asks nothing of the PD dashboard")
	}
	compareGolden(t, "/cpd-learning", answers)
}
