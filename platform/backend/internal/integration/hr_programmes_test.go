//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestTheHRProgrammeRegistersMatchTheExistingPages files the People records,
// payroll checks, successors and leave
// internal/hrregister/testdata/programmes_golden.py filed, asks Culture &
// Engagement, Payroll Readiness, Succession Planning and Staff Wellness &
// Support as each reader the golden asked, and compares each page whole.
// Skipped unless EDIFY_HR_PROGRAMMES_GOLDEN names that file, written within
// the hour.
func TestTheHRProgrammeRegistersMatchTheExistingPages(t *testing.T) {
	path := os.Getenv("EDIFY_HR_PROGRAMMES_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_HR_PROGRAMMES_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Answers []struct {
			goldenAnswer
			Path string `json:"path"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	// Children first; the parents filed first.
	tables := []string{"leave", "hr_succession_candidate", "hr_payroll_readiness", "staff_profile", "user"}
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gprg%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for i := len(tables) - 1; i >= 0; i-- {
		table := tables[i]
		for _, row := range golden.Tables[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	byPath := map[string][]goldenAnswer{}
	order := []string{}
	for _, a := range golden.Answers {
		if _, seen := byPath[a.Path]; !seen {
			order = append(order, a.Path)
		}
		byPath[a.Path] = append(byPath[a.Path], a.goldenAnswer)
	}
	if len(order) != 4 {
		t.Fatalf("the golden asks %d registers, want 4", len(order))
	}
	for _, p := range order {
		compareGolden(t, p, byPath[p])
	}
}
