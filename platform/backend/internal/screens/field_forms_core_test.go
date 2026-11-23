package screens

import (
	"slices"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

func coreField(t *testing.T, drawer *screensv1.PageDrawer, name string) *screensv1.DrawerField {
	t.Helper()
	for _, item := range drawer.GetItems() {
		if item.GetField().GetName() == name {
			return item.GetField()
		}
	}
	t.Fatalf("no %s field", name)
	return nil
}

func coreLinks(drawer *screensv1.PageDrawer) []*screensv1.PageLink {
	var links []*screensv1.PageLink
	for _, item := range drawer.GetItems() {
		for _, part := range item.GetBlock().GetPanel().GetItems() {
			links = append(links, part.GetLinks().GetLinks()...)
		}
	}
	return links
}

func coreText(drawer *screensv1.PageDrawer, words string) *screensv1.DrawerItem {
	for _, item := range drawer.GetItems() {
		if item.GetText() == words {
			return item
		}
	}
	return nil
}

func optionValues(field *screensv1.DrawerField) []string {
	values := make([]string, len(field.GetOptions()))
	for i, option := range field.GetOptions() {
		values[i] = option.GetValue()
	}
	return values
}

func openPackage() coreforms.Package {
	return coreforms.Package{Available: true,
		Visits:    []coreforms.Slot{{Sequence: 2, Label: "Second Visit"}},
		Trainings: []coreforms.Slot{{Sequence: 3, Label: "Third Training"}}}
}

func TestEveryCoreFormBelongsToCoreSchools(t *testing.T) {
	for _, path := range []string{"/core-schools/schedule-activity", "/core-schools/schedule-visit", "/core-schools/schedule-training", "/core-schools/assign-partner"} {
		form, ok := fieldFormFor(path)
		if !ok {
			t.Fatalf("%s is not served", path)
		}
		if why := form.refusal(fieldPrincipal(rbac.CCEO)); why != "" {
			t.Errorf("%s: CCEO refused: %s", path, why)
		}
		if why := form.refusal(fieldPrincipal(rolePC)); why != "Access Denied: Your active role does not have permission to view Core Schools." {
			t.Errorf("%s: %q", path, why)
		}
	}
}

func TestTheMenuLeadsToEachFormOrSaysWhyNot(t *testing.T) {
	menu := coreforms.Menu{School: coreforms.School{Code: "1006", Name: "Goma"}, Package: openPackage(), StaffCanVisit: true,
		StaffVisits: 1, StaffVisitCap: 2, VisitsLeft: 1, StaffTrainingsOpen: true, CanPlanTraining: true,
		StaffTrainings: 2, StaffTrainingCap: 2}
	drawer := coreMenuDrawer(menu)
	if drawer.GetTitle() != "Schedule activity for Goma" || drawer.GetCanSubmit() {
		t.Fatalf("head: %v", drawer)
	}
	links := coreLinks(drawer)
	if len(links) != 3 {
		t.Fatalf("links: %v", links)
	}
	if links[0].GetHref() != "/core-schools/schedule-visit?school_id=1006" || !links[0].GetDrawer() || links[0].GetCaption() != "Core visit · staff 1/2 · 1 remaining" {
		t.Fatalf("visit: %v", links[0])
	}
	if links[2].GetText() != "Schedule other activity" || links[2].GetHref() != "/planning/schedule-modal?school_id=1006" {
		t.Fatalf("other: %v", links[2])
	}
	menu.StaffCanVisit, menu.StaffVisits, menu.StaffTrainingsOpen = false, 2, false
	locked := coreLinks(coreMenuDrawer(menu))
	if locked[0].GetHref() != "" || locked[0].GetCaption() != "Core visit · staff visits complete (2/2)" {
		t.Fatalf("locked visit: %v", locked[0])
	}
	if locked[1].GetHref() != "" || locked[1].GetCaption() != "Core training · staff trainings complete (2/2)" {
		t.Fatalf("locked training: %v", locked[1])
	}
	none := coreLinks(coreMenuDrawer(coreforms.Menu{School: coreforms.School{Code: "1000"}, StaffCanVisit: true}))
	if none[0].GetCaption() != "Core visit · no core package for this year" || none[1].GetCaption() != "Core training · no core package for this year" {
		t.Fatalf("no package: %v", none)
	}
}

func TestTheVisitFormAsksOnlyWhatThePurposeNeeds(t *testing.T) {
	form := coreforms.VisitForm{
		School: coreforms.School{Code: "1006", Name: "Goma"}, Package: openPackage(), FY: "2027", FollowUpRequired: true,
		Purposes:           []coreforms.Choice{{Value: "in_school_training", Label: "In-school Training"}, {Value: "training_follow_up", Label: "Training Follow Up"}, {Value: "ssa_support", Label: "SSA Support"}, {Value: "donor_visit", Label: "Donor Visit"}},
		NonPackagePurposes: []string{"donor_visit", "ssa_support"},
		Courses:            []coreforms.Course{{ID: "c1", Label: "Budgeting", Category: "Finance", InterventionLabel: "Financial Health"}},
		FollowUps:          []coreforms.FollowUp{{ID: "a1", Label: "Budgeting · 09 Oct 2026 · At the school", InterventionLabel: "Financial Health"}},
		Staff:              []coreforms.Choice{{Value: "u1", Label: "Ada"}}, Responsible: "u1", FocusCode: "leadership", FocusLabel: "Leadership",
		Recommendations: []coreforms.Need{{Label: "Financial Health", Score: 6.1}},
	}
	drawer := coreVisitDrawer(form)
	course := coreField(t, drawer, "training_course_id")
	if !course.GetRequired() || course.GetShowWhen()[0].GetField() != "purpose_of_visit" || !slices.Contains(course.GetShowWhen()[0].GetValues(), "in_school_training") {
		t.Fatalf("course: %v", course)
	}
	source := coreField(t, drawer, "source_activity_id")
	if !source.GetRequired() || source.GetShowWhen()[0].GetValues()[0] != "training_follow_up" {
		t.Fatalf("follow-up: %v", source)
	}
	focus := coreField(t, drawer, "focus_intervention")
	if focus.GetValue() != "leadership" || focus.GetHelp() != "Pre-selected from the SSA’s first-ranked need, Leadership." {
		t.Fatalf("focus: %v", focus)
	}
	if values := focus.GetShowWhen()[0].GetValues(); !slices.Equal(values, []string{"donor_visit"}) {
		t.Fatalf("focus shows for %v while a follow-up must name its training", values)
	}
	slot := coreField(t, drawer, "visit_number")
	if slot.GetValue() != "2" || !slices.Equal(slot.GetShowWhen()[0].GetValues(), []string{"", "training_follow_up"}) {
		t.Fatalf("visit slot: %v", slot)
	}
	if got := coreField(t, drawer, "responsible_staff_id"); got.GetValue() != "u1" {
		t.Fatalf("responsible: %v", got)
	}
	if coreText(drawer, "Financial Health (6.1/10)") == nil {
		t.Fatal("no recommendation")
	}
	if line := coreText(drawer, "Finance · SSA intervention association: Financial Health"); line == nil || line.GetShowWhen()[0].GetField() != "training_course_id" {
		t.Fatalf("course line: %v", line)
	}
	form.FollowUpRequired = false
	if values := coreField(t, coreVisitDrawer(form), "focus_intervention").GetShowWhen()[0].GetValues(); !slices.Contains(values, "training_follow_up") {
		t.Fatalf("an optional follow-up keeps its focus: %v", values)
	}
}

func TestAVisitNeedingApprovalAsksWhyAndNamesTheOwner(t *testing.T) {
	drawer := coreVisitDrawer(coreforms.VisitForm{School: coreforms.School{Name: "Goma"}, OwnerName: "Paul N.", RequesterName: "Moses"})
	note := drawer.GetItems()[0].GetNote()
	if note.GetTone() != "warning" || note.GetText() != "This school is in Paul N.’s portfolio. Paul N. approves or declines the visit; you (Moses) stay the responsible person, and once approved it enters your plan and budget." {
		t.Fatalf("note: %v", note)
	}
	why := coreField(t, drawer, "visit_justification")
	if !why.GetRequired() || why.GetPlaceholder() != "Why you, rather than Paul N.?" {
		t.Fatalf("why: %v", why)
	}
	for _, item := range drawer.GetItems() {
		if item.GetField().GetName() == "responsible_staff_id" {
			t.Fatal("the requester stays the responsible person")
		}
	}
}

func TestATrainingCarriesItsCataloguedIntervention(t *testing.T) {
	drawer := coreTrainingDrawer(coreforms.TrainingForm{School: coreforms.School{Name: "Goma"}, Package: openPackage(),
		Courses: []coreforms.Course{
			{ID: "c1", Label: "Budgeting", Category: "Finance", Indicator: "Financial Health", InterventionLabel: "Financial Health"},
			{ID: "c2", Label: "Open", Category: "General", Indicator: "Any", InterventionLabel: "Not SSA-scored", PlannerChooses: true},
		},
		Facilitators: []coreforms.Choice{{Value: "p1", Label: "Build Africa"}}})
	course := coreField(t, drawer, "catalogue_item_id")
	if !course.GetRequired() || len(course.GetOptions()) != 3 {
		t.Fatalf("course: %v", course)
	}
	focus := coreField(t, drawer, "focus_intervention")
	if !slices.Equal(focus.GetShowWhen()[0].GetValues(), []string{"c2"}) {
		t.Fatalf("only a course open to any intervention offers the list: %v", focus)
	}
	line := coreText(drawer, "SSA intervention: Financial Health")
	if line == nil || !slices.Equal(line.GetShowWhen()[0].GetValues(), []string{"c1"}) {
		t.Fatalf("linked line: %v", line)
	}
	facilitator := coreField(t, drawer, "facilitating_partner_id")
	if facilitator.GetOptions()[0].GetLabel() != "Staff" || facilitator.GetOptions()[1].GetLabel() != "Build Africa" {
		t.Fatalf("facilitator: %v", facilitator)
	}
}

func TestAssignGreysWhatThePartnersHalfHasUsed(t *testing.T) {
	form := coreforms.AssignForm{School: coreforms.School{Name: "Goma", Type: "core"}, Package: openPackage(), FY: "2027", SideCap: 2,
		Purposes:   []coreforms.Choice{{Value: "in_school_training", Label: "In-school Training"}, {Value: "training_follow_up", Label: "Training Follow Up"}, {Value: "ssa_support", Label: "SSA Support"}},
		VisitsUsed: 2, TrainingsUsed: 1, TrainingsOpen: true, SSAClosed: "Goma has completed its SSA for FY2027.", Today: "23 Nov 2026",
		Partners:  []coreforms.Partner{{ID: "p1", Name: "Build Africa", Codes: []string{"B"}}, {ID: "p2", Name: "Open Partner"}},
		Courses:   []coreforms.Course{{ID: "c1", Code: "A", Label: "Alpha"}, {ID: "c2", Code: "B", Label: "Beta"}},
		Handovers: []projectcapacity.HandoverRoute{{AssignmentID: "e1", Project: "EdTech"}},
	}
	drawer := coreAssignDrawer(form)
	options := coreField(t, drawer, "purpose_of_visit").GetOptions()
	if options[1].GetDisabled() || !options[2].GetDisabled() || options[2].GetLabel() != "Training Follow Up (partner visits complete)" {
		t.Fatalf("purposes: %v", options)
	}
	if !options[3].GetDisabled() || options[3].GetLabel() != "SSA Support — not available" {
		t.Fatalf("SSA: %v", options[3])
	}
	course := coreField(t, drawer, "training_course_id")
	if course.GetGroupBy() != "partner_id" {
		t.Fatalf("course: %v", course)
	}
	var forFirst, forSecond []string
	for _, option := range course.GetOptions() {
		switch option.GetGroup() {
		case "p1":
			forFirst = append(forFirst, option.GetValue())
		case "p2":
			forSecond = append(forSecond, option.GetValue())
		}
	}
	if !slices.Equal(forFirst, []string{"c2"}) || !slices.Equal(forSecond, []string{"c1", "c2"}) {
		t.Fatalf("a partner is offered what it delivers: %v / %v", forFirst, forSecond)
	}
	links := coreLinks(drawer)
	if len(links) != 1 || links[0].GetText() != "EdTech" || links[0].GetHref() != "/projects/planning/bulk-partner?assignments=e1" || !links[0].GetDrawer() {
		t.Fatalf("hand-over: %v", links)
	}
	slot := coreField(t, drawer, "visit_training_number")
	if slot.GetGroupBy() != "purpose_of_visit" {
		t.Fatalf("slot: %v", slot)
	}
	if coreText(drawer, "Partner's half of this package: visits 2/2 · trainings 1/2.") == nil {
		t.Fatal("no partner half line")
	}
	if line := coreText(drawer, "SSA intervention: Filled in from the training"); line != nil {
		t.Fatalf("a purpose with no training says nothing about one: %v", line)
	}
	note := coreText(drawer, "Set on the training in the Training Catalogue. It cannot be changed here.")
	if note == nil || slices.Contains(note.GetShowWhen()[0].GetValues(), "") {
		t.Fatalf("the note waits for a chosen training: %v", note)
	}
	if help := course.GetHelp(); help != "Choose the partner first. You choose the training; the partner only sets the delivery date." {
		t.Fatalf("course help: %q", help)
	}
}
