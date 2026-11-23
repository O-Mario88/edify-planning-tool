package activities

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Core Schools visit form (core_schools_views.core_schedule_visit_action).
const (
	coreDateRefusal       = "Please choose a valid planned date and visit slot."
	noActivePackage       = "This school does not have an active core package."
	coreTrainingRefused   = "Core trainings are planned by the CCEO or Program Lead responsible for the school. Your role schedules school visits only."
	coreSourceNotEligible = "Choose a completed current-FY training this School did."
	coreFollowUpNeeds     = "Select the completed training this visit follows up."
	coreCalendarLabel     = "Open in Calendar"
	auditCoreVisit        = "schedule_core_visit"
	auditCoreOutreach     = "schedule_core_outreach_visit"
	auditCoreTraining     = "schedule_core_training"
)

// coreVisitRoles are the roles that open this form and may save it in Go.
var coreVisitRoles = []string{"CCEO", "Program Lead", "CountryDirector", "ImpactAssessment", "Accountant"}

// coreVisitFields are the fields the form posts. Any other carrying a value
// (a partner, a pinned item) is a case Go does not take.
var coreVisitFields = map[string]bool{
	"csrfmiddlewaretoken": true, "school_id": true, "purpose_of_visit": true, "scheduled_date": true,
	"visit_number": true, "focus_intervention": true, "responsible_staff_id": true, "source_activity_id": true,
	"visit_justification": true, "activity_goal": true, "visit_purpose": true, "expected_outcome": true,
	"recommendation_reason": true, "training_course_id": true, "training_number": true, "delivery_type": true,
}

// CoreVisitRequest is the Core visit form as posted.
type CoreVisitRequest struct {
	SchoolCode, Purpose, Date, VisitNumber, Focus, Responsible string
	SourceActivityID, Goal, Outcome, Justification, RecReason  string
	TrainingCourseID, TrainingNumber                           string
}

// CoreVisitRequestFromForm reads the form; false when Go does not take it.
func CoreVisitRequestFromForm(schoolCode string, form url.Values) (CoreVisitRequest, bool) {
	for name, values := range form {
		if coreVisitFields[name] {
			continue
		}
		for _, value := range values {
			if strings.TrimSpace(value) != "" {
				return CoreVisitRequest{}, false
			}
		}
	}
	text := func(name string) string { return strings.TrimSpace(form.Get(name)) }
	goal := text("activity_goal")
	if goal == "" {
		goal = text("visit_purpose")
	}
	return CoreVisitRequest{
		SchoolCode: strings.TrimSpace(schoolCode), Purpose: text("purpose_of_visit"), Date: text("scheduled_date"),
		VisitNumber: text("visit_number"), Focus: text("focus_intervention"), Responsible: text("responsible_staff_id"),
		SourceActivityID: text("source_activity_id"), Goal: goal, Outcome: text("expected_outcome"),
		Justification: text("visit_justification"), RecReason: form.Get("recommendation_reason"),
		TrainingCourseID: text("training_course_id"), TrainingNumber: text("training_number"),
	}, true
}

// openCoreSlotAt is _free_slot: the slot asked for while it is open, else the
// lowest one that is.
func openCoreSlotAt(slots []coreSlot, preferred int, taken func(string) bool) *coreSlot {
	for i := range slots {
		if slots[i].Sequence == preferred && !taken(slots[i].Status) {
			return &slots[i]
		}
	}
	return openCoreSlot(slots, taken)
}

// coreSlotNumber is int(posted or 1).
func coreSlotNumber(raw string) (int, error) {
	if raw == "" {
		return 1, nil
	}
	return strconv.Atoi(raw)
}

func coreVisitBooked(number int, label string) string {
	return fmt.Sprintf("Core Visit V%d (%s) scheduled successfully.", number, label)
}

func coreVisitPending(number int, label, owner string) string {
	return fmt.Sprintf("Core Visit V%d (%s) scheduled, pending %s's approval. It takes effect on your plan and enters your budget once approved.", number, label, owner)
}

func coreOutreachBooked(label string) string {
	return label + " scheduled. It is not one of the package's four visits."
}

func coreOutreachPending(label, owner string) string {
	return fmt.Sprintf("%s scheduled, pending %s's approval. It takes effect on your plan and enters your budget once approved.", label, owner)
}

func coreTrainingBooked(number int, course string) string {
	return fmt.Sprintf("Core Training T%d (%s) and its school visit scheduled successfully.", number, course)
}

func coreUniversalBooked(course string) string {
	return course + " and its school visit scheduled. It is on top of the package's four trainings."
}

func onColleaguesCorePlan(message, owner string) string {
	return fmt.Sprintf("%s It is on %s's My Plan, because they are the responsible staff member — you will find it on the Calendar.", message, owner)
}

// ScheduleCoreVisit makes the Core visit form's save, or refuses it in the
// existing words, or hands it on (ErrHandOn).
func (s *Service) ScheduleCoreVisit(ctx context.Context, p auth.Principal, req CoreVisitRequest, origin Origin) (Answer, error) {
	if s.requests == nil || !in(coreVisitRoles, p.ActiveRole) || p.InActingAppointment || p.StaffProfileID == "" {
		return Answer{}, handOn("not a role Go saves the Core visit form for")
	}
	now := s.now()
	today := dateOnly(now.In(s.kampala))
	target, err := s.coreVisitTarget(ctx, p, req, now)
	if err != nil {
		return Answer{}, err
	}
	if req.Date != "" && !isoDate.MatchString(req.Date) {
		return Answer{}, handOn("a date in another form")
	}
	day, err := time.ParseInLocation(time.DateOnly, req.Date, s.kampala)
	if err != nil {
		return Answer{}, refuse(coreDateRefusal)
	}
	purpose := req.Purpose
	if IsPairPurpose(purpose) {
		if in(rules.Doors.Requesters, p.ActiveRole) {
			return Answer{}, refuse(coreTrainingRefused)
		}
		return s.coreDoorTraining(ctx, p, req, origin, day)
	}
	if purpose == "" {
		purpose = "ssa_support"
	}
	if !in(inScopePurposes, purpose) {
		return Answer{}, handOn("a purpose Go does not take at the Core door")
	}
	if coreRouteFor(purpose) == corePackageVisit {
		return s.coreDoorPackageVisit(ctx, p, req, origin, *target, purpose, now, today, day)
	}
	return s.coreDoorOutreach(ctx, p, req, origin, *target, purpose, now, today, day)
}

// coreVisitTarget is who the visit belongs to. A named responsible person
// other than the one it would fall to is a deliberate handover: handed on.
func (s *Service) coreVisitTarget(ctx context.Context, p auth.Principal, req CoreVisitRequest, now time.Time) (*visitTarget, error) {
	var target *visitTarget
	if in(rules.Doors.Requesters, p.ActiveRole) {
		asked, err := s.requestTarget(ctx, p, req.SchoolCode, "ssa_support", now)
		if err != nil {
			return nil, err
		}
		target = asked
	} else {
		sc, owner, err := s.visitSchool(ctx, p, req.SchoolCode, "ssa_support", now)
		if err != nil {
			return nil, err
		}
		if req.Responsible != "" && req.Responsible != owner {
			return nil, handOn("a named responsible person other than the visit's owner")
		}
		target = &visitTarget{school: *sc, responsible: owner}
	}
	if !in(rules.Gate.CoreRuleTypes, target.school.Type) {
		return nil, handOn("not a Core school")
	}
	return target, nil
}

// coreDoorOutreach is _schedule_core_outreach_visit: a visit booked as itself.
// Staff SSA Support takes its package slot once it is saved.
func (s *Service) coreDoorOutreach(ctx context.Context, p auth.Principal, req CoreVisitRequest, origin Origin,
	target visitTarget, purpose string, now, today, day time.Time) (Answer, error) {
	kind := rules.Purposes.ActivityTypes[purpose]
	label := rules.Purposes.Labels[purpose]
	if label == "" {
		label = kind
	}
	it, err := resolveForKind(ctx, s.db, kind, day)
	if err != nil {
		return Answer{}, err
	}
	if it == nil {
		return Answer{}, refuse("No single approved Catalogue Activity costs “%s”. Ask the Country Director to define one costing for it before scheduling this purpose.", label)
	}
	booking, err := s.routeCoreVisit(ctx, target, purpose, day, now)
	if err != nil {
		return Answer{}, err
	}
	target.core = booking
	pl, err := s.create(ctx, p, Request{Goal: req.Goal, Outcome: req.Outcome, Justification: req.Justification},
		origin, now, today, day, target, it.ID, strings.TrimSpace(req.RecReason), purpose, kind)
	if err != nil {
		return Answer{}, err
	}
	pl.doorAudit = auditCoreOutreach
	rowID, err := s.write(ctx, pl)
	if err != nil {
		return Answer{}, err
	}
	s.afterCommit(ctx, pl, rowID)
	return s.coreDoorAnswer(ctx, pl, coreOutreachBooked(label), func(owner string) string {
		return coreOutreachPending(label, owner)
	})
}

// coreDoorPackageVisit is the form's package branch: a core_visit in the slot
// the planner chose, or the next open one.
func (s *Service) coreDoorPackageVisit(ctx context.Context, p auth.Principal, req CoreVisitRequest, origin Origin,
	target visitTarget, purpose string, now, today, day time.Time) (Answer, error) {
	number, err := coreSlotNumber(req.VisitNumber)
	if err != nil {
		return Answer{}, refuse(coreDateRefusal)
	}
	it, err := resolveForKind(ctx, s.db, coreVisitKind, day)
	if err != nil {
		return Answer{}, err
	}
	if it == nil {
		return Answer{}, refuse(noCoreVisitCosting)
	}
	fy := schooldirectory.OperationalFY(day.UTC())
	planID, err := readCorePlan(ctx, s.db, target.school.Code, fy)
	if err != nil {
		return Answer{}, err
	}
	if planID == "" {
		return Answer{}, refuse(noActivePackage)
	}
	focus, err := s.coreFollowUpFocus(ctx, p, req, target.school, now)
	if err != nil {
		return Answer{}, err
	}
	booking, err := s.routeCoreVisit(ctx, target, purpose, day, now)
	if err != nil {
		return Answer{}, err
	}
	if booking == nil {
		return Answer{}, refuse(noActivePackage)
	}
	booking.preferred = number
	target.core = booking
	pl, err := s.create(ctx, p, Request{Goal: req.Goal, Outcome: req.Outcome, Focus: focus,
		SourceActivityID: req.SourceActivityID, Justification: req.Justification},
		origin, now, today, day, target, it.ID, strings.TrimSpace(req.RecReason), purpose, coreVisitKind)
	if err != nil {
		return Answer{}, err
	}
	pl.doorAudit = auditCoreVisit
	rowID, err := s.write(ctx, pl)
	if err != nil {
		return Answer{}, err
	}
	s.afterCommit(ctx, pl, rowID)
	label := rules.Purposes.Labels[purpose]
	return s.coreDoorAnswer(ctx, pl, coreVisitBooked(pl.core.slotNumber, label), func(owner string) string {
		return coreVisitPending(pl.core.slotNumber, label, owner)
	})
}

// coreFollowUpFocus is what the form's Training Follow Up targets: the session
// it follows owns the intervention; with none, the planner's or the SSA's
// first-ranked need.
func (s *Service) coreFollowUpFocus(ctx context.Context, p auth.Principal, req CoreVisitRequest, sc school, now time.Time) (string, error) {
	fy := schooldirectory.OperationalFY(now)
	if req.SourceActivityID != "" {
		session, err := readFollowedSession(ctx, s.db, req.SourceActivityID, sc.ID)
		if err != nil {
			return "", err
		}
		if session == nil || session.problem(sc.ID, fy) != "" {
			return "", refuse(coreSourceNotEligible)
		}
		return "", nil
	}
	needs, err := followUpNeedsTraining(ctx, s.db, p.Country, fy)
	if err != nil {
		return "", err
	}
	if needs {
		return "", refuse(coreFollowUpNeeds)
	}
	if req.Focus != "" {
		return req.Focus, nil
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, sc.ID, sc.ClusterID, now)
	if err != nil {
		return "", err
	}
	if len(need.Priorities) > 0 {
		return need.Priorities[0], nil
	}
	return "", nil
}

// coreDoorTraining is _schedule_core_in_school_training: the pair, its
// training in the slot chosen, its visit credited once saved.
func (s *Service) coreDoorTraining(ctx context.Context, p auth.Principal, req CoreVisitRequest, origin Origin, day time.Time) (Answer, error) {
	number, err := coreSlotNumber(req.TrainingNumber)
	if err != nil {
		return Answer{}, refuse(coreDateRefusal)
	}
	pp, err := s.preparePair(ctx, p, Request{SchoolID: req.SchoolCode, Purpose: req.Purpose, Date: req.Date,
		Goal: req.Goal, Outcome: req.Outcome, CatalogueItemID: req.TrainingCourseID, RecReason: strings.TrimSpace(req.RecReason)}, origin)
	if err != nil {
		return Answer{}, err
	}
	if pp.corePlanID == "" && !pp.course.Universal {
		return Answer{}, refuse(noActivePackage)
	}
	if pp.corePlanID != "" {
		pp.trainingSlotAsked = number
	}
	pp.training.doorAudit = auditCoreTraining
	rowID, err := s.writePair(ctx, pp)
	if err != nil {
		return Answer{}, err
	}
	s.afterPair(ctx, pp, rowID)
	booked := coreUniversalBooked(pp.course.Name)
	if pp.corePlanID != "" {
		booked = coreTrainingBooked(pp.trainingSlotNumber, pp.course.Name)
	}
	answer, err := s.coreDoorAnswer(ctx, pp.training, booked, nil)
	if err != nil {
		return Answer{}, err
	}
	answer.PairedVisitID = pp.visit.row.id
	return answer, nil
}

// coreDoorAnswer is _core_scheduled_response, or the request's confirmation.
func (s *Service) coreDoorAnswer(ctx context.Context, pl *plan, booked string, pending func(string) string) (Answer, error) {
	answer, err := s.answer(ctx, pl)
	if err != nil {
		return Answer{}, err
	}
	switch owner := pl.row.responsible; {
	case pl.row.isRequest():
		name, err := staffName(ctx, s.db, pl.row.approvalOwner, schoolOwnerStandIn)
		if err != nil {
			return Answer{}, err
		}
		answer.Message = pending(name)
	case owner != pl.p.StaffProfileID && owner != pl.p.UserID:
		name, err := staffName(ctx, s.db, owner, schoolCCEOStandIn)
		if err != nil {
			return Answer{}, err
		}
		answer.Message, answer.PlanLinkLabel = onColleaguesCorePlan(booked, name), coreCalendarLabel
	default:
		answer.Message = booked
	}
	return answer, nil
}

// auditCoreDoor is the door's own audit row beside the activity's.
func (s *Service) auditCoreDoor(ctx context.Context, pl *plan) error {
	if pl.doorAudit == "" {
		return nil
	}
	role := pl.p.ActiveRole
	now := s.now()
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, now)
	if err != nil {
		return err
	}
	// log() stores no payload at all unless a cover stamp gave it one.
	var payload any
	if stamped := withStamps(nil, cover); len(stamped) > 0 {
		payload = stamped
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: pl.doorAudit, SubjectKind: audit.Text(activitySubject), SubjectID: audit.Text(pl.row.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: true,
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID), Payload: payload,
	}, now); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
