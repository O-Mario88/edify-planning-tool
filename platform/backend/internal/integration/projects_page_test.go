//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Special Projects page over project work the seed
// lacks (closed, partner-delivered, under way, awaiting and returned by IA,
// handed to a partner, the year before, paid, with costs and partners), for
// every reader the page opens for and one it refuses, with each filter,
// another tab and another selected project. Skipped unless
// EDIFY_PROJECTS_GOLDEN names a file internal/projectspage/testdata/
// golden.py wrote today.
func TestProjectsPageMatchesTheExistingFeedOverProjectWorkTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_PROJECTS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PROJECTS_GOLDEN is not set")
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
	// Only the golden's own rows (ids starting "gpj"), children first.
	children := []string{"activity_schedule_cost_line", "activity", "project_partner_assignment",
		"project_staff_assignment", "project"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpj%'`); err != nil {
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
		t.Fatal("the golden asks nothing of /projects")
	}
	compareGolden(t, "/projects", answers)
}
