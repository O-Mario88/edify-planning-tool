package debriefs

import (
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func titled(text string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Rows: []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: text}}}}}}}
}

// Owner, 2026-11-16: "Fix the tabs". The existing feed drew every tab with
// the open tab's rows; each tab now holds its own, and only the asked tab is
// open.
func TestEachDebriefTabHoldsItsOwnRows(t *testing.T) {
	labels := [][2]string{{"awaiting_review", "Awaiting my review (1)"}, {"all", "All Debriefs"}, {"mine", "My Debriefs"}}
	tables := map[string]*screensv1.PageBlock{
		"awaiting_review": titled("awaiting"), "all": titled("everything"), "mine": titled("my own"),
	}
	segs := tabSegments(labels, "mine", tables).GetSegments().Segments
	if len(segs) != 3 {
		t.Fatalf("%d tabs, want 3", len(segs))
	}
	for i, want := range []struct {
		label, row string
		open       bool
	}{{"Awaiting my review (1)", "awaiting", false}, {"All Debriefs", "everything", false}, {"My Debriefs", "my own", true}} {
		got := segs[i]
		row := got.Blocks[0].GetTable().Rows[0].Cells[0].Text
		if got.Label != want.label || row != want.row || got.Active != want.open {
			t.Errorf("tab %d = %q holding %q open=%v, want %q holding %q open=%v",
				i, got.Label, row, got.Active, want.label, want.row, want.open)
		}
	}
}

func TestAnUnknownTabLeavesEveryTabClosed(t *testing.T) {
	labels := [][2]string{{"all", "All Debriefs"}, {"mine", "My Debriefs"}}
	tables := map[string]*screensv1.PageBlock{"all": titled("a"), "mine": titled("m")}
	for _, s := range tabSegments(labels, "bogus", tables).GetSegments().Segments {
		if s.Active {
			t.Errorf("tab %q is open for an unknown tab", s.Label)
		}
	}
}
