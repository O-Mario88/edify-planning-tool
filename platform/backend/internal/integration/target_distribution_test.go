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

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targetdistribution"
)

// targetDistributionTables is what the golden files, parents first.
var targetDistributionTables = []string{"hr_strategic_priority_cycle", "hr_priority_import_batch", "hr_strategic_priority"}

// The existing feed's Uganda Target Distribution for IA, the Country Director
// and the Admin over years with no master (with no year asked, a draft
// cycle's year, a year with staged imports and the seed's own year), and the
// CCEO it refuses; a year with a master, and staged imports for a reader who
// may see them, are handed on. Skipped unless EDIFY_TARGET_DISTRIBUTION_GOLDEN
// names a file internal/targetdistribution/testdata/golden.py wrote within the
// hour.
func TestTargetDistributionMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_TARGET_DISTRIBUTION_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_TARGET_DISTRIBUTION_GOLDEN is not set")
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
			HandOn bool `json:"hand_on"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	clear := func() {
		for i := len(targetDistributionTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gtd%%'`, targetDistributionTables[i])); err != nil {
				t.Errorf("clearing %s: %v", targetDistributionTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range targetDistributionTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	served := []goldenAnswer{}
	handedOn := 0
	for _, answer := range golden.Answers {
		if !answer.HandOn {
			served = append(served, answer.goldenAnswer)
			continue
		}
		query := url.Values{}
		for k, v := range answer.Query {
			query.Set(k, v)
		}
		_, ok, err := targetdistribution.NewService(gateway, time.Now).Build(ctx, snoozer(t, answer.Email), targetdistribution.Path, query)
		if err != nil || ok {
			t.Errorf("%s %v: served (%v), want handed on", answer.Email, answer.Query, err)
		}
		handedOn++
	}
	if len(served) == 0 || handedOn == 0 {
		t.Fatal("the golden asks nothing Go draws, or nothing Go hands on")
	}
	compareGolden(t, targetdistribution.Path, served)
	t.Logf("%d answers handed on", handedOn)
}
