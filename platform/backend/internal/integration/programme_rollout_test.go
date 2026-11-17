//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/programmerollout"
)

// programmeRolloutTables is what the golden files, parents first, each with
// the column its rows are found by.
var programmeRolloutTables = [][2]string{{"user", "id"}, {"staff_profile", "id"}, {"activity_catalogue_item", "id"}, {"activity", "id"}, {"cluster_activity_attendance", "activity_id"},
	{"ssa_record", "id"}, {"ssa_score", "ssa_record_id"}, {"partner_assignment", "id"}, {"staff_school_assignment", "id"},
	{"cce_regional_engagement", "id"}, {"partner_engagement", "id"}}

// The existing feed's Programme Rollout on its Trainings view over the
// team's trainings the seed lacks (delivered at a school and at a cluster by
// a partner with attendance confirmed, in review, upcoming, a partner's
// dated session, one months ahead, one cancelled, one last year), for the
// Programme Lead each year and with the view named, and the officer and the
// Accountant it refuses. Skipped unless EDIFY_PROGRAMME_ROLLOUT_GOLDEN names
// a file internal/programmerollout/testdata/golden.py wrote within the hour.
func TestProgrammeRolloutMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_PROGRAMME_ROLLOUT_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PROGRAMME_ROLLOUT_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	unfile := func() {
		// What signing the filed lead in wrote about them.
		for _, table := range []string{"refresh_token", "login_event", "presence_time"} {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE user_id LIKE 'gpr%%'`, table)); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
		for i := len(programmeRolloutTables) - 1; i >= 0; i-- {
			table, column := programmeRolloutTables[i][0], programmeRolloutTables[i][1]
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %q WHERE %s LIKE 'gpr%%'`, table, column)); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	unfile()
	t.Cleanup(unfile)
	for _, tc := range programmeRolloutTables {
		for _, row := range golden.Rows[tc[0]] {
			sql := fmt.Sprintf(`INSERT INTO %q SELECT * FROM json_populate_record(NULL::%q, $1::json)`, tc[0], tc[0])
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", tc[0], err)
			}
		}
	}
	compareGolden(t, programmerollout.Path, golden.Answers)
}
