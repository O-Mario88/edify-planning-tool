//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Users page over a team the seed does not hold (enough
// members to page, logins in every state, a member who left, schools held
// and not), compared whole, with the readers who lead no team sent to the
// dashboard and the one who may not open it refused. Skipped unless
// EDIFY_PARTNER_USERS_GOLDEN names a file internal/partnerusers/testdata/
// golden.py wrote today.
func TestPartnerUsersMatchesTheExistingFeedOverATeamTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_PARTNER_USERS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PARTNER_USERS_GOLDEN is not set")
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
	// Only the golden's own rows (ids starting "gpu"), children first.
	children := []string{"partner_school_member", "partner_member", "user"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpu%'`); err != nil {
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
	compareGolden(t, "/partner/users", answers)
}
