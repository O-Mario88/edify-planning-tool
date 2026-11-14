//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

type targetsCell struct {
	Key        string `json:"key"`
	Label      string `json:"label"`
	Pct        *int   `json:"pct"`
	DisplayPct *int   `json:"display_pct"`
	Achieved   int    `json:"achieved"`
	Target     int    `json:"target"`
	Status     string `json:"status"`
	Tone       string `json:"tone"`
}

// The target engine's member cells (month, Q1–Q4, the year) against the
// existing engine's, for people with agreed priorities (duplicates, an
// unmapped and a zero one, an older agreement behind a newer one), explicit
// monthly targets, a target profile, legacy targets, validated and
// unvalidated ledger rows and approved, pending and unreadable leave, on the
// year's first and last days, today and in Q2, and for the year before; read
// through the gateway's own role. Skipped unless EDIFY_TARGETS_GOLDEN names a
// file internal/targets/testdata/golden.py wrote today.
func TestTheTargetEngineMatchesTheExistingOne(t *testing.T) {
	path := os.Getenv("EDIFY_TARGETS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_TARGETS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Today   string                       `json:"today"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []struct {
			FY     string `json:"fy"`
			Today  string `json:"today"`
			People []struct {
				UserID  string        `json:"user_id"`
				StaffID string        `json:"staff_id"`
				Status  string        `json:"status"`
				Tone    string        `json:"tone"`
				Cells   []targetsCell `json:"cells"`
			} `json:"people"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s", golden.Today)
	}
	ctx := context.Background()
	children := []string{"hr_performance_priority", "hr_performance_review", "monthly_personal_target",
		"staff_target_profile", "target_achievement_ledger", "leave"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpt%'`); err != nil {
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
	compared, differing := 0, 0
	for _, answer := range golden.Answers {
		people := []targets.Person{}
		for _, p := range answer.People {
			people = append(people, targets.Person{UserID: p.UserID, StaffID: p.StaffID})
		}
		roster, err := targets.Prepare(ctx, gateway, people, answer.FY, nil)
		if errors.Is(err, targets.ErrHandOn) {
			t.Fatalf("FY %s: the engine hands on (%v); regenerate the golden: it clears the ledger marks", answer.FY, err)
		}
		if err != nil {
			t.Fatalf("FY %s: %v", answer.FY, err)
		}
		today, err := time.Parse(time.DateOnly, answer.Today)
		if err != nil {
			t.Fatal(err)
		}
		for i, want := range answer.People {
			compared++
			got := roster.Member(people[i], today)
			cells := []targetsCell{}
			for _, c := range got.Cells {
				cells = append(cells, targetsCell{Key: c.Key, Label: c.Label, Pct: c.Pct, DisplayPct: c.DisplayPct,
					Achieved: c.Achieved, Target: c.Target, Status: c.Status, Tone: c.Tone})
			}
			if got.Status != want.Status || got.Tone != want.Tone || !reflect.DeepEqual(cells, want.Cells) {
				differing++
				gotJSON, _ := json.Marshal(cells)
				wantJSON, _ := json.Marshal(want.Cells)
				t.Errorf("FY %s %s %s: %s/%s %s\n want %s/%s %s", answer.FY, answer.Today, want.UserID,
					got.Status, got.Tone, gotJSON, want.Status, want.Tone, wantJSON)
			}
		}
	}
	t.Logf("%d people's cells compared, %d differing", compared, differing)
}
