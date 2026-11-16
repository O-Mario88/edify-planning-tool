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

// debriefTables is the order the golden's rows are filed in (a debrief
// before the rows that point at it) and, reversed, the order they leave.
var debriefTables = []string{
	"daily_debrief", "daily_debrief_recipient", "daily_debrief_activity_link", "daily_debrief_challenge",
	"daily_debrief_commitment", "daily_debrief_action", "daily_debrief_peer_solution", "daily_debrief_insight",
}

// The existing feed's Field Debrief Dashboard over debriefs the seed lacks
// (a Programme Lead's officers, the Lead, another team and a partner, this
// period and the one before, every status and risk, a restricted debrief
// routed to HR, challenges, linked activities, commitments, actions, a peer
// solution and an open insight), for every reader it opens for with each
// tab, range, filter and page, and for a reader it refuses. Skipped unless
// EDIFY_DEBRIEFS_GOLDEN names a file internal/debriefs/testdata/golden.py
// wrote within the half hour. The existing feed draws every tab with the open
// tab's rows; Go gives each tab its own (owner, 2026-11-16: "Fix the tabs"),
// so each tab is compared with the existing page asked with that tab open.
func TestTheDebriefDashboardMatchesTheExistingFeedOverDebriefsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_DEBRIEFS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_DEBRIEFS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Rows    map[string][]json.RawMessage `json:"rows"`
		Written time.Time                    `json:"written"`
		Answers []struct {
			Email     string            `json:"email"`
			Query     map[string]string `json:"query"`
			Status    int               `json:"status"`
			Body      json.RawMessage   `json:"body"`
			TabTables []json.RawMessage `json:"tab_tables"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden answers were written at %s; their times have moved", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(debriefTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gdf%%'`, debriefTables[i])); err != nil {
				t.Errorf("clearing %s: %v", debriefTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range debriefTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		body, err := ownTabs(a.Body, a.TabTables)
		if err != nil {
			t.Fatalf("%s %v: %v", a.Email, a.Query, err)
		}
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: body})
	}
	if len(answers) == 0 {
		t.Fatal("the golden asks nothing of the dashboard")
	}
	compareGolden(t, "/debriefs", answers)
}

// ownTabs is the existing answer with each tab holding the table the
// existing page shows when that tab is the one open.
func ownTabs(body json.RawMessage, tables []json.RawMessage) (json.RawMessage, error) {
	if len(tables) == 0 {
		return body, nil
	}
	var page map[string]any
	if err := json.Unmarshal(body, &page); err != nil {
		return nil, err
	}
	blocks, _ := page["blocks"].([]any)
	for _, b := range blocks {
		block, _ := b.(map[string]any)
		segs, ok := block["segments"].(map[string]any)
		if !ok {
			continue
		}
		list, _ := segs["segments"].([]any)
		if len(list) != len(tables) {
			return nil, fmt.Errorf("%d tabs but %d tab tables", len(list), len(tables))
		}
		for i, seg := range list {
			var own any
			if err := json.Unmarshal(tables[i], &own); err != nil {
				return nil, err
			}
			seg.(map[string]any)["blocks"] = own
		}
	}
	return json.Marshal(page)
}
