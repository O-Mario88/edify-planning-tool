package staffsetup

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestARowReadsAsTheQueueWritesIt(t *testing.T) {
	admin := auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}
	cells := row(admin, school{ID: "s1", Name: "Kasana", District: "Mukono", DistrictID: "d1", Region: "Central"}, "Select CCEO profile...").GetCells()
	if cells[0].GetText() != "Kasana Uploaded Owner: None Specified" || cells[1].GetText() != "Mukono district / Central region" ||
		!cells[2].GetBadge() || cells[4].GetText() != "Match Ignore" {
		t.Fatalf("cells %v", cells)
	}
	if got := picker([]staff{{"A", "a@x.org"}, {"B", "b@x.org"}}); got != "Select CCEO profile... A (a@x.org) B (b@x.org)" {
		t.Fatalf("picker %q", got)
	}
}

func TestAnEmptyQueueIsOneCellUnderItsColumns(t *testing.T) {
	got := page(auth.Principal{}, nil, nil, nil).GetBlocks()[0].GetTable()
	if len(got.GetColumns()) != 5 || len(got.GetRows()) != 1 || got.GetRows()[0].GetCells()[0].GetText() != emptyLine {
		t.Fatalf("empty %v", got)
	}
}
