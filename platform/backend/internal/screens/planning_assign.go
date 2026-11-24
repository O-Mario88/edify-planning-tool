package screens

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
)

const assignKind = "assign"

// ClientAssigner is the Go save of the Planning drawer's Assign to Partner
// (internal/activities.Service).
type ClientAssigner interface {
	AssignClientPartner(ctx context.Context, p auth.Principal, req activities.ClientAssignRequest, origin activities.Origin) (activities.Answer, error)
}

// WithClientAssign makes Assign to Partner's save Go's where Go takes it.
// While Django is present its own drawer keeps it: the form has no
// form-only door to compose the post through.
func (s *Service) WithClientAssign(saver ClientAssigner) *Service {
	s.clientAssign = saver
	return s
}

// assignInGo is assign_partner_action_view; served is false when the save
// is forwarded, or handed on to the existing application.
func (s *Service) assignInGo(ctx context.Context, message *screensv1.SavePlanningDrawerRequest) (
	*screensv1.SavePlanningDrawerResponse, bool, error,
) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || s.clientAssign == nil || s.existingApp != nil || message.GetKind() != assignKind {
		return nil, false, nil
	}
	if !coreforms.MayAssign(p.ActiveRole) {
		return &screensv1.SavePlanningDrawerResponse{Saved: false, Error: coreforms.AssignPartnerRefused}, true, nil
	}
	req, taken := activities.ClientAssignRequestFromValues(message.GetSchoolId(), message.GetValues())
	if !taken {
		return nil, false, nil
	}
	saved, err := s.clientAssign.AssignClientPartner(ctx, p, req, activities.Origin{})
	return outcomeOf(ctx, s.logger, saved, err)
}

// getAssignDrawerInGo is assign_partner_modal_view for one school, drawn as
// the feed's planning_drawers.read_assign reads its page. Opening it writes
// nothing.
func (s *Service) getAssignDrawerInGo(ctx context.Context, p auth.Principal, schoolID string) (*screensv1.GetPlanningDrawerResponse, bool, error) {
	form, err := coreforms.NewService(s.db, s.clock).ClientAssignFor(ctx, p, schoolID, ssaInterventionChoices)
	var refusal *coreforms.Refusal
	switch {
	case errors.As(err, &refusal):
		return &screensv1.GetPlanningDrawerResponse{Refusal: refusal.Message}, true, nil
	case errors.Is(err, coreforms.ErrNotFound):
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "Not found.")
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetPlanningDrawerResponse{Drawer: planningAssignDrawer(form)}, true, nil
}

// planningAssignDrawer is read_assign of assign_partner_drawer.html.
func planningAssignDrawer(f coreforms.ClientAssignForm) *screensv1.PlanningDrawer {
	d := &screensv1.PlanningDrawer{
		Kind: "assign", Title: "Assign " + f.School.Name + " to a partner", SubmitLabel: "Assign to partner", CancelLabel: "Cancel",
		FollowUpRequiresTraining: f.FollowUpRequired, PurposeNotes: f.Notes, Interventions: choiceOptions(ssaInterventionChoices),
		PartnerCourses: map[string]*screensv1.CodeList{},
		Captions: map[string]string{
			"followUpDone":         "Trainings this school completed in fiscal year " + f.FY + ", at the school or at cluster sessions.",
			"followUpNoneRequired": "No completed training is recorded for this school in fiscal year " + f.FY + ".",
			"followUpNoneOptional": "No prior training recorded. The follow-up can still be planned; its focus comes from the school's SSA.",
			"partnerCourses":       "Showing the trainings this partner is recorded as delivering.",
			"trainingHelp":         "After delivery, it is confirmed with its Salesforce Training ID beginning TS-.",
			"linkedIntervention":   "Set on the training in the Training Catalogue. It cannot be changed here.",
			"plannerChooses":       "The Training Catalogue leaves this training open to any SSA intervention. Choose the one it targets.",
			"handoverTitle":        "", "handover": "",
			"assignedDateLabel": "Assigned date", "assignedDate": f.Today,
			"assignedDateHelp": "The day this assignment is made. The partner chooses the date of the work.",
			"monitoredBy":      "Monitored by " + f.Monitor + ", who stays responsible for this support.",
		},
		Placeholders: map[string]string{
			"partner_id": "Select partner…", "purpose_of_visit": "Select a reason…", "partner_training_activity": "Select a training…",
			"partner_training_focus_intervention": "No specific intervention", "partner_source_activity": "Select a training this school did…",
		},
		Labels: map[string]string{
			"partner_id": "Partner", "purpose_of_visit": "Reason for assigning", "partner_training_activity": "Training",
			"partner_source_activity": "Training followed up", "partner-training-ssa-label": "SSA intervention",
		},
		Hidden: map[string]string{"school_id": f.School.Code},
	}
	for _, partner := range f.Partners {
		d.Partners = append(d.Partners, &screensv1.DrawerOption{Value: partner.ID, Label: partner.Name})
		if len(partner.Codes) > 0 {
			d.PartnerCourses[partner.ID] = &screensv1.CodeList{Codes: partner.Codes}
		}
	}
	for _, purpose := range f.Purposes {
		d.Purposes = append(d.Purposes, &screensv1.DrawerOption{Value: purpose.Value, Label: purpose.Label, Disabled: purpose.Disabled})
	}
	for _, course := range f.Courses {
		d.Trainings = append(d.Trainings, &screensv1.PlanningTraining{
			Id: course.ID, Label: course.Label, StableCode: course.Code, Category: course.Category, SsaIndicator: course.Indicator,
			SsaIntervention: course.Intervention, SsaInterventionLabel: course.InterventionLabel, PlannerChooses: course.PlannerChooses,
			Universal: course.Universal, StaffDeliveryAllowed: true, CertifiedAgencyDeliveryAllowed: course.CertifiedAllowed,
			PriorityTitles: course.PriorityTitles,
		})
	}
	for _, row := range f.FollowUps {
		d.FollowUps = append(d.FollowUps, &screensv1.PlanningFollowUp{Id: row.ID, Label: row.Label, InterventionLabel: row.InterventionLabel})
	}
	if len(f.Handovers) > 0 {
		d.Captions["handoverTitle"] = "Or assign through a project"
		d.Captions["handover"] = "Opens the project's own activities and partners for this school."
		if f.School.Type == "core" {
			d.Captions["handover"] += " Project work counts toward the partner's half of the package; a project the SSA does not measure, such as Alumni, does not."
		}
		for _, route := range f.Handovers {
			d.ProjectHandovers = append(d.ProjectHandovers, &screensv1.ProjectHandover{Label: route.Project,
				Path: handoverLink(route).GetHref()})
		}
	}
	if f.Withdrawal != nil {
		d.Notes = []*screensv1.PlanningNote{{Title: "Previous partner withdrawal", Text: f.Withdrawal.Partner + " · " + f.Withdrawal.Reason,
			Tone: "warning"}}
	}
	return d
}
