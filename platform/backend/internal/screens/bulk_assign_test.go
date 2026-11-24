package screens

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
)

func TestTheBulkAssignDrawerNamesEverySchoolAndWhatItIsClosedTo(t *testing.T) {
	rows := []activities.BulkAssignRow{
		{School: activities.TickedSchool{Name: "Kito", Code: "1442"}, OK: true, ClosedTo: []string{"No SSA Support: done"}},
		{School: activities.TickedSchool{Name: "Goma", Code: "1599"}, Reason: "a Champion school"},
	}
	d := bulkAssignDrawer(rows, 1, []coreforms.Partner{{ID: "p1", Name: "Build Africa"}}, false)
	if d.GetTitle() != "Assign to partner" || d.GetSubtitle() != "1 school" || d.GetSubmitLabel() != "Assign 1 school" || !d.GetCanSubmit() {
		t.Fatalf("head: %v", d)
	}
	texts := []string{}
	for _, item := range d.GetItems() {
		if text := item.GetText(); text != "" {
			texts = append(texts, text)
		}
	}
	want := []string{"Kito 1442", "No SSA Support: done", "Goma 1599", "Not included: a Champion school",
		"1 selected school is outside your planning portfolio and left out.", bulkAssignEvery, bulkAssignDay}
	if len(texts) != len(want) {
		t.Fatalf("texts %q", texts)
	}
	for i := range want {
		if texts[i] != want[i] {
			t.Fatalf("text %d: %q, want %q", i, texts[i], want[i])
		}
	}
	partner := d.GetItems()[5].GetField()
	if partner.GetName() != "partner_id" || len(partner.GetOptions()) != 2 || partner.GetOptions()[1].GetLabel() != "Build Africa" {
		t.Fatalf("partner %v", partner)
	}
	none := bulkAssignDrawer(rows[1:], 0, nil, false)
	if none.GetCanSubmit() || none.GetSubmitLabel() != "" || none.GetSubtitle() != "0 schools" {
		t.Fatalf("none: %v", none)
	}
}
