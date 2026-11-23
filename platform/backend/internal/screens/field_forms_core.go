package screens

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
)

const (
	corePurposeField       = "purpose_of_visit"
	purposeFollowUp        = "training_follow_up"
	purposeSSASupport      = "ssa_support"
	purposeInSchool        = "in_school_training"
	nextOpenSlot           = "Next open slot"
	noTrainingSlots        = "No training slots available"
	selectTraining         = "Select a training…"
	costedLine             = "Costed automatically at minimum viable rates."
	linkedInterventionNote = "Set on the training in the Training Catalogue. It cannot be changed here."
	openInterventionHelp   = "The Training Catalogue leaves this training open to any SSA intervention. Choose the one it targets."
)

// formRefused is a form the reader may not open, answered in its own words
// rather than as a failure.
type formRefused struct{ message string }

func (r *formRefused) Error() string { return r.message }

// coreFormError turns the reader's refusals into the form's answers.
func coreFormError(ctx context.Context, err error) error {
	var refusal *coreforms.Refusal
	if errors.As(err, &refusal) {
		return &formRefused{message: refusal.Message}
	}
	if errors.Is(err, coreforms.ErrNotFound) {
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This was not found, or it is not yours to view.")
	}
	return err
}

func coreSchoolCode(req fieldFormRequest) string {
	return strings.TrimSpace(req.query.Get("school_id"))
}

func coreMenuForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	menu, err := coreforms.NewService(s.db, s.clock).MenuFor(ctx, p, coreSchoolCode(req))
	if err != nil {
		return nil, coreFormError(ctx, err)
	}
	return coreMenuDrawer(menu), nil
}

func coreVisitForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	form, err := coreforms.NewService(s.db, s.clock).VisitFor(ctx, p, coreSchoolCode(req), ssaInterventionChoices)
	if err != nil {
		return nil, coreFormError(ctx, err)
	}
	return coreVisitDrawer(form), nil
}

func coreTrainingForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	form, err := coreforms.NewService(s.db, s.clock).TrainingFor(ctx, p, coreSchoolCode(req), ssaInterventionChoices)
	if err != nil {
		return nil, coreFormError(ctx, err)
	}
	return coreTrainingDrawer(form), nil
}

func coreAssignForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	form, err := coreforms.NewService(s.db, s.clock).AssignFor(ctx, p, coreSchoolCode(req), ssaInterventionChoices)
	if err != nil {
		return nil, coreFormError(ctx, err)
	}
	return coreAssignDrawer(form), nil
}

// whenField is "shown while field holds one of values".
func whenField(field string, values ...string) []*screensv1.DrawerCondition {
	return []*screensv1.DrawerCondition{{Field: field, Values: values}}
}

func textWhen(text, field string, values ...string) *screensv1.DrawerItem {
	item := textLine(text)
	item.ShowWhen = whenField(field, values...)
	return item
}

func noteWhen(text, tone, field string, values ...string) *screensv1.DrawerItem {
	item := reviewNote(text, tone)
	item.ShowWhen = whenField(field, values...)
	return item
}

// linksItem is a list of links in a drawer. One without an address is drawn
// as a choice that cannot be taken.
func linksItem(links ...*screensv1.PageLink) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{
		Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{
			Links: &screensv1.PageLinks{Links: links},
		}}}},
	}}}}
}

func schoolQuery(path, code string) string { return path + "?school_id=" + url.QueryEscape(code) }

// coreMenuDrawer is schedule_activity_drawer.html.
func coreMenuDrawer(m coreforms.Menu) *screensv1.PageDrawer {
	visit := &screensv1.PageLink{Text: "Schedule"}
	switch {
	case m.Package.Available && m.StaffCanVisit:
		visit.Href, visit.Drawer = schoolQuery("/core-schools/schedule-visit", m.School.Code), true
		visit.Caption = fmt.Sprintf("Core visit · staff %d/%d · %d remaining", m.StaffVisits, m.StaffVisitCap, m.VisitsLeft)
	case !m.StaffCanVisit:
		visit.Caption = fmt.Sprintf("Core visit · staff visits complete (%d/%d)", m.StaffVisits, m.StaffVisitCap)
	default:
		visit.Caption = "Core visit · no core package for this year"
	}
	training := &screensv1.PageLink{Text: "Schedule"}
	switch {
	case m.Package.Available && m.StaffTrainingsOpen && m.CanPlanTraining:
		training.Href, training.Drawer = schoolQuery("/core-schools/schedule-training", m.School.Code), true
		training.Caption = fmt.Sprintf("Core training · staff %d/%d · %d remaining", m.StaffTrainings, m.StaffTrainingCap, m.TrainingsLeft)
	case m.Package.Available && !m.StaffTrainingsOpen:
		training.Caption = fmt.Sprintf("Core training · staff trainings complete (%d/%d)", m.StaffTrainings, m.StaffTrainingCap)
	case m.Package.Available:
		training.Caption = "Core training · not available for your role"
	default:
		training.Caption = "Core training · no core package for this year"
	}
	items := []*screensv1.DrawerItem{headingLine("Core package")}
	if m.Package.Complete {
		items = append(items, textLine("Package complete"))
	}
	items = append(items,
		textLine("Four visits and four trainings: two of each by staff, two of each by a partner."),
		linksItem(visit, training),
		headingLine("Other school activities"),
		textLine("Donor, story, invitation and social visits have no limit and are not package visits. A follow-up or SSA Support visit counts as one of the staff's package visits."),
		linksItem(&screensv1.PageLink{Text: "Schedule other activity", Href: schoolQuery("/planning/schedule-modal", m.School.Code), Drawer: true}),
	)
	return readOnlyDrawer("Schedule activity for "+m.School.Name, items)
}

func slotOptions(slots []coreforms.Slot, empty string) []*screensv1.DrawerOption {
	if len(slots) == 0 {
		return []*screensv1.DrawerOption{{Label: empty}}
	}
	options := make([]*screensv1.DrawerOption, len(slots))
	for i, slot := range slots {
		options[i] = &screensv1.DrawerOption{Value: strconv.Itoa(slot.Sequence), Label: slot.Label}
	}
	return options
}

func firstSlot(slots []coreforms.Slot) string {
	if len(slots) == 0 {
		return ""
	}
	return strconv.Itoa(slots[0].Sequence)
}

func recommendationItems(needs []coreforms.Need) []*screensv1.DrawerItem {
	if len(needs) == 0 {
		return nil
	}
	items := []*screensv1.DrawerItem{textLine("Recommended focus areas from the latest SSA")}
	for _, need := range needs {
		items = append(items, textLine(need.Label+" ("+strconv.FormatFloat(need.Score, 'f', 1, 64)+"/10)"))
	}
	return items
}

func courseChoices(courses []coreforms.Course) []*screensv1.DrawerOption {
	options := []*screensv1.DrawerOption{{Label: selectTraining}}
	for _, course := range courses {
		options = append(options, &screensv1.DrawerOption{Value: course.ID, Label: course.Label})
	}
	return options
}

// linesByCourse is one line per distinct sentence, shown for the courses it
// describes.
func linesByCourse(field string, courses []coreforms.Course, line func(coreforms.Course) string) []*screensv1.DrawerItem {
	var order []string
	ids := map[string][]string{}
	for _, course := range courses {
		text := line(course)
		if text == "" {
			continue
		}
		if _, seen := ids[text]; !seen {
			order = append(order, text)
		}
		if !slices.Contains(ids[text], course.ID) {
			ids[text] = append(ids[text], course.ID)
		}
	}
	items := make([]*screensv1.DrawerItem, 0, len(order))
	for _, text := range order {
		items = append(items, textWhen(text, field, ids[text]...))
	}
	return items
}

func courseIDs(courses []coreforms.Course, keep func(coreforms.Course) bool) []string {
	var ids []string
	for _, course := range courses {
		if keep(course) && !slices.Contains(ids, course.ID) {
			ids = append(ids, course.ID)
		}
	}
	return ids
}

// followUpItems is the Training followed up field, shared by the visit and
// assignment drawers.
func followUpItems(rows []coreforms.FollowUp, required bool, fy string) []*screensv1.DrawerItem {
	label := "Training followed up"
	if !required {
		label += " (optional)"
	}
	options := []*screensv1.DrawerOption{{Label: "Select a training this school did…"}}
	var lineOrder []string
	byLine := map[string][]string{}
	for _, row := range rows {
		options = append(options, &screensv1.DrawerOption{Value: row.ID, Label: row.Label})
		line := "Focus intervention: " + row.InterventionLabel + ", from the training followed up."
		if _, seen := byLine[line]; !seen {
			lineOrder = append(lineOrder, line)
		}
		byLine[line] = append(byLine[line], row.ID)
	}
	items := []*screensv1.DrawerItem{formField(&screensv1.DrawerField{
		Name: "source_activity_id", Label: label, Kind: "select", Required: required, Options: options,
		Help:     "Trainings this school completed in Fiscal Year " + fy + ", at the school or at a cluster session it attended.",
		ShowWhen: whenField(corePurposeField, purposeFollowUp),
	})}
	if len(rows) == 0 {
		if required {
			items = append(items, noteWhen("No completed training is recorded for this School in Fiscal Year "+fy+".", "warning", corePurposeField, purposeFollowUp))
		} else {
			items = append(items, textWhen("No prior training recorded. The follow-up can still be planned; its focus comes from the school's SSA.", corePurposeField, purposeFollowUp))
		}
	}
	for _, line := range lineOrder {
		items = append(items, textWhen(line, "source_activity_id", byLine[line]...))
	}
	return items
}

func interventionOptions(blank string) []*screensv1.DrawerOption {
	return append([]*screensv1.DrawerOption{{Label: blank}}, choiceOptions(ssaInterventionChoices)...)
}

// coreVisitDrawer is schedule_visit_drawer.html. What the page shows and
// hides as the purpose changes is said on each field.
func coreVisitDrawer(f coreforms.VisitForm) *screensv1.PageDrawer {
	var items []*screensv1.DrawerItem
	if f.OwnerName != "" {
		items = append(items, reviewNote("This school is in "+f.OwnerName+"’s portfolio. "+f.OwnerName+
			" approves or declines the visit; you ("+f.RequesterName+") stay the responsible person, and once approved it enters your plan and budget.", "warning"))
	}
	purposes := []*screensv1.DrawerOption{{Label: "Select a purpose…"}}
	var focusFor []string
	slotFor := []string{""}
	var nonPackage, training []string
	for _, purpose := range f.Purposes {
		purposes = append(purposes, &screensv1.DrawerOption{Value: purpose.Value, Label: purpose.Label})
		isTraining := slices.Contains(coreforms.TrainingPurposes, purpose.Value)
		isOutreach := slices.Contains(f.NonPackagePurposes, purpose.Value)
		if isTraining {
			training = append(training, purpose.Value)
		}
		if isOutreach {
			nonPackage = append(nonPackage, purpose.Value)
		}
		if !isTraining && !isOutreach {
			slotFor = append(slotFor, purpose.Value)
		}
		followUpNamesIt := purpose.Value == purposeFollowUp && f.FollowUpRequired
		if !isTraining && purpose.Value != purposeSSASupport && !followUpNamesIt {
			focusFor = append(focusFor, purpose.Value)
		}
	}
	items = append(items,
		formField(&screensv1.DrawerField{Name: corePurposeField, Label: "Purpose of visit", Kind: "select", Required: true, Options: purposes}),
		textWhen("Focus intervention: Data Gathering. Completing the visit records the SSA scores, or why they were not collected.", corePurposeField, purposeSSASupport),
	)
	items = append(items, followUpItems(f.FollowUps, f.FollowUpRequired, f.FY)...)
	if len(training) > 0 {
		items = append(items, formField(&screensv1.DrawerField{Name: "training_course_id", Label: "Training", Kind: "select", Required: true,
			Help: "Creates the Core training and its school visit together.", Options: courseChoices(f.Courses), ShowWhen: whenField(corePurposeField, training...)}))
		items = append(items, linesByCourse("training_course_id", f.Courses, func(c coreforms.Course) string {
			return c.Category + " · SSA intervention association: " + c.InterventionLabel
		})...)
		items = append(items, formField(&screensv1.DrawerField{Name: "training_number", Label: "Training slot", Kind: "select",
			Value: firstSlot(f.Package.Trainings), Options: slotOptions(f.Package.Trainings, noTrainingSlots), ShowWhen: whenField(corePurposeField, training...)}))
	}
	focusHelp := ""
	if f.FocusLabel != "" {
		focusHelp = "Pre-selected from the SSA’s first-ranked need, " + f.FocusLabel + "."
	}
	items = append(items,
		formField(&screensv1.DrawerField{Name: "focus_intervention", Label: "Focus intervention (optional)", Kind: "select", Value: f.FocusCode,
			Help: focusHelp, Options: interventionOptions("No single intervention"), ShowWhen: whenField(corePurposeField, focusFor...)}),
		formField(&screensv1.DrawerField{Name: "visit_number", Label: "Visit slot", Kind: "select", Value: firstSlot(f.Package.Visits),
			Options: slotOptions(f.Package.Visits, nextOpenSlot), ShowWhen: whenField(corePurposeField, slotFor...)}),
	)
	if len(nonPackage) > 0 {
		items = append(items, textWhen("This visit is not one of the package's four visits and has no limit.", corePurposeField, nonPackage...))
	}
	items = append(items, formField(&screensv1.DrawerField{Name: "scheduled_date", Label: "Planned date", Kind: "date", Required: true}))
	items = append(items, recommendationItems(f.Recommendations)...)
	if f.OwnerName != "" {
		items = append(items, formField(&screensv1.DrawerField{Name: "visit_justification", Label: "Why you need to visit this school", Kind: "textarea",
			Required: true, Placeholder: "Why you, rather than " + f.OwnerName + "?"}))
	} else {
		staff := []*screensv1.DrawerOption{{Label: "Select a staff member…"}}
		for _, member := range f.Staff {
			staff = append(staff, &screensv1.DrawerOption{Value: member.Value, Label: member.Label})
		}
		items = append(items, formField(&screensv1.DrawerField{Name: "responsible_staff_id", Label: "Responsible staff", Kind: "select", Value: f.Responsible, Options: staff}))
	}
	items = append(items,
		textLine("Staff make this visit. To have a partner make it, use Assign on the school's row: the partner chooses the date."),
		formField(&screensv1.DrawerField{Name: "activity_goal", Label: "Activity goal", Kind: "textarea", Placeholder: "What this visit should achieve"}),
		formField(&screensv1.DrawerField{Name: "expected_outcome", Label: "Expected outcome", Kind: "textarea", Placeholder: "Expected results"}),
		textLine(costedLine),
	)
	return &screensv1.PageDrawer{Title: "Schedule visit for " + f.School.Name, HasRequired: true,
		SubmitLabel: "Schedule visit", CancelLabel: "Cancel", CanSubmit: true, Items: items}
}

// courseInterventionItems is the read-only SSA intervention a catalogued
// course carries, and the list for one the catalogue leaves open. A form that
// always asks for a training says so before one is chosen; one where the
// training depends on the purpose says nothing until then.
func courseInterventionItems(field string, courses []coreforms.Course, alwaysAsked bool) []*screensv1.DrawerItem {
	linked := courseIDs(courses, func(c coreforms.Course) bool { return !c.PlannerChooses })
	open := courseIDs(courses, func(c coreforms.Course) bool { return c.PlannerChooses })
	var items []*screensv1.DrawerItem
	if alwaysAsked {
		items = append(items, textWhen("SSA intervention: Filled in from the training", field, ""))
		linked = append([]string{""}, linked...)
	}
	items = append(items, linesByCourse(field, courses, func(c coreforms.Course) string {
		if c.PlannerChooses {
			return ""
		}
		return "SSA intervention: " + c.InterventionLabel
	})...)
	if len(linked) > 0 {
		items = append(items, textWhen(linkedInterventionNote, field, linked...))
	}
	if len(open) > 0 {
		items = append(items, formField(&screensv1.DrawerField{Name: "focus_intervention", Label: "SSA intervention", Kind: "select",
			Help: openInterventionHelp, Options: interventionOptions("No specific intervention"), ShowWhen: whenField(field, open...)}))
	}
	return items
}

// coreTrainingDrawer is schedule_training_drawer.html.
func coreTrainingDrawer(f coreforms.TrainingForm) *screensv1.PageDrawer {
	const courseField = "catalogue_item_id"
	items := []*screensv1.DrawerItem{formField(&screensv1.DrawerField{Name: courseField, Label: "Training", Kind: "select", Required: true,
		Help: "Any training in the Training Catalogue, whatever intervention it serves.", Options: courseChoices(f.Courses)})}
	if len(f.Courses) == 0 {
		items = append(items, reviewNote("No training is active in the Training Catalogue.", "warning"))
	}
	items = append(items, linesByCourse(courseField, f.Courses, func(c coreforms.Course) string {
		return c.Category + " · SSA intervention association: " + c.Indicator
	})...)
	items = append(items, courseInterventionItems(courseField, f.Courses, true)...)
	items = append(items,
		formField(&screensv1.DrawerField{Name: "training_number", Label: "Training slot", Kind: "select", Value: firstSlot(f.Package.Trainings),
			Options: slotOptions(f.Package.Trainings, noTrainingSlots)}),
		formField(&screensv1.DrawerField{Name: "scheduled_date", Label: "Planned date", Kind: "date", Required: true}),
	)
	items = append(items, recommendationItems(f.Recommendations)...)
	facilitators := []*screensv1.DrawerOption{{Label: "Staff"}}
	for _, partner := range f.Facilitators {
		facilitators = append(facilitators, &screensv1.DrawerOption{Value: partner.Value, Label: partner.Label})
	}
	items = append(items,
		formField(&screensv1.DrawerField{Name: "expected_participants", Label: "Expected participants", Kind: "number", Placeholder: "e.g. 15"}),
		formField(&screensv1.DrawerField{Name: "duration_hours", Label: "Duration (hours)", Kind: "number", Placeholder: "e.g. 4"}),
		textLine("Staff deliver this training. To have a partner deliver it, use Assign on the school's row: the partner chooses the date."),
		formField(&screensv1.DrawerField{Name: "facilitating_partner_id", Label: "Facilitated by", Kind: "select", Options: facilitators,
			Help: "A partner facilitating this training is not assigned the school. Assign the school to a partner separately for follow-ups and other support."}),
		formField(&screensv1.DrawerField{Name: "training_purpose", Label: "Purpose and description", Kind: "textarea", Placeholder: "Goal of this training"}),
		textLine(costedLine),
	)
	return &screensv1.PageDrawer{Title: "Schedule training for " + f.School.Name, HasRequired: true,
		SubmitLabel: "Schedule training", CancelLabel: "Cancel", CanSubmit: true, Items: items}
}

// assignPurposeOptions greys what the partner's half can no longer take.
func assignPurposeOptions(f coreforms.AssignForm) []*screensv1.DrawerOption {
	options := []*screensv1.DrawerOption{{Label: "Select a purpose…"}}
	for _, purpose := range f.Purposes {
		option := &screensv1.DrawerOption{Value: purpose.Value, Label: purpose.Label}
		switch {
		case purpose.Value == purposeInSchool:
			if !f.TrainingsOpen {
				option.Disabled, option.Label = true, purpose.Label+" (partner trainings complete)"
			}
		case purpose.Value == purposeSSASupport && f.SSAClosed != "":
			option.Disabled, option.Label = true, purpose.Label+" — not available"
		case !f.VisitsOpen:
			option.Disabled, option.Label = true, purpose.Label+" (partner visits complete)"
		}
		options = append(options, option)
	}
	return options
}

// partnerCourseOptions offers each partner the courses it is recorded as
// delivering, or every course for one not yet scoped.
func partnerCourseOptions(partners []coreforms.Partner, courses []coreforms.Course) []*screensv1.DrawerOption {
	options := []*screensv1.DrawerOption{{Label: selectTraining}}
	for _, partner := range partners {
		for _, course := range courses {
			if len(partner.Codes) == 0 || slices.Contains(partner.Codes, course.Code) {
				options = append(options, &screensv1.DrawerOption{Value: course.ID, Label: course.Label, Group: partner.ID})
			}
		}
	}
	return options
}

func assignSlotOptions(f coreforms.AssignForm) []*screensv1.DrawerOption {
	options := []*screensv1.DrawerOption{{Label: nextOpenSlot}}
	for _, purpose := range f.Purposes {
		slots := f.Package.Visits
		if purpose.Value == purposeInSchool {
			slots = f.Package.Trainings
		}
		for _, slot := range slots {
			options = append(options, &screensv1.DrawerOption{Value: strconv.Itoa(slot.Sequence), Label: slot.Label, Group: purpose.Value})
		}
	}
	return options
}

func handoverItems(f coreforms.AssignForm) []*screensv1.DrawerItem {
	if len(f.Handovers) == 0 {
		return nil
	}
	links := make([]*screensv1.PageLink, len(f.Handovers))
	for i, route := range f.Handovers {
		links[i] = handoverLink(route)
	}
	help := "Opens the project's own activities and partners for this school."
	if f.School.Type == "core" {
		help += " Project work counts toward the partner's half of the package; a project the SSA does not measure, such as Alumni, does not."
	}
	return []*screensv1.DrawerItem{headingLine("Or assign through a project"), linksItem(links...), textLine(help)}
}

func handoverLink(route projectcapacity.HandoverRoute) *screensv1.PageLink {
	return &screensv1.PageLink{Text: route.Project, Href: "/projects/planning/bulk-partner?assignments=" + url.QueryEscape(route.AssignmentID), Drawer: true}
}

// coreAssignDrawer is assign_partner_drawer.html. The partner is asked before
// the training, because the list of trainings depends on who delivers them.
func coreAssignDrawer(f coreforms.AssignForm) *screensv1.PageDrawer {
	const courseField = "training_course_id"
	help := "In-school Training fills a Core training slot; the other purposes fill a Core visit slot."
	if f.SSAClosed != "" {
		help = f.SSAClosed
	}
	allPurposes := make([]string, len(f.Purposes))
	for i, purpose := range f.Purposes {
		allPurposes[i] = purpose.Value
	}
	items := []*screensv1.DrawerItem{formField(&screensv1.DrawerField{Name: corePurposeField, Label: "Purpose of visit", Kind: "select", Required: true,
		Help: help, Options: assignPurposeOptions(f)})}
	if f.SSAClosed != "" {
		items = append(items, textLine("In-school Training fills a Core training slot; the other purposes fill a Core visit slot."))
	}
	items = append(items, textLine(fmt.Sprintf("Partner's half of this package: visits %d/%d · trainings %d/%d.", f.VisitsUsed, f.SideCap, f.TrainingsUsed, f.SideCap)))
	items = append(items, handoverItems(f)...)
	partners := []*screensv1.DrawerOption{{Label: "Select a partner…"}}
	for _, partner := range f.Partners {
		partners = append(partners, &screensv1.DrawerOption{Value: partner.ID, Label: partner.Name})
	}
	items = append(items,
		formField(&screensv1.DrawerField{Name: "partner_id", Label: "Partner", Kind: "select", Required: true, Options: partners}),
		textWhen("Focus intervention: Data Gathering. The partner uploads the visit form; the SSA scores are recorded at completion.", corePurposeField, purposeSSASupport),
	)
	items = append(items, followUpItems(f.FollowUps, f.FollowUpRequired, f.FY)...)
	items = append(items, formField(&screensv1.DrawerField{Name: courseField, Label: "Training", Kind: "select", Required: true, GroupBy: "partner_id",
		Help: "Choose the partner first. You choose the training; the partner only sets the delivery date.", Options: partnerCourseOptions(f.Partners, f.Courses),
		ShowWhen: whenField(corePurposeField, purposeInSchool)}))
	items = append(items, linesByCourse(courseField, f.Courses, func(c coreforms.Course) string {
		return c.Category + " · SSA intervention association: " + c.InterventionLabel
	})...)
	items = append(items, courseInterventionItems(courseField, f.Courses, false)...)
	items = append(items,
		formField(&screensv1.DrawerField{Name: "visit_training_number", Label: "Available slot", Kind: "select", GroupBy: corePurposeField,
			Options: assignSlotOptions(f), ShowWhen: whenField(corePurposeField, allPurposes...)}),
		formField(&screensv1.DrawerField{Name: "notes", Label: "Notes for the partner", Kind: "textarea", Placeholder: "Instructions, timing or focus"}),
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: []*screensv1.PageFact{{Label: "Assigned date", Value: f.Today}}}}},
		textLine("The day this assignment is made. The partner chooses the date of the work."),
		textLine("The slot leaves your queue and the partner is notified to schedule it."),
	)
	return &screensv1.PageDrawer{Title: "Assign Core support at " + f.School.Name, HasRequired: true,
		SubmitLabel: "Assign to partner", CancelLabel: "Cancel", CanSubmit: true, Items: items}
}
