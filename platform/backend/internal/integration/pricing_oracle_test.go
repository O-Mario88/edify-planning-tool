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

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
)

type oracleCost struct {
	Amount       int64    `json:"amount"`
	CostMissing  bool     `json:"cost_missing"`
	MissingItems []string `json:"missing_items"`
	Lines        []struct {
		Label   string `json:"label"`
		Key     string `json:"key"`
		Unit    *int64 `json:"unit"`
		Qty     int64  `json:"qty"`
		Amount  int64  `json:"amount"`
		Missing bool   `json:"missing"`
	} `json:"lines"`
}

func (o *oracleCost) equals(c costing.Cost) bool {
	if o.Amount != c.Amount || o.CostMissing != c.CostMissing || len(o.Lines) != len(c.Lines) ||
		!reflect.DeepEqual(append([]string{}, o.MissingItems...), append([]string{}, c.MissingItems...)) {
		return false
	}
	for i, l := range o.Lines {
		g := c.Lines[i]
		if l.Label != g.Label || l.Key != g.Key || l.Qty != g.Qty || l.Amount != g.Amount || l.Missing != g.Missing ||
			(l.Unit == nil) != (g.Unit == nil) || (l.Unit != nil && *l.Unit != *g.Unit) {
			return false
		}
	}
	return true
}

// Every live activity priced by Go as the existing single cost writer prices
// it (_costing_input, then calculate_dual), on the cards the oracle files: a
// newer operational card in force for ten days of April, with a threshold,
// a rate below its minimum, a rate left out and a linked cost; and a dearer
// reference card. Skipped unless EDIFY_PRICING_ORACLE names a file
// internal/pricing/testdata/oracle.py wrote today.
func TestGoPricesEveryActivityAsTheExistingCostWriter(t *testing.T) {
	path := os.Getenv("EDIFY_PRICING_ORACLE")
	if path == "" {
		t.Skip("EDIFY_PRICING_ORACLE is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var oracle struct {
		Today      string                       `json:"today"`
		Rows       map[string][]json.RawMessage `json:"rows"`
		Activities []struct {
			ID          string      `json:"id"`
			Error       string      `json:"error"`
			Operational *oracleCost `json:"operational"`
			Reference   *oracleCost `json:"reference"`
			Warnings    []string    `json:"warnings"`
			Missing     struct {
				Operational []string `json:"operational"`
				Reference   []string `json:"reference"`
			} `json:"missing"`
			Viability   string    `json:"viability"`
			CanSchedule bool      `json:"canSchedule"`
			Cards       []*string `json:"cards"`
		} `json:"activities"`
	}
	if err := json.Unmarshal(raw, &oracle); err != nil {
		t.Fatal(err)
	}
	if oracle.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the oracle was written on %s", oracle.Today)
	}
	ctx := context.Background()
	children := []string{"cost_setting", "cost_catalogue"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpr%'`); err != nil {
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
	card := func(c *pricing.Card) *string {
		if c == nil {
			return nil
		}
		return &c.ID
	}
	same := func(a, b *string) bool { return (a == nil) == (b == nil) && (a == nil || *a == *b) }
	differing := 0
	for _, want := range oracle.Activities {
		in, err := pricing.StoredInput(ctx, gateway, want.ID)
		if err != nil {
			t.Fatalf("%s: %v", want.ID, err)
		}
		got, err := pricing.Price(ctx, gateway, in)
		if want.Error != "" {
			if !errors.Is(err, pricing.ErrUnknownProfile) {
				differing++
				t.Errorf("%s: the existing writer refused (%s); Go: %v", want.ID, want.Error, err)
			}
			continue
		}
		if err != nil {
			t.Fatalf("%s: %v", want.ID, err)
		}
		ok := want.Operational.equals(got.Operational) &&
			(want.Reference == nil) == !got.HasReference &&
			(want.Reference == nil || want.Reference.equals(got.Reference)) &&
			reflect.DeepEqual(append([]string{}, want.Warnings...), got.Warnings) &&
			reflect.DeepEqual(append([]string{}, want.Missing.Operational...), got.MissingOperational) &&
			reflect.DeepEqual(append([]string{}, want.Missing.Reference...), got.MissingReference) &&
			want.Viability == got.Viability && want.CanSchedule == got.CanSchedule &&
			same(want.Cards[0], card(got.OperationalCard)) && same(want.Cards[1], card(got.ReferenceCard))
		if !ok {
			differing++
			if differing <= 5 {
				g, _ := json.Marshal(got)
				w, _ := json.Marshal(want)
				t.Errorf("%s differs\n go:       %s\n existing: %s", want.ID, g, w)
			}
		}
	}
	t.Logf("%d activities priced, %d differing", len(oracle.Activities), differing)
}
