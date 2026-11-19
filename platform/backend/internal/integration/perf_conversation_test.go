//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestThePerformanceConversationMatchesTheExistingPage files the officers,
// agreements, priorities and commitments
// internal/perfconversation/testdata/golden.py filed, asks
// /performance-conversation as each reader the golden asked in the year's
// open window (a measured priority's conversation handed on), then with the
// window shut, and compares each page whole; the window is put back.
// Skipped unless EDIFY_PERF_CONVERSATION_GOLDEN names that file, written
// within the hour.
func TestThePerformanceConversationMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_PERF_CONVERSATION_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PERF_CONVERSATION_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	type answer struct {
		goldenAnswer
		HandedOn bool `json:"handed_on"`
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Window  string                       `json:"window"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Open    []answer                     `json:"open"`
		Locked  []answer                     `json:"locked"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	// Children first, each found by the column named; filed parents first.
	// The officers' sign-ins (their sessions and login events) go before them.
	tables := [][2]string{{"hr_value_commitment", "review_id"}, {"hr_performance_priority", "review_id"}, {"hr_performance_review", "id"},
		{"staff_supervisor_assignment", "id"}, {"staff_profile", "id"}, {"refresh_token", "user_id"}, {"login_event", "user_id"}, {"user", "id"}}
	clear := func() {
		for _, tc := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+tc[0]+`" WHERE `+tc[1]+` LIKE 'gpcv%'`); err != nil {
				t.Errorf("clearing %s: %v", tc[0], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for i := len(tables) - 1; i >= 0; i-- {
		table := tables[i][0]
		if tables[i][1] == "user_id" {
			continue // made by signing in, never filed
		}
		for _, row := range golden.Tables[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	asked := func(list []answer) []goldenAnswer {
		out := []goldenAnswer{}
		for _, a := range list {
			if a.HandedOn {
				// Go hands it on, as it does a page that redirects.
				a.Status = 302
			}
			out = append(out, a.goldenAnswer)
		}
		return out
	}
	if len(golden.Open) == 0 || len(golden.Locked) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/performance-conversation", asked(golden.Open))

	var fy, window string
	if err := admin.QueryRow(ctx, `SELECT fy, active_window FROM hr_performance_cycle WHERE active_window = $1 ORDER BY id LIMIT 1`,
		golden.Window).Scan(&fy, &window); err != nil {
		t.Fatalf("reading the open cycle: %v", err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `UPDATE hr_performance_cycle SET active_window = $2 WHERE fy = $1`, fy, window); err != nil {
			t.Errorf("reopening the cycle's window: %v", err)
		}
	})
	if _, err := admin.Exec(ctx, `UPDATE hr_performance_cycle SET active_window = 'none' WHERE fy = $1`, fy); err != nil {
		t.Fatalf("shutting the cycle's window: %v", err)
	}
	compareGolden(t, "/performance-conversation", asked(golden.Locked))
}
