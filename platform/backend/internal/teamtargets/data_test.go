package teamtargets

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// _rank: the strongest full-year share first and numbered; a member with no
// target for the year last, by name, without a place.
func TestRankRowsPutsTheUnsetLastWithoutAPlace(t *testing.T) {
	year := func(pct *int, target int) []targets.Cell {
		return []targets.Cell{{Key: "fy", Pct: pct, Target: target}}
	}
	p := func(v int) *int { return &v }
	mk := func(name string, cells []targets.Cell) *row {
		return &row{TeamMember: targets.TeamMember{Cells: cells}, member: Member{Name: name}}
	}
	d := &data{t: team{rows: []*row{mk("zoe", year(nil, 0)), mk("Bea", year(p(40), 10)), mk("ann", year(p(80), 10)),
		mk("Al", year(nil, 0)), mk("cid", year(p(40), 5))}}}
	d.rankRows()
	want := []struct {
		name string
		rank int
	}{{"ann", 1}, {"Bea", 2}, {"cid", 3}, {"Al", 0}, {"zoe", 0}}
	for i, w := range want {
		r := d.t.rows[i]
		got := 0
		if r.rank != nil {
			got = *r.rank
		}
		if r.member.Name != w.name || got != w.rank {
			t.Fatalf("place %d: %s #%d, want %s #%d", i, r.member.Name, got, w.name, w.rank)
		}
	}
}
