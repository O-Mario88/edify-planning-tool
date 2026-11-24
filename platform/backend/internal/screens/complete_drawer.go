package screens

import (
	"context"
	"errors"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

// My Plan's Complete drawer (/my-plan/<id>/complete-drawer) drawn in Go with
// the existing application absent, for the work Go completes
// (activities.CompleteDrawer); every other one is handed on.

// CompleteDrawers reads what the drawer shows (internal/activities.Service).
type CompleteDrawers interface {
	CompleteDrawer(ctx context.Context, p auth.Principal, id string) (activities.CompleteFacts, error)
}

// WithCompleteDrawer makes the Complete drawer Go's with Django absent.
func (s *Service) WithCompleteDrawer(d CompleteDrawers) *Service {
	s.completeDrawers = d
	return s
}

// The drawer's fixed words (complete_drawer.html).
const (
	completedOnHelp  = "Today or an earlier day. If it was done on another day than planned, the visit and its cost move to that day, and the planned day is freed."
	registerAddHelp  = "Not in Edify? Add it in Salesforce first, then add a new school."
	observedNote     = "A short note for the activity file, if there is something to say."
	schoolCreatePerm = "school.createSingle"
	outcomeMax       = 1000
	observationsMax  = 2000
	followUpMax      = 500
)

func (s *Service) completeDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.completeDrawers == nil || s.existingApp != nil {
		return nil, false, nil
	}
	m := completeDrawer.FindStringSubmatch(strings.TrimSuffix(path, "/"))
	if m == nil {
		return nil, false, nil
	}
	f, err := s.completeDrawers.CompleteDrawer(ctx, p, m[1])
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	var courses []coreforms.Course
	if f.SSA {
		var followUps []coreforms.FollowUp
		courses, followUps, err = coreforms.NewService(s.db, s.clock).CompletionLists(ctx, f.SchoolID, f.Planned, f.FY, ssaInterventionChoices)
		if err != nil {
			return nil, true, err
		}
		if len(followUps) > 0 {
			// The follow-up picker is drawn by the existing application until
			// it is compared.
			return nil, false, nil
		}
	}
	return &screensv1.GetDrawerResponse{Drawer: completionDrawer(f, rbac.Grants(p.ActiveRole, schoolCreatePerm), courses...)}, true, nil
}

// completionDrawer is complete_drawer.html as the feed reads it, for a work
// with one Salesforce ID, no purpose to choose, no SSA scores, no
// accountability and no return note.
func completionDrawer(f activities.CompleteFacts, canAddSchool bool, courses ...coreforms.Course) *screensv1.PageDrawer {
	title := "Complete " + strings.ReplaceAll(f.ActivityType, "_", " ")
	if f.SchoolName != "" {
		title += " at " + f.SchoolName
	}
	items := []*screensv1.DrawerItem{
		drawerField(&screensv1.DrawerField{
			Name: "actual_delivery_date", Label: completedOnLabel(f.ActivityType), Kind: "date", Value: f.Delivered,
			Required: true, Help: completedOnHelp, MaxDate: f.Today,
		}),
	}
	if f.SSA {
		items = append(items, purposeItems(f, courses)...)
		items = append(items, ssaItems()...)
	}
	items = append(items, salesforceField(f.SalesforceKind))
	if f.SSA {
		followUpShown := []*screensv1.DrawerCondition{{Field: "purpose_type", Values: []string{"training_follow_up"}}}
		items = append(items,
			&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: "Training followed up"}, ShowWhen: followUpShown},
			shownWhen(note("This school is not recorded as attending any training or cluster session in FY"+f.FY+". Submit that session's completion with the school ticked as attended first — a follow-up visit is completed against the session it answers.", "danger"), followUpShown))
	}
	if f.Attendance {
		zero := 0.0
		items = append(items,
			drawerField(&screensv1.DrawerField{Name: "teachers_attended", Label: "Teachers attended", Kind: "number", Value: f.Teachers, Min: &zero}),
			drawerField(&screensv1.DrawerField{Name: "leaders_attended", Label: "Leaders attended", Kind: "number", Value: f.Leaders, Min: &zero}))
		if f.Cluster {
			items = append(items, registerItems(f, canAddSchool)...)
		}
	}
	items = append(items,
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: "What you observed (optional)"}},
		drawerText(observedNote),
		drawerField(&screensv1.DrawerField{Name: "actual_outcome", Label: "Outcome", Kind: "textarea", Value: f.Outcome, MaxLength: length(outcomeMax)}),
		drawerField(&screensv1.DrawerField{Name: "actual_observations", Label: "Observations", Kind: "textarea", Value: f.Observations, MaxLength: length(observationsMax)}),
		drawerField(&screensv1.DrawerField{Name: "follow_up_note", Label: "Follow-up needed (optional)", Kind: "text", Value: f.FollowUp, MaxLength: length(followUpMax)}),
	)
	return &screensv1.PageDrawer{
		Title: title, HasRequired: true, Items: items,
		SubmitLabel: "Submit completion", CancelLabel: "Cancel", CanSubmit: true,
	}
}

func completedOnLabel(activityType string) string {
	switch {
	case activityType == "school_visit":
		return "Date the school was visited"
	case activityType == "cluster_meeting":
		return "Date the meeting was held"
	case strings.Contains(activityType, "training"):
		return "Date the training was held"
	}
	return "Date completed"
}

func salesforceField(kind string) *screensv1.DrawerItem {
	if kind == "training" {
		return drawerField(&screensv1.DrawerField{Name: "salesforce_id", Label: "Training ID", Kind: "text", Required: true,
			Help: "The training ID from Salesforce completes this activity.", Placeholder: "e.g. TS-998877"})
	}
	return drawerField(&screensv1.DrawerField{Name: "salesforce_id", Label: "Visit ID", Kind: "text", Required: true,
		Help: "The visit ID from Salesforce completes this activity.", Placeholder: "e.g. SV-11223344 or SVE-11223344"})
}

// registerItems are the register: its search (which the app does not
// reload, as the feed names no target) and the cluster's schools, after the
// "Select all" box the feed reads as one more, unnamed, option.
func registerItems(f activities.CompleteFacts, canAddSchool bool) []*screensv1.DrawerItem {
	search := &screensv1.DrawerField{Name: "q", Label: "Find a school already in Edify", Kind: "search",
		Placeholder: "School name or ID", ReloadsPath: "/my-plan/" + f.ActivityID + "/register-school-search"}
	if canAddSchool {
		search.Help = registerAddHelp
	}
	var options []*screensv1.DrawerOption
	var ticked []string
	for _, school := range f.Register {
		options = append(options, &screensv1.DrawerOption{Value: school.ID, Label: school.Name, Detail: school.Code})
		if school.Ticked {
			ticked = append(ticked, school.ID)
		}
	}
	if len(options) > 0 {
		options = append(options, &screensv1.DrawerOption{Value: "on"})
	}
	return []*screensv1.DrawerItem{
		drawerText("Schools that attended"),
		drawerField(search),
		drawerField(&screensv1.DrawerField{Name: registerField, Kind: "checklist", Options: options, Value: strings.Join(ticked, ",")}),
	}
}

func length(n int32) *int32 { return &n }

// The purposes a School Visit + SSA Collection may be completed as
// (completion_purpose_options), and the sections that follow the choice.
var (
	completionPurposeChoices = [][2]string{{"ssa_support", "SSA Support"}, {"in_school_training", "In-school Training"},
		{"in_school_training_ssa", "In-school Training + SSA Collection"}, {"training_follow_up", "Training Follow Up"}}
	inSchoolTrainingShown  = []*screensv1.DrawerCondition{{Field: "purpose_type", Values: []string{"in_school_training", "in_school_training_ssa"}}}
	ssaNotCollectedReasons = [][2]string{{"", "Choose a reason…"}, {"School leader unavailable", "School leader unavailable"},
		{"Assessment not completed", "Assessment not completed"}, {"Time insufficient", "Not enough time"},
		{"Data collection postponed", "Data collection postponed"}, {"Wrong school visited", "Wrong school visited"},
		{"Other", "Other"}}
)

const completionPurposeHelp = "What the visit was for. Completing it as an In-school Training (with or without SSA Collection) adds the training to this visit, and each takes its own Salesforce ID."

// purposeItems are the purpose and the training delivered.
func purposeItems(f activities.CompleteFacts, courses []coreforms.Course) []*screensv1.DrawerItem {
	trainings := []*screensv1.DrawerOption{{Value: "", Label: "Select the training"}}
	for _, c := range courses {
		trainings = append(trainings, &screensv1.DrawerOption{Value: c.ID, Label: c.Label + " · " + c.InterventionLabel})
	}
	zero := 0.0
	return []*screensv1.DrawerItem{
		drawerField(&screensv1.DrawerField{Name: "purpose_type", Label: "Purpose of the visit", Kind: "select",
			Value: f.CurrentPurpose, Required: true, Help: completionPurposeHelp, Options: choiceOptions(completionPurposeChoices)}),
		{Kind: &screensv1.DrawerItem_Heading{Heading: "Training delivered"}, ShowWhen: inSchoolTrainingShown},
		drawerField(&screensv1.DrawerField{Name: "training_course_id", Label: "Which training was delivered?", Kind: "select",
			Required: true, Options: trainings, ShowWhen: inSchoolTrainingShown}),
		drawerField(&screensv1.DrawerField{Name: "teachers_attended", Label: "Teachers attended", Kind: "number", Value: "0", Min: &zero, ShowWhen: inSchoolTrainingShown}),
		drawerField(&screensv1.DrawerField{Name: "leaders_attended", Label: "Leaders attended", Kind: "number", Value: "0", Min: &zero, ShowWhen: inSchoolTrainingShown}),
		drawerField(&screensv1.DrawerField{Name: "training_salesforce_id", Label: "Training ID", Kind: "text", Required: true,
			Help:        "The training's ID from Salesforce. The visit's ID is asked below; both are checked together.",
			Placeholder: "e.g. TS-998877", ShowWhen: inSchoolTrainingShown}),
	}
}

// ssaItems are the SSA section: collected or not, the eight scores, or why
// none were taken.
func ssaItems() []*screensv1.DrawerItem {
	const asked = "Were SSA scores collected on this activity?"
	zero, ten, tenth := 0.0, 10.0, 0.1
	collected := []*screensv1.DrawerCondition{{Field: "ssa_collected", Values: []string{"yes"}}}
	items := []*screensv1.DrawerItem{
		{Kind: &screensv1.DrawerItem_Heading{Heading: asked}},
		{Kind: &screensv1.DrawerItem_Heading{Heading: "SSA scores (optional)"}},
		drawerText("Enter all eight scores if they were collected, or leave them blank. The Salesforce ID below is what completes the visit."),
		drawerField(&screensv1.DrawerField{Name: "ssa_collected", Label: asked, Kind: "radio", Value: "yes",
			Options: choiceOptions([][2]string{{"yes", "SSA data collected"}, {"no", "No, not collected"}})}),
		shownWhen(drawerText("Each score is from 0 to 10."), collected),
	}
	for _, c := range ssaInterventionChoices {
		items = append(items, drawerField(&screensv1.DrawerField{Name: "score_" + c[0], Label: c[1], Kind: "number",
			Min: &zero, Max: &ten, Step: &tenth, ShowWhen: collected}))
	}
	return append(items, drawerField(&screensv1.DrawerField{Name: "ssa_not_collected_reason",
		Label: "Reason SSA was not collected (optional)", Kind: "select", Options: choiceOptions(ssaNotCollectedReasons),
		ShowWhen: []*screensv1.DrawerCondition{{Field: "ssa_collected", Values: []string{"no"}}}}))
}

// shownWhen is the item, shown only under the conditions.
func shownWhen(item *screensv1.DrawerItem, when []*screensv1.DrawerCondition) *screensv1.DrawerItem {
	item.ShowWhen = when
	return item
}
