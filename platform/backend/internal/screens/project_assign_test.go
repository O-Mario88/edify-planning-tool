package screens

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
)

func TestTheProjectAssignDrawerNamesEachSchoolsProjectAndOffersTheProjectsPartnersFirst(t *testing.T) {
	sel := activities.ProjectAssignSelection{
		Rows: []activities.ProjectAssignRow{
			{SchoolName: "Kito", ProjectName: "EdTech"},
			{SchoolName: "Nama", ProjectName: "EdTech", Reason: "This school is closed."},
		},
		ProjectPartners: []string{"p2"}, Listed: true,
	}
	partners := []coreforms.Partner{{ID: "p1", Name: "Build Africa"}, {ID: "p2", Name: "Room to Read"}}
	d := projectAssignDrawer(sel, partners, true)
	if d.GetTitle() != "Assign 1 project school to a partner" || d.GetSubmitLabel() != "Assign 1 school" || !d.GetCanSubmit() {
		t.Fatalf("head: %v", d)
	}
	texts := []string{}
	for _, item := range d.GetItems() {
		if text := item.GetText(); text != "" {
			texts = append(texts, text)
		}
	}
	want := []string{"Selected project schools", "Kito · EdTech", "Nama · EdTech · Not included: This school is closed.", bulkAssignDay, projectAssignEvery}
	if len(texts) != len(want) {
		t.Fatalf("texts %q", texts)
	}
	for i := range want {
		if texts[i] != want[i] {
			t.Fatalf("text %d: %q, want %q", i, texts[i], want[i])
		}
	}
	options := d.GetItems()[3].GetField().GetOptions()
	if len(options) != 3 || options[1].GetLabel() != "Room to Read" || options[2].GetLabel() != "Build Africa" {
		t.Fatalf("partners %v", options)
	}
	purposes := d.GetItems()[5].GetField().GetOptions()
	for _, o := range purposes {
		if o.GetValue() == "training_follow_up" {
			t.Fatal("a follow-up that names its training is assigned from each school's own Assign")
		}
	}
	sel.ProjectPartners = nil
	options = projectAssignDrawer(sel, partners, false).GetItems()[3].GetField().GetOptions()
	if len(options) != 4 || !options[1].GetDisabled() || options[1].GetLabel() != projectAssignNoListed {
		t.Fatalf("no shared partner: %v", options)
	}
}

func TestTheProjectAssignAsksForTheProjectsPageBeforeTheHandOver(t *testing.T) {
	for role, want := range map[string]string{
		"HumanResources":     projectAssignPageDenied,
		"CountryDirector":    projectAssignDenied,
		"ProjectCoordinator": "",
		"CCEO":               "",
	} {
		if got := projectAssignRefusal(auth.Principal{Account: auth.Account{ActiveRole: role}}); got != want {
			t.Fatalf("%s: %q, want %q", role, got, want)
		}
	}
}
