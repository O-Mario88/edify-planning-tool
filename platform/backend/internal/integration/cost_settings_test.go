//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Cost Catalogue and Cost Intelligence over a register
// of two pages (35 costs linked to one governed activity) and a cost review
// queue, as the readers who open each door, a reader who opens neither, and
// the register's and the coverage's pages. Skipped unless
// EDIFY_COST_SETTINGS_GOLDEN names a file internal/costsettings/testdata/
// golden.py wrote today.
func TestCostSettingsMatchesTheExistingFeedOverARegisterTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_COST_SETTINGS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_COST_SETTINGS_GOLDEN is not set")
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
	// Only the golden's own rows (ids starting "gcs"), children first.
	children := []string{"activity_cost_review", "cost_setting"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gcs%'`); err != nil {
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
	byPath := map[string][]goldenAnswer{}
	for _, a := range golden.Answers {
		byPath[a.Path] = append(byPath[a.Path], goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	for _, door := range []string{"/cost-settings", "/cost-intelligence"} {
		if len(byPath[door]) == 0 {
			t.Fatalf("the golden asks nothing of %s", door)
		}
		compareGolden(t, door, byPath[door])
	}
}
