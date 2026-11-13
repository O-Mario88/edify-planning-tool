//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Leave Policies over recorded holidays the seed does
// not hold (a declared day, one on a national holiday, an announced Eid, a
// past day), compared whole. Skipped unless EDIFY_LEAVE_POLICIES_GOLDEN names
// a file internal/leavepolicies/testdata/golden.py wrote today (the national
// list moves with the day).
func TestLeavePoliciesMatchTheExistingFeedOverRecordedHolidays(t *testing.T) {
	path := os.Getenv("EDIFY_LEAVE_POLICIES_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_LEAVE_POLICIES_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden calendarGolden
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s", golden.Today)
	}
	ctx := context.Background()
	// Only the golden's own holidays (ids starting "glp") are filed and
	// cleared; the leave policies the existing view writes on its first read
	// are filed where they are missing and left, as that view leaves them.
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM public_holiday WHERE id LIKE 'glp%'`); err != nil {
			t.Errorf("clearing the holidays: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows["leave_type_policy"] {
		if _, err := admin.Exec(ctx, `INSERT INTO leave_type_policy SELECT * FROM json_populate_record(NULL::leave_type_policy, $1::json)
ON CONFLICT DO NOTHING`, string(row)); err != nil {
			t.Fatalf("filing a policy: %v", err)
		}
	}
	for _, row := range golden.Rows["public_holiday"] {
		if _, err := admin.Exec(ctx, `INSERT INTO public_holiday SELECT * FROM json_populate_record(NULL::public_holiday, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a holiday: %v", err)
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	compareGolden(t, "/leave/policies", answers)
}
