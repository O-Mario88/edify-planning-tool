//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"regexp"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// updatedAt is the footer's "Updated <moment>", the minute the page was
// drawn: the golden's and Go's are drawn minutes apart.
var updatedAt = regexp.MustCompile(`· Updated [A-Z][a-z]+ \d{2}, \d{4} \d{2}:\d{2} [AP]M$`)

// TestTheConsolidatedFundAllocationMatchesTheExistingPage files the
// activities, cost lines and country admin plan
// internal/budgetpage/testdata/fund_allocation_golden.py filed, asks
// /finance/fund-allocation as each reader the golden asked, and compares
// each page whole but for the minute its footer says it was updated.
// Skipped unless EDIFY_FUND_ALLOCATION_GOLDEN names that file, written
// within the hour.
func TestTheConsolidatedFundAllocationMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_FUND_ALLOCATION_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_FUND_ALLOCATION_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	// Children first; filed parents first.
	tables := []string{"admin_budget_line", "monthly_work_plan_budget", "activity_schedule_cost_line", "activity"}
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gfa%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for i := len(tables) - 1; i >= 0; i-- {
		for _, row := range golden.Tables[tables[i]] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+tables[i]+`" SELECT * FROM json_populate_record(NULL::"`+tables[i]+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", tables[i], err)
			}
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGoldenMasked(t, "/finance/fund-allocation", golden.Answers, func(page *screensv1.GetPageResponse) {
		for _, b := range page.GetBlocks() {
			for _, item := range b.GetPanel().GetItems() {
				if text, ok := item.Kind.(*screensv1.PagePanelItem_Text); ok {
					text.Text = updatedAt.ReplaceAllString(text.Text, "· Updated —")
				}
			}
		}
	})
}
