package activities

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The bulk Schedule on a list of ticked schools (planning_views.
// bulk_schedule_action_view and _staff_schedule_plan): the planner's one
// purpose and date, each school its own costed activity through the single
// Schedule's rules, a school those rules refuse named and left out.

const (
	// bulkScheduleMaxSchools is BULK_SCHEDULE_MAXIMUM_SCHOOLS.
	bulkScheduleMaxSchools = 50
	bulkNoSchools          = "No schools in your planning portfolio were selected."
	bulkNoDate             = "Choose a delivery date."
	bulkNoPurpose          = "Select the purpose of the visit before scheduling."
	bulkNoTraining         = "Select the Training to deliver."
	bulkFollowUpNamed      = "A Training Follow Up names the training it follows, which differs from school to school. Schedule it from each school's own Schedule."
	bulkOutcome            = "Complete the planned support and record evidence."
	bulkHandedOnSchool     = "This could not be scheduled here."
	bulkRefusedTitle       = "Could not schedule the selection: "
)

// BulkScheduleRequest is the drawer's post: the ticked schools (codes or
// keys, comma-joined or not) and the planner's one plan.
type BulkScheduleRequest struct {
	Codes                        []string
	Purpose, Course, Date, Focus string
}

// bulkPlan is _staff_schedule_plan for a list of schools.
type bulkPlan struct {
	purpose, activityType, label, reason string
}

// bulkPurposeOf is the plan's purpose: split_training_purpose, then
// normalise_visit_purpose(for_partner=False). An In-school Training pair in
// bulk is handed on.
func bulkPurposeOf(raw, course string) (bulkPlan, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return bulkPlan{}, refuse(bulkNoPurpose)
	}
	purpose := raw
	if raw == "in_school_training_ssa" {
		purpose = rules.Pair.TrainingPurpose
	}
	label := rules.Purposes.Labels[purpose]
	if label == "" {
		label = purpose
	}
	if in(rules.Purposes.Retired, purpose) {
		return bulkPlan{}, refuse("%s is no longer scheduled on its own. Choose In-school Training for this work.", label)
	}
	if !in(rules.Purposes.Staff, purpose) {
		return bulkPlan{}, refuse("%s cannot be assigned to a staff member.", label)
	}
	if purpose == rules.Pair.TrainingPurpose {
		if strings.TrimSpace(course) == "" {
			return bulkPlan{}, refuse(bulkNoTraining)
		}
		return bulkPlan{}, handOn("an In-school Training pair scheduled in bulk")
	}
	return bulkPlan{purpose: purpose, activityType: rules.Purposes.ActivityTypes[purpose], label: label,
		reason: label + " selected by the planner."}, nil
}

// ScheduleRefusal is can_schedule_activity's refusal for the role
// (_no_scheduling_permission_message), or "" when the role schedules.
func ScheduleRefusal(role string) string {
	switch {
	case in(rules.Doors.Drawer, role):
		return ""
	case role == rules.Doors.AdminRole:
		return rules.Doors.AdminRefusal
	}
	return noPermission
}

// StaffPurposes are STAFF_VISIT_PURPOSES in their order, value then label.
func StaffPurposes() [][2]string {
	out := make([][2]string, 0, len(rules.Purposes.Staff))
	for _, value := range rules.Purposes.Staff {
		out = append(out, [2]string{value, rules.Purposes.Labels[value]})
	}
	return out
}

func plural(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// bulkScheduledMessage is the view's confirmation.
func bulkScheduledMessage(scheduled, outside int, refused []string) string {
	message := fmt.Sprintf("Scheduled %d %s.", scheduled, plural(scheduled, "school", "schools"))
	if outside > 0 {
		message += fmt.Sprintf(" %d selected %s %s outside your planning portfolio and left out.",
			outside, plural(outside, "school", "schools"), plural(outside, "is", "are"))
	}
	if len(refused) > 0 {
		message += " Not scheduled: " + strings.Join(refused, "; ")
	}
	return message
}

// tickedCodes is _ticked_schools' codes: each value split on commas, trimmed,
// the first of each kept, at most the maximum.
func tickedCodes(values []string) []string {
	var codes []string
	seen := map[string]bool{}
	for _, value := range values {
		for _, code := range strings.Split(value, ",") {
			code = strings.TrimSpace(code)
			if code == "" || seen[code] {
				continue
			}
			seen[code] = true
			codes = append(codes, code)
		}
	}
	if len(codes) > bulkScheduleMaxSchools {
		codes = codes[:bulkScheduleMaxSchools]
	}
	return codes
}

// TickedSchool is one school of the selection in the planner's portfolio.
type TickedSchool struct {
	ID, Code, Name, ClusterID string
	CreatedAt                 time.Time
}

// TickedSchools is _ticked_schools: the operating schools among the codes in
// the person's own portfolio, by name, and how many codes were posted.
func (s *Service) TickedSchools(ctx context.Context, p auth.Principal, values []string) ([]TickedSchool, int, error) {
	codes := tickedCodes(values)
	if len(codes) == 0 {
		return nil, 0, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, 0, handOn("no scope: " + err.Error())
	}
	rows, err := s.db.Query(ctx, `SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(s.cluster_id, ''), s.created_at
  FROM school s WHERE s.deleted_at IS NULL AND (s.school_id = ANY($1) OR s.id = ANY($1)) AND s.id = ANY($2)
 ORDER BY s.name, s.id`, codes, scope.OwnSchoolIDs)
	if err != nil {
		return nil, 0, fmt.Errorf("activities: reading the ticked schools: %w", err)
	}
	defer rows.Close()
	var schools []TickedSchool
	for rows.Next() {
		var t TickedSchool
		if err := rows.Scan(&t.ID, &t.Code, &t.Name, &t.ClusterID, &t.CreatedAt); err != nil {
			return nil, 0, fmt.Errorf("activities: reading a ticked school: %w", err)
		}
		schools = append(schools, t)
	}
	return schools, len(codes), rows.Err()
}

// BulkSchedule makes the bulk Schedule, or refuses it in the existing words,
// or hands it on (ErrHandOn) before anything is written.
func (s *Service) BulkSchedule(ctx context.Context, p auth.Principal, req BulkScheduleRequest, origin Origin) (Answer, error) {
	if refusal := ScheduleRefusal(p.ActiveRole); refusal != "" {
		return Answer{}, &Refusal{Message: refusal, Forbidden: true}
	}
	if in(rules.Doors.Requesters, p.ActiveRole) || p.InActingAppointment || p.StaffProfileID == "" {
		return Answer{}, handOn("not a planner scheduling their own portfolio in bulk")
	}
	schools, posted, err := s.TickedSchools(ctx, p, req.Codes)
	if err != nil {
		return Answer{}, err
	}
	if len(schools) == 0 {
		return Answer{}, refuse(bulkNoSchools)
	}
	date := strings.TrimSpace(req.Date)
	if date == "" {
		return Answer{}, refuse(bulkNoDate)
	}
	plan, item, err := s.bulkPlanOf(ctx, p, req)
	var refusal *Refusal
	if errors.As(err, &refusal) {
		// error_fragment(exc, action="Could not schedule the selection").
		return Answer{}, refuse("%s%s", bulkRefusedTitle, refusal.Message)
	}
	if err != nil {
		return Answer{}, err
	}
	dayFocus := ""
	if focus := strings.TrimSpace(req.Focus); focus != "" && canonicalNamed(focus) {
		dayFocus = focus
	}
	requests := make([]Request, len(schools))
	for i, school := range schools {
		focus, err := s.bulkFocus(ctx, plan, school, dayFocus)
		if err != nil {
			return Answer{}, err
		}
		requests[i] = Request{SchoolID: school.Code, Purpose: plan.purpose, Date: date, Goal: plan.label + " at " + school.Name,
			Outcome: bulkOutcome, CatalogueItemID: item.ID, RecReason: plan.reason, Focus: focus}
	}
	// Every school's case before anything is written: a school Go does not
	// take hands the whole selection on, as one transaction would.
	for _, r := range requests {
		var refusal *Refusal
		if _, err := s.prepare(ctx, p, r, origin); err != nil && !errors.As(err, &refusal) {
			return Answer{}, err
		}
	}
	scheduled, notice, refused := 0, "", []string{}
	for i, r := range requests {
		saved, err := s.Schedule(ctx, p, r, origin)
		var refusal *Refusal
		switch {
		case errors.As(err, &refusal):
			refused = append(refused, schools[i].Name+": "+refusal.Message)
		case errors.Is(err, ErrHandOn):
			s.logger.Warn("activities: a bulk school was handed on after the first pass", "school", schools[i].Code, "err", err)
			refused = append(refused, schools[i].Name+": "+bulkHandedOnSchool)
		case err != nil:
			return Answer{}, err
		default:
			scheduled++
			notice = saved.Notice
		}
	}
	message := bulkScheduledMessage(scheduled, posted-len(schools), refused)
	if scheduled == 0 {
		return Answer{}, refuse("%s%s", bulkRefusedTitle, message)
	}
	return Answer{Message: message, Notice: notice}, nil
}

// bulkPlanOf is _staff_schedule_plan: the purpose, the follow-up rule and
// the one item that costs the purpose.
func (s *Service) bulkPlanOf(ctx context.Context, p auth.Principal, req BulkScheduleRequest) (bulkPlan, *item, error) {
	plan, err := bulkPurposeOf(req.Purpose, req.Course)
	if err != nil {
		return bulkPlan{}, nil, err
	}
	now := s.now()
	if plan.purpose == followUpPurpose {
		needs, err := followUpNeedsTraining(ctx, s.db, p.Country, schooldirectory.OperationalFY(now))
		if err != nil {
			return bulkPlan{}, nil, err
		}
		if needs {
			return bulkPlan{}, nil, refuse(bulkFollowUpNamed)
		}
	}
	it, err := resolveForKind(ctx, s.db, plan.activityType, dateOnly(now.In(s.kampala)))
	if err != nil {
		return bulkPlan{}, nil, err
	}
	if it == nil {
		return bulkPlan{}, nil, refuse("No single approved Catalogue Activity costs “%s”. Ask the Country Director to define one costing for it before scheduling this purpose.", plan.label)
	}
	return plan, it, nil
}

// bulkFocus is _bulk_schedule_focus: none for a purpose that moves no single
// intervention, the planner's one for the day, else the school's first need.
func (s *Service) bulkFocus(ctx context.Context, plan bulkPlan, school TickedSchool, dayFocus string) (string, error) {
	if in(rules.Purposes.InterventionFree, plan.purpose) {
		return "", nil
	}
	if dayFocus != "" {
		return dayFocus, nil
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, school.ID, school.ClusterID, s.now())
	if err != nil {
		return "", err
	}
	if len(need.Priorities) > 0 {
		return need.Priorities[0], nil
	}
	return "", nil
}
