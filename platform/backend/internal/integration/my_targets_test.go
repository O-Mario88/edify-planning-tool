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
// its rows are found by (the ledger by its sources).
var myTargetsTables = [][2]string{
	{"mscs_story", "id"}, {"ssa_record", "id"}, {"activity", "id"}, {"monthly_personal_target", "id"},
	{"hr_performance_review", "id"}, {"hr_performance_priority", "id"}, {"pd_request", "id"}, {"core_plan", "id"},
	{"staff_school_assignment", "id"}, {"ssa_score", "id"}, {"target_achievement_ledger", "source_id"},
}

// The existing feed's My Targets for an officer with agreed priorities,
// work in every state the ledger and the gap reasons tell apart, Core
// Schools and the portfolio's groups, for this month, an earlier month and
// the year before, and for an officer with no agreement — each page whole.
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
	clear := func() {
		for i := len(myTargetsTables) - 1; i >= 0; i-- {
			table, column := myTargetsTables[i][0], myTargetsTables[i][1]
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE %s LIKE 'gmt%%'`, table, column)); err != nil {
				t.Errorf("clearing %s: %v", table, err)
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
