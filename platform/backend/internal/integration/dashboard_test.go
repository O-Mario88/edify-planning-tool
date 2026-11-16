//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"
)

// dashboardTables is what the golden files, in the order it files them.
var dashboardTables = []string{`"user"`, "staff_profile", "activity", "leave"}

// The existing feed's field officer Home over work the seed lacks:
// past-due work in each state "What needs you now" draws, this week's work
// in each state the week draws, monitored partner work, leave this week,
// and an officer with no work at all, for this week and the weeks either
// side. Skipped unless EDIFY_DASHBOARD_GOLDEN names a file
// internal/dashboard/testdata/golden.py wrote within the last half hour
// (its dates are today's).
func TestOfficerHomeMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_DASHBOARD_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_DASHBOARD_GOLDEN is not set")
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
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden was written at %s; write it again", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		// Signing in as the golden's own officer leaves its session and its
		// sign-in behind.
		for _, table := range []string{"refresh_token", "login_event"} {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE user_id LIKE 'gdsh%%'`, table)); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
		for i := len(dashboardTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gdsh%%'`, dashboardTables[i])); err != nil {
				t.Errorf("clearing %s: %v", dashboardTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range dashboardTables {
		key := table
		if table == `"user"` {
			key = "user"
		}
		for _, row := range golden.Rows[key] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing of the officer's Home")
	}
	compareGolden(t, "/dashboard", golden.Answers)
}
