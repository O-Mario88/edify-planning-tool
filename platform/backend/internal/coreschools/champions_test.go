package coreschools

import (
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreoversight"
)

func TestACandidateRowWritesItsFiguresAsTheTemplateDoes(t *testing.T) {
	shown := []coreoversight.Candidate{
		{Code: "1126", Score: 91.4, LatestAvg: 8.6, Delta: 0.6, LowestScore: 7, LowestIntervention: "teaching_environment", Completed: 8, Total: 8},
		{Code: "", Score: 88, LatestAvg: 8, Delta: 0, LowestScore: 7, LowestIntervention: "None", Completed: 8, Total: 9},
	}
	schools := map[string]candidateSchool{"1126": {id: "s1", name: "Hill Primary", district: "Mukono"}, "": {name: "No Code", district: "Unknown"}}
	blocks := candidateBlocks(shown, schools, url.Values{}, true)
	if got := blocks[0].GetPanel().GetTitle(); got != "Candidacy Proposals (2)" {
		t.Fatalf("count %q", got)
	}
	rows := blocks[1].GetTable().GetRows()
	first, second := rows[0].GetCells(), rows[1].GetCells()
	checks := map[string]string{
		first[1].GetHref(): "/schools/1126", first[3].GetText(): "8.6", first[4].GetText(): "▲ 0.6",
		first[5].GetText(): "8 / 8 Slots", first[6].GetText(): "7.0 (teaching_environment)", first[7].GetText(): "91.4",
		second[0].GetText(): "—", second[4].GetText(): "0.0", second[7].GetText(): "88.0",
	}
	for got, want := range checks {
		if got != want {
			t.Errorf("got %q, want %q", got, want)
		}
	}
	if second[1].GetHref() != "" {
		t.Errorf("a school without a School ID links nowhere, got %q", second[1].GetHref())
	}
}

func TestNoCandidateLeavesTheTemplatesEmptySentence(t *testing.T) {
	blocks := candidateBlocks(nil, nil, url.Values{}, true)
	if rows := blocks[1].GetTable().GetRows(); len(rows) != 1 || rows[0].GetCells()[0].GetText() != candidatesEmpty {
		t.Fatalf("the empty row %v", rows)
	}
	if got := blocks[0].GetPanel().GetTitle(); got != "Candidacy Proposals (0)" {
		t.Fatalf("count %q", got)
	}
}
