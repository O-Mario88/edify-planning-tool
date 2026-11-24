package screens

import (
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
)

func TestBulkProjectDrawerOffersTheProjects(t *testing.T) {
	d := bulkProjectDrawer([]projectcapacity.BulkSchool{{ID: "s1", Code: "1442", Name: "Alpha"}, {ID: "s2", Code: "1338", Name: "Beta"}}, 1,
		[]*screensv1.BulkProjectChoice{{Value: "p1", Label: "Numeracy · Grace"}, {Value: "p2", Label: "Reading · no allocation", Block: "You have no school allocation for Reading."}})
	if d.GetTitle() != "Add 2 schools to a project" || d.GetSubmitLabel() != "Add to project" || !d.GetCanSubmit() || d.GetCancelLabel() != "Cancel" {
		t.Fatalf("head = %+v", d)
	}
	items := d.GetItems()
	if items[0].GetHeading() != "Selected schools" || items[1].GetText() != "Alpha 1442" || items[2].GetText() != "Beta 1338" {
		t.Errorf("schools = %+v", items[:3])
	}
	if n := items[3].GetNote(); n.GetText() != "1 selected school is outside your reach and left out." || n.GetTone() != "warning" {
		t.Errorf("outside = %+v", n)
	}
	f := items[4].GetField()
	if f.GetName() != "project_id" || !f.GetRequired() || len(f.GetOptions()) != 3 || !f.GetOptions()[2].GetDisabled() || f.GetOptions()[1].GetDisabled() {
		t.Errorf("project = %+v", f)
	}
	if items[5].GetText() != "Adds the 2 selected schools. Schools already in the project are skipped." {
		t.Errorf("closing = %q", items[5].GetText())
	}
}

func TestBulkProjectDrawerWithNothingToAddCloses(t *testing.T) {
	d := bulkProjectDrawer(nil, 2, nil)
	if d.GetCanSubmit() || d.GetCancelLabel() != "Close" || d.GetTitle() != "Add 0 schools to a project" {
		t.Fatalf("head = %+v", d)
	}
	last := d.GetItems()[len(d.GetItems())-1].GetNote()
	if last.GetText() != "None of the selected schools can be added to a project from here." {
		t.Errorf("note = %+v", last)
	}
	d = bulkProjectDrawer([]projectcapacity.BulkSchool{{ID: "s1", Name: "Alpha"}}, 0, nil)
	if last := d.GetItems()[len(d.GetItems())-1].GetNote(); last.GetText() != "No active projects available. Create a project before assigning schools." || d.GetCanSubmit() {
		t.Errorf("no projects = %+v", d)
	}
}
