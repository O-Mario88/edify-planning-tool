//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Partner Activities over partner work the seed does
// not hold (visits ahead, overdue, completed, undated and dated only by
// time; hand-overs undated, overdue, released, for a cluster and matching a
// visit), as HR through every filter, the other readers who keep the page and
// the partner logins, with the staff who are sent on to Partner Oversight.
// Skipped unless EDIFY_PARTNERS_GOLDEN names a file internal/partnerworkspace/
// testdata/golden.py wrote today.
func TestPartnersMatchesTheExistingFeedOverPartnerWorkTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_PARTNERS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PARTNERS_GOLDEN is not set")
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
	// Only the golden's own rows (ids starting "gpw"), children first.
	children := []string{"partner_assignment", "activity", "partner"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpw%'`); err != nil {
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
	compareGolden(t, "/partners", answers)
}
