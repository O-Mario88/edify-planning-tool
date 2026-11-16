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

// projectMyPlanTables is the order the golden's rows are filed in (a row
// before the rows that point at it) and, reversed, the order they leave.
var projectMyPlanTables = []string{
	"activity", "activity_schedule_cost_line", "advance_request",
}

// The existing feed's Special Projects My Plan over project work the seed
// lacks (the coordinator's own visits, training and cluster meeting, a visit
// someone else runs, partner work assigned and verified, work returned,
// rescheduled, overdue, completed without accepted evidence, awaiting IA,
// cancelled and of another year, with cost lines and advances), for the
// coordinator with each period, project, status, search, partner and type,
// the Admin, the Country Director, a Programme Lead, a CCEO with no project
// and readers it refuses. Dates sit around the day the golden was written,
// so the answers hold for half an hour. Skipped unless
// EDIFY_PROJECT_MY_PLAN_GOLDEN names a file
// internal/projectmyplan/testdata/golden.py wrote within the half hour.
func TestProjectMyPlanMatchesTheExistingFeedOverWorkTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_PROJECT_MY_PLAN_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PROJECT_MY_PLAN_GOLDEN is not set")
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
		for i := len(projectMyPlanTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gsp%%'`, projectMyPlanTables[i])); err != nil {
				t.Errorf("clearing %s: %v", projectMyPlanTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range projectMyPlanTables {
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
		t.Fatal("the golden asks nothing of the project My Plan")
	}
	compareGolden(t, "/projects/my-plan", answers)
}
