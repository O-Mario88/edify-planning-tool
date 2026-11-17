//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mytargets"
)

// myTargetsTables is what the golden files, parents first, and the column
// its rows are found by (the ledger by its sources; a ledger mark, which
// names the officer, is cleared by its owner and year as well).
var myTargetsTables = [][2]string{
	{"hr_strategic_priority_cycle", "id"}, {"hr_strategic_priority", "id"}, {"hr_priority_milestone", "id"},
	{"hr_milestone_activity_rule", "id"}, {"hr_milestone_allocation", "id"}, {"hr_milestone_period_target", "id"},
	{"mscs_story", "id"}, {"ssa_record", "id"}, {"project", "id"}, {"activity", "id"}, {"hr_milestone_progress_credit", "id"},
	{"hr_activity_priority_link", "id"}, {"monthly_personal_target", "id"},
	{"hr_performance_review", "id"}, {"hr_performance_priority", "id"}, {"pd_request", "id"}, {"core_plan", "id"},
	{"staff_school_assignment", "id"}, {"project_staff_assignment", "id"}, {"project_school_assignment", "id"},
	{"ssa_score", "id"}, {"target_achievement_ledger", "source_id"}, {"target_ledger_dirty", "owner_id"},
}

// The existing feed's My Targets for an officer with agreed priorities,
// work in every state the ledger and the gap reasons tell apart, Core
// Schools and the portfolio's groups, for this month, an earlier month and
// the year before, and for an officer with no agreement; Projects assigned
// to the officer and to a Project Coordinator, who is shown the workspace
// strip; a partner's two logins, which have no People record; the officer's
// year read with its ledger marked stale after work changed (Go works the
// rebuild out in memory); and in the year after, approved milestone allocations of every
// kind — each page whole.
// Skipped unless EDIFY_MY_TARGETS_GOLDEN names a file
// internal/mytargets/testdata/golden.py wrote within the last half hour.
func TestMyTargetsMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_MY_TARGETS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_MY_TARGETS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []struct {
			goldenAnswer
			At time.Time `json:"at"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden was written at %s; write it again", golden.Written)
	}
	ctx := context.Background()
	// The ledger mark names the officer, not a "gmt" row: it is found by
	// its owner and year.
	var marks []struct {
		Owner string `json:"owner_id"`
		FY    string `json:"fy"`
	}
	for _, row := range golden.Rows["target_ledger_dirty"] {
		var m struct {
			Owner string `json:"owner_id"`
			FY    string `json:"fy"`
		}
		if err := json.Unmarshal(row, &m); err != nil {
			t.Fatal(err)
		}
		marks = append(marks, m)
	}
	clear := func() {
		for i := len(myTargetsTables) - 1; i >= 0; i-- {
			table, column := myTargetsTables[i][0], myTargetsTables[i][1]
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE %s LIKE 'gmt%%'`, table, column)); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
		for _, m := range marks {
			if _, err := admin.Exec(ctx, `DELETE FROM target_ledger_dirty WHERE owner_id = $1 AND fy = $2`, m.Owner, m.FY); err != nil {
				t.Errorf("clearing a ledger mark: %v", err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, tc := range myTargetsTables {
		for _, row := range golden.Rows[tc[0]] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, tc[0], tc[0])
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", tc[0], err)
			}
		}
	}
	compared, differing := 0, 0
	for _, answer := range golden.Answers {
		query := url.Values{}
		for k, v := range answer.Query {
			query.Set(k, v)
		}
		at := answer.At
		page, served, err := mytargets.NewService(gateway, func() time.Time { return at }).Build(ctx, snoozer(t, answer.Email), mytargets.Path, query)
		if err != nil {
			t.Fatalf("%s %v: %v", answer.Email, answer.Query, err)
		}
		if !served {
			t.Errorf("%s %v: handed on", answer.Email, answer.Query)
			continue
		}
		want := &screensv1.GetPageResponse{}
		if err := protojson.Unmarshal(answer.Body, want); err != nil {
			t.Fatal(err)
		}
		compared++
		differing += samePage(t, fmt.Sprintf("%s %v", answer.Email, answer.Query), page, want)
	}
	t.Logf("%d answers compared, %d differing", compared, differing)
	if compared == 0 {
		t.Fatal("Go drew none of the pages")
	}
}
