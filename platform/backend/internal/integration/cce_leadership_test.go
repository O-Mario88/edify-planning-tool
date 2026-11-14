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
	var golden hrRegisterGolden
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s", golden.Today)
	}
	ctx := context.Background()
	// Only the golden's own rows (ids starting "gcl"), children first.
	children := []string{"cce_cceo_coaching", "cce_regional_engagement", "cce_regional_report", "activity"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gcl%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range []string{"activity", "cce_regional_report", "cce_regional_engagement", "cce_cceo_coaching"} {
		for _, row := range golden.Rows[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	byPath := map[string][]goldenAnswer{}
	for _, a := range golden.Answers {
		byPath[a.Path] = append(byPath[a.Path], goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	for path, answers := range byPath {
		compareGolden(t, path, answers)
	}
}
