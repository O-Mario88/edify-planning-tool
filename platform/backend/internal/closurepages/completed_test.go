package closurepages

import (
	"net/url"
	"testing"
)

func TestALedgerRowWithNothingRecordedReadsAsTheTemplateWritesIt(t *testing.T) {
	blocks := completedTable([]closedActivity{{id: "abcdefghijkl", kind: "school_visit"}}, role{OpenSchool: true}, url.Values{})
	cells := blocks[0].GetTable().GetRows()[0].GetCells()
	want := []string{"#abcdefgh", "—", "Cluster-wide", "None", "School Visit", "", "Not Verified", "—"}
	for i, w := range want {
		if cells[i].GetText() != w {
			t.Errorf("cell %d: %q, want %q", i, cells[i].GetText(), w)
		}
	}
	if href := cells[8].GetActions()[0].GetHref(); href != "/completed-activities/abcdefghijkl/" {
		t.Errorf("View Record goes to %q", href)
	}
}

func TestAnEmptyLedgerReadsAsTheEmptyRowAndMessage(t *testing.T) {
	table := completedTable(nil, role{}, url.Values{})[0].GetTable()
	if table.GetEmptyMessage() != completedEmpty || table.GetRows()[0].GetCells()[0].GetText() != completedEmpty {
		t.Fatalf("empty ledger %v", table)
	}
}
