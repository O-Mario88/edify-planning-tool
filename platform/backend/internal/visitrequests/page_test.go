package visitrequests

import (
	"net/url"
	"testing"
	"time"
)

func TestARequestWithoutASchoolReadsAsTheTemplateWritesIt(t *testing.T) {
	planned := time.Date(2026, 12, 3, 0, 0, 0, 0, time.UTC)
	pending := pendingBlocks([]request{{kind: "school_visit", person: unknownAsker, planned: &planned}})
	if p := pending[0].GetPanel(); p.GetTitle() != "A staff member asks to visit your school" || p.GetSubtitle() != "School Visit • 3 Dec 2026" {
		t.Errorf("pending card %q / %q", p.GetTitle(), p.GetSubtitle())
	}
	mine := mineBlocks([]request{{kind: "school_visit", status: "rejected", note: "Not now.", person: unknownOwner}},
		role{OpenSchool: true}, url.Values{})
	cells := mine[0].GetTable().GetRows()[0].GetCells()
	want := []string{"—", "—School Visit", "—", "the school's owner", "DeclinedNot now."}
	for i, w := range want {
		if cells[i].GetText() != w {
			t.Errorf("cell %d: %q, want %q", i, cells[i].GetText(), w)
		}
	}
	if cells[1].GetHref() != "" {
		t.Errorf("no school links nowhere, got %q", cells[1].GetHref())
	}
}
