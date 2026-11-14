//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Quality Flags over flags the seed does not hold (every
// status and an unknown one, other raisers, an assignee without an account,
// more than the register lists), compared whole. Skipped unless
// EDIFY_QUALITY_FLAGS_GOLDEN names a file internal/qualityflags/testdata/
// golden.py wrote today.
func TestQualityFlagsMatchTheExistingFeedOverFlagsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_QUALITY_FLAGS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_QUALITY_FLAGS_GOLDEN is not set")
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
	// Only the golden's own flags (ids starting "gqf").
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM cd_flag WHERE id LIKE 'gqf%'`); err != nil {
			t.Errorf("clearing the flags: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows["cd_flag"] {
		if _, err := admin.Exec(ctx, `INSERT INTO cd_flag SELECT * FROM json_populate_record(NULL::cd_flag, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a flag: %v", err)
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	compareGolden(t, "/quality-checks", answers)
}
