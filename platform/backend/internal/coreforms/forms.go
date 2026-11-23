package coreforms

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workplan"
)

var (
	// partnerPurposes is PARTNER_VISIT_PURPOSES.
	partnerPurposes = []Choice{
		{"in_school_training", "In-school Training"},
		{"training_follow_up", "Training Follow Up"},
		{"ssa_support", "SSA Support"},
	}
	// staffPurposes is STAFF_VISIT_PURPOSES.
	staffPurposes = []Choice{
		{"in_school_training", "In-school Training"},
		{"in_school_training_ssa", "In-school Training + SSA Collection"},
		{"training_follow_up", "Training Follow Up"},
		{"ssa_support", "SSA Support"},
		{"donor_visit", "Donor Visit"},
		{"story_gathering", "Content/Story Collection"},
		{"school_invitation", "School Invitation"},
		{"social_visit", "Social Visit"},
	}
	// TrainingPurposes is IN_SCHOOL_TRAINING_PURPOSES.
	TrainingPurposes = []string{"in_school_training", "in_school_training_ssa"}
	// projectPageRoles is PAGE_PERMISSIONS["projects"].
	projectPageRoles = []string{roleAdmin, roleCCEO, roleCD, roleIA, rolePL, rolePC}
	// coreTrainingPlanners is can_schedule_activity with no school named.
	coreTrainingPlanners = []string{roleCCEO, rolePL, rolePC}
	kampala              = mustZone("Africa/Kampala")
)

func mustZone(name string) *time.Location {
	zone, err := time.LoadLocation(name)
	if err != nil {
		panic(fmt.Sprintf("coreforms: loading %s: %v", name, err))
	}
	return zone
}

// Menu is core_schedule_activity_drawer.
type Menu struct {
	School                                 School
	Package                                Package
	StaffCanVisit                          bool
	StaffVisitReason                       string
	StaffVisits, StaffVisitCap, VisitsLeft int
	StaffTrainingsOpen, CanPlanTraining    bool
	StaffTrainings, StaffTrainingCap       int
	TrainingsLeft                          int
}

// VisitForm is core_schedule_visit_drawer.
type VisitForm struct {
	School                   School
	Purposes                 []Choice
	NonPackagePurposes       []string
	Package                  Package
	Recommendations          []Need
	FocusCode, FocusLabel    string
	Courses                  []Course
	FollowUps                []FollowUp
	FollowUpRequired         bool
	FY                       string
	Staff                    []Choice
	Responsible              string
	OwnerName, RequesterName string
}

// TrainingForm is core_schedule_training_drawer.
type TrainingForm struct {
	School          School
	Package         Package
	Recommendations []Need
	Courses         []Course
	Facilitators    []Choice
}

// AssignForm is core_assign_partner_drawer.
type AssignForm struct {
	School                    School
	Purposes                  []Choice
	Package                   Package
	Partners                  []Partner
	Courses                   []Course
	FollowUps                 []FollowUp
	FollowUpRequired          bool
	FY                        string
	Handovers                 []projectcapacity.HandoverRoute
	VisitsUsed, TrainingsUsed int
	SideCap                   int
	VisitsOpen, TrainingsOpen bool
	SSAClosed, Today          string
}

func (s *Service) gateOf(ctx context.Context, school School, fy string) (visitgate.Gate, error) {
	gate, err := visitgate.Of(ctx, s.db, s.gates, school.gate(), fy, fy)
	if err != nil {
		return gate, fmt.Errorf("coreforms: reading the visit rule: %w", err)
	}
	return gate, nil
}

// MenuFor opens the Schedule Activity choice.
func (s *Service) MenuFor(ctx context.Context, p auth.Principal, code string) (Menu, error) {
	school, err := s.VisitTarget(ctx, p, code)
	if err != nil {
		return Menu{}, err
	}
	fy := schooldirectory.OperationalFY(s.now())
	pack, err := s.packageFor(ctx, school, fy)
	if err != nil {
		return Menu{}, err
	}
	gate, err := s.gateOf(ctx, school, fy)
	if err != nil {
		return Menu{}, err
	}
	caps := s.gates.Core.Caps
	menu := Menu{
		School: school, Package: pack, StaffCanVisit: gate.StaffCanSchedule, StaffVisitReason: gate.StaffReason,
		StaffVisits: gate.StaffVisits, CanPlanTraining: slices.Contains(coreTrainingPlanners, p.ActiveRole),
		StaffTrainingCap: caps.StaffTrainings,
	}
	switch gate.Rule {
	case "core":
		menu.StaffVisits, menu.StaffVisitCap = gate.Split.StaffVisits, caps.StaffVisits
		menu.StaffTrainings = gate.Split.StaffTrainings
		menu.StaffTrainingsOpen = menu.StaffTrainings < caps.StaffTrainings
	case "client":
		menu.StaffVisitCap = s.gates.StaffVisitCap
	}
	menu.VisitsLeft = max(0, menu.StaffVisitCap-menu.StaffVisits)
	menu.TrainingsLeft = max(0, caps.StaffTrainings-menu.StaffTrainings)
	return menu, nil
}

// need reads the recommendations and the first-ranked focus.
func (s *Service) need(ctx context.Context, school School) ([]Need, string, error) {
	summary, err := activities.SchoolNeed(ctx, s.db, school.ID, school.ClusterID, s.now())
	if err != nil {
		return nil, "", fmt.Errorf("coreforms: reading the school's need: %w", err)
	}
	rows := make([]Need, len(summary.Ranked))
	for i, row := range summary.Ranked {
		rows[i] = Need{Code: row.Intervention, Label: row.Label, Score: row.Score}
	}
	focus := ""
	if len(summary.Priorities) > 0 {
		focus = summary.Priorities[0]
	}
	return recommended(rows), focus, nil
}

func (s *Service) localDay() time.Time {
	now := s.now().In(kampala)
	return time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
}

func namesOf(choices [][2]string) map[string]string {
	names := make(map[string]string, len(choices))
	for _, choice := range choices {
		names[choice[0]] = choice[1]
	}
	return names
}

// VisitFor opens the Schedule Visit form.
func (s *Service) VisitFor(ctx context.Context, p auth.Principal, code string, interventions [][2]string) (VisitForm, error) {
	school, err := s.VisitTarget(ctx, p, code)
	if err != nil {
		return VisitForm{}, err
	}
	fy := schooldirectory.OperationalFY(s.now())
	names := namesOf(interventions)
	form := VisitForm{School: school, FY: fy, NonPackagePurposes: s.gates.Core.NonPackageVisitPurposes, RequesterName: p.Name}
	if form.RequesterName == "" {
		form.RequesterName = "You"
	}
	for _, purpose := range staffPurposes {
		if !SchedulesVisitsOnly(p.ActiveRole) || !slices.Contains(TrainingPurposes, purpose.Value) {
			form.Purposes = append(form.Purposes, purpose)
		}
	}
	if form.Package, err = s.packageFor(ctx, school, fy); err != nil {
		return VisitForm{}, err
	}
	if form.Recommendations, form.FocusCode, err = s.need(ctx, school); err != nil {
		return VisitForm{}, err
	}
	form.FocusLabel = names[form.FocusCode]
	if form.Courses, err = s.courses(ctx, names, s.localDay()); err != nil {
		return VisitForm{}, err
	}
	if form.FollowUps, err = s.followUps(ctx, school, fy, names, schoolprofile.ActivityTypeLabels()); err != nil {
		return VisitForm{}, err
	}
	if form.FollowUpRequired, err = activities.FollowUpNeedsTraining(ctx, s.db, p.Country, fy); err != nil {
		return VisitForm{}, fmt.Errorf("coreforms: reading the year's follow-up rule: %w", err)
	}
	if form.Staff, err = s.staffMembers(ctx); err != nil {
		return VisitForm{}, err
	}
	for _, member := range form.Staff {
		if member.Value == school.AccountOwner {
			form.Responsible = member.Value
		}
	}
	if p.ActiveRole == roleAccountant {
		if form.OwnerName, err = s.approvalOwner(ctx, school, p.UserID, p.StaffProfileID); err != nil {
			return VisitForm{}, err
		}
	}
	return form, nil
}

// TrainingFor opens the Schedule Training form.
func (s *Service) TrainingFor(ctx context.Context, p auth.Principal, code string, interventions [][2]string) (TrainingForm, error) {
	if SchedulesVisitsOnly(p.ActiveRole) {
		return TrainingForm{}, &Refusal{Message: TrainingRefused}
	}
	school, err := s.Operational(ctx, p, code)
	if err != nil {
		return TrainingForm{}, err
	}
	form := TrainingForm{School: school}
	if form.Package, err = s.packageFor(ctx, school, schooldirectory.OperationalFY(s.now())); err != nil {
		return TrainingForm{}, err
	}
	if form.Recommendations, _, err = s.need(ctx, school); err != nil {
		return TrainingForm{}, err
	}
	if form.Courses, err = s.courses(ctx, namesOf(interventions), s.localDay()); err != nil {
		return TrainingForm{}, err
	}
	if form.Facilitators, err = s.facilitators(ctx); err != nil {
		return TrainingForm{}, err
	}
	return form, nil
}

// AssignFor opens the Assign Core support form.
func (s *Service) AssignFor(ctx context.Context, p auth.Principal, code string, interventions [][2]string) (AssignForm, error) {
	if !MayAssign(p.ActiveRole) {
		return AssignForm{}, &Refusal{Message: AssignRefused}
	}
	school, err := s.Operational(ctx, p, code)
	if err != nil {
		return AssignForm{}, err
	}
	fy := schooldirectory.OperationalFY(s.now())
	names := namesOf(interventions)
	form := AssignForm{School: school, FY: fy, Purposes: partnerPurposes, SideCap: s.gates.Core.SideCap,
		Today: s.localDay().Format("2 Jan 2006")}
	if form.Package, err = s.packageFor(ctx, school, fy); err != nil {
		return AssignForm{}, err
	}
	if form.Partners, err = s.assignablePartners(ctx); err != nil {
		return AssignForm{}, err
	}
	all, err := s.courses(ctx, names, s.localDay())
	if err != nil {
		return AssignForm{}, err
	}
	for _, course := range all {
		if course.PartnerAllowed {
			form.Courses = append(form.Courses, course)
		}
	}
	if form.FollowUps, err = s.followUps(ctx, school, fy, names, schoolprofile.ActivityTypeLabels()); err != nil {
		return AssignForm{}, err
	}
	if form.FollowUpRequired, err = activities.FollowUpNeedsTraining(ctx, s.db, p.Country, fy); err != nil {
		return AssignForm{}, fmt.Errorf("coreforms: reading the year's follow-up rule: %w", err)
	}
	gate, err := s.gateOf(ctx, school, fy)
	if err != nil {
		return AssignForm{}, err
	}
	split := gate.Split
	form.VisitsUsed, form.TrainingsUsed = split.PartnerHeldVisits(), split.PartnerHeldTrainings()
	form.VisitsOpen = !split.HasPackage || form.VisitsUsed < form.SideCap
	form.TrainingsOpen = !split.HasPackage || form.TrainingsUsed < form.SideCap
	if !gate.CanAssignSSA {
		form.SSAClosed = gate.AssignSSAReason
	}
	if form.Handovers, err = s.handovers(ctx, p, school); err != nil {
		return AssignForm{}, err
	}
	return form, nil
}

// handovers is project_handover_routes, for a reader holding the Projects page.
func (s *Service) handovers(ctx context.Context, p auth.Principal, school School) ([]projectcapacity.HandoverRoute, error) {
	if !slices.Contains(projectPageRoles, p.ActiveRole) {
		return nil, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, fmt.Errorf("coreforms: resolving the scope: %w", err)
	}
	projects, err := workplan.ScopedProjects(ctx, s.db, p, scope)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the reader's projects: %w", err)
	}
	ids := make([]string, len(projects))
	for i, project := range projects {
		ids[i] = project[0]
	}
	return projectcapacity.NewService(s.db, s.now).HandoverRoutes(ctx, school.ID, ids)
}
