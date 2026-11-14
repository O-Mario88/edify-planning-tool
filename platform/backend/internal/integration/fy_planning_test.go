//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Fiscal Year Planning over planning policies the seed does not hold (the
// next year opened, a later year not open in another country, an earlier year
// without an opening moment), compared whole. Skipped unless
// EDIFY_FY_PLANNING_GOLDEN names a file internal/fyplanning/testdata/
// golden.py wrote today.
func TestFiscalYearPlanningMatchesTheExistingFeedOverPoliciesTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_FY_PLANNING_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_FY_PLANNING_GOLDEN is not set")
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
	// Only the golden's own policies (ids starting "gfy").
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM fiscal_year_planning_policy WHERE id LIKE 'gfy%'`); err != nil {
			t.Errorf("clearing the policies: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows["fiscal_year_planning_policy"] {
		if _, err := admin.Exec(ctx, `INSERT INTO fiscal_year_planning_policy SELECT * FROM json_populate_record(NULL::fiscal_year_planning_policy, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a policy: %v", err)
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	compareGolden(t, "/planning/fiscal-years", answers)
}
