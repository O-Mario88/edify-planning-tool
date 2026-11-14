//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"sort"
	"strings"
	"testing"
	"time"
)

// The existing feed's Priorities page in a year with approved allocations:
// an officer's own contract, a Programme Lead's team contract (the team root
// and the officers' allocations it does not cover), the country contract for
// Admin and the Country Director, and readers with no allocation; over
// schools, rate and attendance milestones, an unlinked one, inactive and
// draft rows, planned and completed activities and live and reversed
// credits. Skipped unless EDIFY_ALLOCATIONS_GOLDEN names a file
// internal/allocations/testdata/golden.py wrote today.
func TestApprovedAllocationsMatchTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_ALLOCATIONS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ALLOCATIONS_GOLDEN is not set")
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
	children := []string{"hr_milestone_progress_credit", "hr_milestone_allocation", "hr_milestone_activity_rule",
		"hr_priority_milestone", "hr_strategic_priority", "activity"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpa%'`); err != nil {
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
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: inPlanOrder(t, a.Body)})
	}
	compareGolden(t, "/my-performance", answers)
}

// inPlanOrder puts the existing answer's distributed priorities in the
// plan's order (each milestone's source order, which the golden's titles
// follow). The existing queryset sets no order, so its rows come as the
// planner reaches them; Go lists them in the plan's order.
func inPlanOrder(t *testing.T, body json.RawMessage) json.RawMessage {
	t.Helper()
	var page map[string]any
	if err := json.Unmarshal(body, &page); err != nil {
		t.Fatal(err)
	}
	blocks, _ := page["blocks"].([]any)
	for _, b := range blocks {
		table, _ := b.(map[string]any)["table"].(map[string]any)
		if title, _ := table["title"].(string); !strings.HasPrefix(title, "Distributed priorities") {
			continue
		}
		rows, _ := table["rows"].([]any)
		first := func(i int) string {
			cells, _ := rows[i].(map[string]any)["cells"].([]any)
			text, _ := cells[0].(map[string]any)["text"].(string)
			return text
		}
		sort.SliceStable(rows, func(i, j int) bool { return first(i) < first(j) })
	}
	out, err := json.Marshal(page)
	if err != nil {
		t.Fatal(err)
	}
	return out
}
