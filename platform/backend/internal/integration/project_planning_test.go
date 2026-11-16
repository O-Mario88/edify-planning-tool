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

// projectPlanningTables is the order the golden's rows are filed in (a row
// before the rows that point at it) and, reversed, the order they leave.
var projectPlanningTables = []string{
	"activity", "activity_schedule_cost_line", "partner_assignment",
}

// The existing feed's Special Projects Planning over the seed's 25 project
// schools and project work the seed lacks (a staff visit this week, partner
// work assigned, work returned, overdue and rescheduled, a cancelled visit,
// a training with a cost line, a visit collecting an SSA, a handover a
// partner has not dated), for the coordinator on each tab, page size, page,
// selection, project, delivery and activity type, search, quarter and year,
// a Programme Lead, the Admin, the Country Director, a CCEO with no project
// and readers it refuses. Dates sit around the day the golden was written,
// so the answers hold for half an hour. Skipped unless
// EDIFY_PROJECT_PLANNING_GOLDEN names a file
// internal/projectplanning/testdata/golden.py wrote within the half hour.
func TestProjectPlanningMatchesTheExistingFeedOverWorkTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_PROJECT_PLANNING_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PROJECT_PLANNING_GOLDEN is not set")
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
		for i := len(projectPlanningTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gpl%%'`, projectPlanningTables[i])); err != nil {
				t.Errorf("clearing %s: %v", projectPlanningTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range projectPlanningTables {
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
		t.Fatal("the golden asks nothing of project Planning")
	}
	compareGolden(t, "/projects/planning", answers)
}
