package schoolprofile

import "testing"

func TestMemberWorkCells(t *testing.T) {
	tests := []struct {
		name                    string
		work                    *placeWork
		visits, trainings, open string
	}{
		{"a school with no work this year", nil, "0 / 0", "0 / 0", "0"},
		{"done of planned, and what is still open", &placeWork{visits: 3, visitsDone: 1, trainings: 2, trainingsDone: 2}, "1 / 3", "2 / 2", "2"},
		{"more done than planned never reads as negative", &placeWork{visits: 1, visitsDone: 2}, "2 / 1", "0 / 0", "0"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			cells := memberWorkCells(tc.work)
			if len(cells) != 3 {
				t.Fatalf("got %d cells", len(cells))
			}
			if cells[0].GetText() != tc.visits || cells[1].GetText() != tc.trainings || cells[2].GetText() != tc.open {
				t.Fatalf("got %q %q %q", cells[0].GetText(), cells[1].GetText(), cells[2].GetText())
			}
		})
	}
}
