//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's monthly CCE reports over reports the seed does not
// hold (the Regional Lead's in every status, one reviewed, other authors and
// countries, enough to page), compared whole. Skipped unless EDIFY_CCE_LEADERSHIP_GOLDEN names
// a file internal/ccelead/testdata/golden.py wrote today (the lead's overdue notice moves with the day).
func TestTheCCEReportsMatchTheExistingFeedOverReportsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_CCE_LEADERSHIP_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_CCE_LEADERSHIP_GOLDEN is not set")
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
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM cce_regional_report WHERE id LIKE 'gcl%'`); err != nil {
			t.Errorf("clearing the reports: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows["cce_regional_report"] {
		if _, err := admin.Exec(ctx, `INSERT INTO cce_regional_report SELECT * FROM json_populate_record(NULL::cce_regional_report, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a report: %v", err)
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	compareGolden(t, "/cce-leadership/reports", answers)
}
