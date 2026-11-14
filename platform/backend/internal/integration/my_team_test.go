//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's My Team for the four Programme Leads (this year, last
// year, a year not offered), Admin and Impact Assessment (no team) and a CCEO
// (refused), over leave and coaching the seed does not hold. The golden reads
// each lead's page once first, so the existing page has rebuilt the ledgers it
// rebuilds on a read; Go answers from them without writing. Skipped unless
// EDIFY_MY_TEAM_GOLDEN names a file internal/myteam/testdata/golden.py wrote
// today.
func TestMyTeamMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_MY_TEAM_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_MY_TEAM_GOLDEN is not set")
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
	children := []string{"leave", "cce_cceo_coaching"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gmt%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range children {
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
	compareGolden(t, "/my-team", answers)
}
