package screens

import "testing"

// A selection whose ids match nothing the reader can see is the feed's drawer:
// no subtitle, the one note, and Close.
func TestEmptySelectionIsTheFeedsDrawer(t *testing.T) {
	for _, c := range []struct {
		cancel bool
		want   string
	}{{true, "None of the selected activities can be cancelled."}, {false, "None of the selected activities can be rescheduled."}} {
		d := cancelSelectionDrawer(nil, nil, 0)
		if !c.cancel {
			d = moveSelectionDrawer(nil, nil)
		}
		if d.GetSubtitle() != "" || d.GetCancelLabel() != "Close" || d.GetCanSubmit() || len(d.GetItems()) != 1 {
			t.Fatalf("cancel=%v head = %+v", c.cancel, d)
		}
		if n := d.GetItems()[0].GetNote(); n.GetText() != c.want || n.GetTone() != "warning" {
			t.Errorf("cancel=%v note = %+v", c.cancel, n)
		}
	}
}
