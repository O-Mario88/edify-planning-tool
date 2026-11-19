//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

// TestTheKnowledgeCenterMatchesTheExistingPages files the rows
// internal/helpcenter/testdata/golden.py filed (its guide, and the route
// mappings that keep the home from writing on its read), asks every
// Knowledge Center reading page as each reader the golden asked, and
// compares each whole page. Skipped unless EDIFY_HELP_CENTER_GOLDEN names
// that file, written within the hour.
func TestTheKnowledgeCenterMatchesTheExistingPages(t *testing.T) {
	path := os.Getenv("EDIFY_HELP_CENTER_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_HELP_CENTER_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Routes  []json.RawMessage            `json:"route_contexts"`
		Answers []struct {
			Path string `json:"path"`
			goldenAnswer
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	routeIDs := []string{}
	for _, row := range golden.Routes {
		var r struct {
			ID string `json:"id"`
		}
		if err := json.Unmarshal(row, &r); err != nil {
			t.Fatal(err)
		}
		routeIDs = append(routeIDs, r.ID)
	}
	tables := []string{"help_center_helparticle", "help_center_helparticleroleaccess", "help_center_helparticle_related_articles",
		"help_center_helpwalkthrough", "help_center_helpglossaryterm"}
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM help_center_helparticleroutecontext WHERE id = ANY($1)`, routeIDs); err != nil {
			t.Errorf("clearing the route mappings: %v", err)
		}
		for i := len(tables) - 1; i >= 0; i-- {
			column := "id"
			if strings.HasSuffix(tables[i], "_related_articles") {
				column = "from_helparticle_id"
			}
			if _, err := admin.Exec(ctx, `DELETE FROM `+tables[i]+` WHERE `+column+`::text LIKE 'gshc%'`); err != nil {
				t.Errorf("clearing %s: %v", tables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	file := func(table string, rows []json.RawMessage) {
		for _, row := range rows {
			if _, err := admin.Exec(ctx, `INSERT INTO `+table+` SELECT * FROM json_populate_record(NULL::`+table+`, $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a row of %s: %v", table, err)
			}
		}
	}
	for _, table := range tables {
		file(table, golden.Tables[table])
	}
	file("help_center_helparticleroutecontext", golden.Routes)
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	byPath := map[string][]goldenAnswer{}
	order := []string{}
	for _, a := range golden.Answers {
		if _, ok := byPath[a.Path]; !ok {
			order = append(order, a.Path)
		}
		byPath[a.Path] = append(byPath[a.Path], a.goldenAnswer)
	}
	for _, p := range order {
		compareGolden(t, p, byPath[p])
	}
}
