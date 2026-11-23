package screens

import (
	"context"
	"errors"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
)

// getScheduleDrawerInGo is schedule_modal_view for one school: the form the
// clients draw, from the rules Django draws it from. Opening it writes nothing.
func (s *Service) getScheduleDrawerInGo(ctx context.Context, p auth.Principal, schoolID string) (*screensv1.GetPlanningDrawerResponse, bool, error) {
	form, err := coreforms.NewService(s.db, s.clock).ScheduleFor(ctx, p, schoolID, ssaInterventionChoices)
	var refusal *coreforms.Refusal
	switch {
	case errors.As(err, &refusal):
		return &screensv1.GetPlanningDrawerResponse{Refusal: refusal.Message}, true, nil
	case errors.Is(err, coreforms.ErrNotFound):
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "School not found.")
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetPlanningDrawerResponse{Drawer: planningScheduleDrawer(form)}, true, nil
}

// planningScheduleDrawer is planning_drawers.read_schedule for the form.
func planningScheduleDrawer(f coreforms.ScheduleForm) *screensv1.PlanningDrawer {
	drawer := &screensv1.PlanningDrawer{
		Kind: "schedule", Title: "Schedule visit for " + f.School.Name, SubmitLabel: "Schedule visit", CancelLabel: "Cancel",
		Lead: planningLead(f.Lead), ExistingPlans: planningExisting(f.Existing),
		InitialPurpose: f.InitialPurpose, InitialTraining: f.Selected, DefaultCatalogueItem: f.Selected,
		Interventions: choiceOptions(ssaInterventionChoices), InitialIntervention: f.InitialIntervention, SsaPriorities: f.Priorities,
		ActivityType: f.ActivityType, RecommendationReason: f.RecommendationReason,
		FollowUpRequiresTraining: f.FollowUpRequired, PurposesLockedEveryYear: f.Locks.EveryYear,
		TrainingLocks: f.Locks.Training, TrainingLockedEveryYear: f.Locks.TrainingEveryYear,
		Captions: scheduleCaptions(f), HasJustification: f.OwnerName != "",
		Placeholders: map[string]string{
			"purpose_of_visit": "Select a purpose…", "training_activity_id": "Select a training…",
			"focus_intervention": "Select an intervention…", "source_activity_id": "Select a training this school did…",
			"school_facilitating_partner_id": "Staff",
		},
		Labels: scheduleLabels(f.OwnerName != ""),
		Hidden: map[string]string{"school_id": f.School.Code, "require_catalogue": "yes"},
	}
	for _, purpose := range f.Purposes {
		drawer.Purposes = append(drawer.Purposes, &screensv1.DrawerOption{Value: purpose.Value, Label: purpose.Label, Disabled: purpose.Disabled})
	}
	if f.OutreachNote != "" {
		drawer.PurposeNotes = []string{f.OutreachNote}
	}
	drawer.VisitLocks = make(map[string]*screensv1.YearReasons, len(f.Locks.Visit))
	for purpose, years := range f.Locks.Visit {
		drawer.VisitLocks[purpose] = &screensv1.YearReasons{ByYear: years}
	}
	drawer.Profiles = make(map[string]*screensv1.PurposeProfile, len(f.Profiles))
	for purpose, profile := range f.Profiles {
		drawer.Profiles[purpose] = &screensv1.PurposeProfile{RequiresParticipants: profile.RequiresParticipants,
			Schedulable: profile.Schedulable, UnavailableReason: profile.UnavailableReason}
	}
	for _, course := range f.Courses {
		drawer.Trainings = append(drawer.Trainings, &screensv1.PlanningTraining{
			Id: course.ID, Label: course.Label, StableCode: course.Code, Category: course.Category, SsaIndicator: course.Indicator,
			SsaIntervention: course.Intervention, SsaInterventionLabel: course.InterventionLabel, PlannerChooses: course.PlannerChooses,
			Universal: course.Universal, StaffDeliveryAllowed: true, CertifiedAgencyDeliveryAllowed: course.CertifiedAllowed,
			PriorityTitles: course.PriorityTitles,
		})
	}
	for _, row := range f.FollowUps {
		drawer.FollowUps = append(drawer.FollowUps, &screensv1.PlanningFollowUp{Id: row.ID, Label: row.Label, InterventionLabel: row.InterventionLabel})
	}
	drawer.Facilitators = []*screensv1.DrawerOption{{Label: "Staff"}}
	for _, partner := range f.Facilitators {
		drawer.Facilitators = append(drawer.Facilitators, &screensv1.DrawerOption{Value: partner.Value, Label: partner.Label})
	}
	return drawer
}

func planningLead(items []coreforms.LeadItem) []*screensv1.PlanningLeadItem {
	lead := make([]*screensv1.PlanningLeadItem, 0, len(items))
	for _, item := range items {
		switch {
		case item.Heading != "":
			lead = append(lead, &screensv1.PlanningLeadItem{Kind: &screensv1.PlanningLeadItem_Heading{Heading: item.Heading}})
		case item.Line != nil:
			lead = append(lead, &screensv1.PlanningLeadItem{Kind: &screensv1.PlanningLeadItem_Line{Line: &screensv1.PlanningLine{
				Label: item.Line.Label, Value: item.Line.Value, Tone: item.Line.Tone}}})
		case item.Note != nil:
			lead = append(lead, &screensv1.PlanningLeadItem{Kind: &screensv1.PlanningLeadItem_Note{Note: &screensv1.PlanningNote{
				Title: item.Note.Title, Text: item.Note.Text, Tone: item.Note.Tone}}})
		default:
			lead = append(lead, &screensv1.PlanningLeadItem{Kind: &screensv1.PlanningLeadItem_Text{Text: item.Text}})
		}
	}
	return lead
}

func planningExisting(existing *coreforms.ExistingPlans) *screensv1.ExistingPlans {
	if existing == nil {
		return nil
	}
	plans := make([]*screensv1.ExistingPlan, len(existing.Plans))
	for i, plan := range existing.Plans {
		plans[i] = &screensv1.ExistingPlan{Label: plan.Label, Status: plan.Status, Tone: plan.Tone}
	}
	return &screensv1.ExistingPlans{
		Note:  &screensv1.PlanningNote{Title: "This school already has plans this year", Text: existing.Message, Tone: "warning"},
		Plans: plans,
		Buttons: map[string]string{"view": "View Existing Plans", "continue": "Continue Planning",
			"follow-up": "Plan as Follow-Up", "cancel": "Cancel"},
	}
}

func scheduleLabels(asksWhy bool) map[string]string {
	labels := map[string]string{
		"purpose_of_visit": "Purpose of visit", "training_activity_id": "Training", "focus_intervention": "Focus intervention",
		"ssa_deviation_reason": "Why this plan departs from the SSA", "source_activity_id": "Training followed up",
		"school_facilitating_partner_id": "Facilitated by", "scheduled_date": "Scheduled date",
		"expected_participants": "Planned participants", "activity_purpose_text": "Goal", "training-ssa-label": "SSA intervention",
	}
	if asksWhy {
		labels["visit_justification"] = "Why you need to visit this school"
	}
	return labels
}

// scheduleCaptions are the drawer's sentences, by the name the clients read
// them under.
func scheduleCaptions(f coreforms.ScheduleForm) map[string]string {
	captions := map[string]string{
		"followUpDone":         "Trainings this school completed in fiscal year " + f.FY + ", at the school or at cluster sessions.",
		"followUpNoneRequired": "No completed training is recorded for this school in fiscal year " + f.FY + ".",
		"followUpNoneOptional": "No prior training recorded. The follow-up can still be planned; its focus comes from the school's SSA.",
		"trainingHelp":         "After delivery, confirm it with its Salesforce Training ID beginning TS-.",
		"linkedIntervention":   "Set on the training in the Training Catalogue. It cannot be changed here.",
		"deviationNamed":       "The verified SSA does not rank this intervention among the school's priorities.",
		"deviationUnnamed":     "No intervention is named.",
		"facilitated":          "A partner facilitating this training is not assigned the school. Assign the school to a partner separately for follow-ups and other support.",
		"dateYearUsed":         "This date's financial year has already had this visit at the school. Choose a date in another financial year, or another purpose.",
		"responsible":          f.Responsible,
		"goalPlaceholder":      "What should this visit achieve?",
	}
	if f.TopLabel != "" {
		captions["deviationNamed"] = "The verified SSA does not rank this intervention among the school's priorities (" + f.TopLabel + " is first)."
		captions["deviationUnnamed"] = "No intervention is named; the verified SSA ranks " + f.TopLabel + " first."
	}
	if f.Stale {
		captions["ssaStale"] = "This school's verified SSA is out of date. Plan an SSA collection so support rests on this year's scores."
	}
	if len(f.Locks.Reasons) > 0 {
		tail := "Donor, content gathering, invitation and social visits can still be scheduled"
		if !f.Locks.AllEveryYear {
			tail += ", and a used visit on a date in another financial year"
		}
		captions["lockTail"] = tail + "."
		if f.Locks.AllEveryYear {
			captions["lockStatic"] = strings.Join(f.Locks.Reasons, " ")
		}
	}
	switch {
	case f.OwnerName != "":
		captions["responsibleHelp"] = "You are the one visiting. " + f.OwnerName + " is asked to approve, not to go."
		captions["justificationPlaceholder"] = "Why you, rather than " + f.OwnerName + "?"
		captions["justificationHelp"] = f.OwnerName + " reads this when deciding."
	case f.VisitIsYours:
		captions["responsibleHelp"] = "This school is in someone else’s portfolio, so the visit lands on your plan and in your budget."
	default:
		captions["responsibleHelp"] = "Assigned from this school’s portfolio owner."
	}
	return captions
}
