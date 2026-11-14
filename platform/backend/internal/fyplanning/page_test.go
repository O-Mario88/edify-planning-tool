package fyplanning

import (
	"testing"
	"time"
)

func TestAFiscalYearReadsOperationalClosedOpenOrNotOpen(t *testing.T) {
	now := time.Date(2026, 11, 14, 9, 0, 0, 0, time.UTC)
	past, future := now.Add(-time.Hour), now.Add(time.Hour)
	for _, c := range []struct {
		fy   string
		open *time.Time
		want string
	}{
		{"2027", nil, "Operational"}, {"2026", nil, "Closed year"}, {"2028", &past, "Open for planning"},
		{"2028", &now, "Open for planning"}, {"2028", &future, "Not open"}, {"2028", nil, "Not open"}, {"FY28", &past, "Not open"},
	} {
		if got := windowState(policy{FY: c.fy, OpenAt: c.open}, "2027", now); got != c.want {
			t.Errorf("FY%s (open %v) = %q, want %q", c.fy, c.open, got, c.want)
		}
	}
}

func TestTheFollowUpCellCarriesTheFlipButtonForAManagerAlone(t *testing.T) {
	pl := policy{FY: "2027", Start: time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC), End: time.Date(2027, 9, 30, 0, 0, 0, 0, time.UTC), FollowUpNeedsTraining: true}
	now := time.Date(2026, 11, 14, 9, 0, 0, 0, time.UTC)
	cells := page([]policy{pl}, "2027", "2028", true, false, now).GetBlocks()[1].GetTable().GetRows()[0].GetCells()
	if cells[4].GetText() != "Yes Allow without training" || cells[3].GetText() != "1 Oct 2026 – 30 Sep 2027" || cells[2].GetText() != "—" {
		t.Fatalf("manager's row: %v", cells)
	}
	reader := page([]policy{pl}, "2027", "2028", false, false, now)
	if got := reader.GetBlocks()[1].GetTable().GetRows()[0].GetCells()[4].GetText(); got != "Yes" || len(reader.GetBlocks()) != 2 {
		t.Fatalf("reader's row %q, blocks %d", got, len(reader.GetBlocks()))
	}
}

func TestTheOpenFormIsGoneOnceTheNextYearIsOpenAndNoPolicyIsOneCell(t *testing.T) {
	now := time.Now()
	if n := len(page(nil, "2027", "2028", true, true, now).GetBlocks()); n != 2 {
		t.Fatalf("next year open: %d blocks", n)
	}
	blocks := page(nil, "2027", "2028", true, false, now).GetBlocks()
	if blocks[2].GetForm().GetSubmitLabel() != "Open FY2028" || len(blocks[1].GetTable().GetRows()[0].GetCells()) != 1 {
		t.Fatalf("blocks: %v", blocks)
	}
}
