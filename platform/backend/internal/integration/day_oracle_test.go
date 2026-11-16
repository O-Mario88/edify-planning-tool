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

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
)

// Days a visit shares, planned by Go as the existing pricing plans them
// (_plan_day and the member costs _write_day_lines writes): a primary day
// split three ways, a Mixed day, two secondary days in a row (the second the
// trip home), a day whose card lacks a rate (refused), an empty day, and a
// day whose members carry lines of their own. Skipped unless
// EDIFY_DAY_ORACLE names a file internal/pricing/testdata/day_oracle.py
// wrote today.
func TestGoPlansEveryDayAsTheExistingPricing(t *testing.T) {
	path := os.Getenv("EDIFY_DAY_ORACLE")
	if path == "" {
		t.Skip("EDIFY_DAY_ORACLE is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var oracle struct {
		Today string                       `json:"today"`
		Rows  map[string][]json.RawMessage `json:"rows"`
		Days  []struct {
			ID        string   `json:"id"`
			Refused   bool     `json:"refused"`
			Mark      string   `json:"mark"`
			District  string   `json:"district"`
			ReturnDay bool     `json:"returnDay"`
			RawPool   [][2]any `json:"pool"`
			Members   []struct {
				ID   string     `json:"id"`
				Cost oracleCost `json:"cost"`
			} `json:"members"`
		} `json:"days"`
	}
	if err := json.Unmarshal(raw, &oracle); err != nil {
		t.Fatal(err)
	}
	if oracle.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the oracle was written on %s", oracle.Today)
	}
	ctx := context.Background()
	children := []string{"activity", "daily_visit_batch", "cost_setting", "cost_catalogue"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpd%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for i := len(children) - 1; i >= 0; i-- {
		table := children[i]
		for _, row := range oracle.Rows[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	differing := 0
	for _, want := range oracle.Days {
		got, err := pricing.PlanDay(ctx, gateway, want.ID)
		var refusal *pricing.DayRefusal
		if want.Refused {
			if !errors.As(err, &refusal) {
				differing++
				t.Errorf("%s: the existing pricing refused the day; Go: %v", want.ID, err)
			}
			continue
		}
		if err != nil {
			t.Fatalf("%s: %v", want.ID, err)
		}
		pool := [][2]any{}
		for _, s := range got.Pool {
			pool = append(pool, [2]any{s.Key, float64(s.Amount)})
		}
		ok := got.Mark == want.Mark && got.DistrictType == want.District && got.ReturnDay == want.ReturnDay &&
			reflect.DeepEqual(pool, append([][2]any{}, want.RawPool...)) && len(got.Members) == len(want.Members)
		for i := 0; ok && i < len(got.Members); i++ {
			ok = got.Members[i].ActivityID == want.Members[i].ID && want.Members[i].Cost.equals(got.Members[i].Cost)
		}
		if !ok {
			differing++
			g, _ := json.Marshal(got)
			w, _ := json.Marshal(want)
			t.Errorf("%s differs\n go:       %s\n existing: %s", want.ID, g, w)
		}
	}
	t.Logf("%d days planned, %d differing", len(oracle.Days), differing)
}
