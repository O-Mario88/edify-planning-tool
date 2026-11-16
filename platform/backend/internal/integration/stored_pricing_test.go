//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"sort"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
)

// Every live activity priced by Go (pricing.PriceStored: which way it is
// priced, then its cost) against the lines the existing single cost writer
// itself writes for it (reprice_activity, rolled back). Skipped unless
// EDIFY_STORED_ORACLE names a file internal/pricing/testdata/stored_oracle.py
// wrote today.
func TestGoPricesEveryStoredActivityAsTheWriterWritesIt(t *testing.T) {
	path := os.Getenv("EDIFY_STORED_ORACLE")
	if path == "" {
		t.Skip("EDIFY_STORED_ORACLE is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var oracle struct {
		Today      string                       `json:"today"`
		Rows       map[string][]json.RawMessage `json:"rows"`
		Activities []struct {
			ID        string  `json:"id"`
			Refused   string  `json:"refused"`
			Unchanged bool    `json:"unchanged"`
			Lines     [][]any `json:"lines"`
		} `json:"activities"`
	}
	if err := json.Unmarshal(raw, &oracle); err != nil {
		t.Fatal(err)
	}
	if oracle.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the oracle was written on %s", oracle.Today)
	}
	// The days the oracle filed (ids starting "gpd"), children first.
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
	sortLines := func(ls [][]any) {
		sort.Slice(ls, func(i, j int) bool {
			a, _ := json.Marshal(ls[i])
			b, _ := json.Marshal(ls[j])
			return string(a) < string(b)
		})
	}
	paths := map[string]int{}
	differing := 0
	for _, want := range oracle.Activities {
		got, err := pricing.PriceStored(ctx, gateway, want.ID)
		switch {
		case errors.Is(err, pricing.ErrLeftAsPriced):
			paths["left as priced"]++
			if !want.Unchanged {
				differing++
				t.Errorf("%s: Go says the writer leaves its lines; the writer changed them", want.ID)
			}
			continue
		case want.Refused != "":
			if err == nil {
				differing++
				t.Errorf("%s: the writer refused (%s); Go priced it", want.ID, want.Refused)
			}
			continue
		case err != nil:
			t.Fatalf("%s: %v", want.ID, err)
		}
		paths[got.Path]++
		lines := [][]any{}
		for _, l := range got.Cost.Lines {
			unit := int64(0)
			if l.Unit != nil {
				unit = *l.Unit
			}
			lines = append(lines, []any{l.Key, l.Label, float64(unit), float64(l.Qty), float64(l.Amount)})
		}
		wantLines := append([][]any{}, want.Lines...)
		sortLines(lines)
		sortLines(wantLines)
		if !reflect.DeepEqual(lines, wantLines) {
			differing++
			if differing <= 5 {
				t.Errorf("%s (%s) differs\n go:     %v\n writer: %v", want.ID, got.Path, lines, wantLines)
			}
		}
	}
	t.Logf("%d activities priced, %d differing, by path %v", len(oracle.Activities), differing, paths)
}
