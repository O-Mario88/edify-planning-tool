package activities

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Attendance (my_plan_views.attendance_upload_action and
// services.record_attendance) for an officer's own staff work at a school:
// the head count is kept and work not yet started is started, without
// completing it. A cluster session's register is handed on.

var (
	// attendanceClosedStatuses are record_attendance's closed_statuses.
	attendanceClosedStatuses = []string{"closed", "cancelled", "rejected", "deferred"}
	// attendanceTypes are the staff work at one school Go takes attendance for.
	attendanceTypes = []string{
		"school_visit", "donor_visit", "story_gathering_visit", "school_invitation", "social_visit",
		"in_school_training", "training", "school_improvement_training",
	}
	// attendanceFields are the drawer's own fields Go takes.
	attendanceFields = []string{"csrfmiddlewaretoken", "teachers_attended", "leaders_attended", "notes"}
	// pyIntForm is what Python's int() reads without underscores: a sign and
	// ASCII digits.
	pyIntForm = regexp.MustCompile(`^[+-]?[0-9]+$`)
)

const (
	attendanceClosedMessage = "Attendance cannot be changed after this activity is closed."
	maxCountDigits          = 9
)

func attendanceClosed(status string) bool { return slices.Contains(attendanceClosedStatuses, status) }

// attendanceCountOf is record_attendance's count(): int(raw or 0), refused
// when it is not a whole number or is negative. A form Python reads that Go
// does not (an underscore, a huge number) is handed on.
func attendanceCountOf(name, raw string) (int, error) {
	value := pyStrip(raw)
	if raw == "" {
		return 0, nil
	}
	if strings.Contains(value, "_") || len(strings.TrimLeft(value, "+-")) > maxCountDigits {
		return 0, handOn(name + " in another form")
	}
	if !pyIntForm.MatchString(value) {
		return 0, refuse("%s must be a whole number.", name)
	}
	n, err := strconv.Atoi(value)
	if err != nil {
		return 0, handOn(name + " in another form")
	}
	if n < 0 {
		return 0, refuse("%s cannot be negative.", name)
	}
	return n, nil
}

// attendanceAuditPayload is the view's audit payload: the counts as posted
// (request.POST.get(name, 0)) and the stripped notes.
func attendanceAuditPayload(form url.Values) map[string]any {
	posted := func(name string) any {
		if values, ok := form[name]; ok && len(values) > 0 {
			return values[len(values)-1]
		}
		return 0
	}
	return map[string]any{"teachers": posted("teachers_attended"), "leaders": posted("leaders_attended"),
		"notes": pyStrip(form.Get("notes"))}
}

// attendanceTarget is the work attendance is recorded on.
type attendanceTarget struct {
	id, activityType, status, schoolID, responsible string
	other                                           bool
	plannedDate                                     *time.Time
}

func readAttendanceTarget(ctx context.Context, q Querier, id string) (*attendanceTarget, error) {
	var a attendanceTarget
	var school, responsible *string
	err := q.QueryRow(ctx, `SELECT a.id, a.activity_type, a.status, a.school_id, a.responsible_staff_id, a.planned_date,
       (a.cluster_id IS NOT NULL OR a.project_id IS NOT NULL OR a.assigned_partner_id IS NOT NULL
        OR a.delivery_type IS DISTINCT FROM 'staff' OR a.monitored_by_staff_id IS NOT NULL)
  FROM activity a WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(&a.id, &a.activityType, &a.status, &school, &responsible, &a.plannedDate, &a.other)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the work: %w", err)
	}
	if school == nil || !slices.Contains(attendanceTypes, a.activityType) {
		return nil, nil
	}
	a.schoolID, a.responsible = *school, text(responsible)
	return &a, nil
}

// RecordAttendance keeps the head count, or refuses it in the existing
// words, or hands it on (ErrHandOn).
func (s *Service) RecordAttendance(ctx context.Context, p auth.Principal, activityID string, form url.Values, origin Origin) (Answer, error) {
	for name, values := range form {
		if !slices.Contains(attendanceFields, name) && slices.ContainsFunc(values, func(v string) bool { return strings.TrimSpace(v) != "" }) {
			return Answer{}, handOn("the drawer posted " + name)
		}
	}
	if p.InActingAppointment || p.StaffProfileID == "" || p.ActiveRole != officerRole || slices.Contains(p.Roles, programmeLeadRole) {
		return Answer{}, handOn("not an officer recording their own work's attendance")
	}
	a, err := readAttendanceTarget(ctx, s.db, strings.TrimSpace(activityID))
	if err != nil {
		return Answer{}, err
	}
	switch {
	case a == nil:
		return Answer{}, handOn("not staff work at one school")
	case a.other:
		return Answer{}, handOn("work in a cluster, a project or a partner's hands")
	case !ownsVisit(p, a.responsible):
		return Answer{}, handOn("someone else's work")
	}
	now := s.now()
	if err := s.ownVisitSchool(ctx, p, a.schoolID, now); err != nil {
		return Answer{}, err
	}
	if attendanceClosed(a.status) {
		return Answer{}, refuse(attendanceClosedMessage)
	}
	teachers, err := attendanceCountOf("teachersAttended", form.Get("teachers_attended"))
	if err != nil {
		return Answer{}, err
	}
	leaders, err := attendanceCountOf("leadersAttended", form.Get("leaders_attended"))
	if err != nil {
		return Answer{}, err
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return Answer{}, fmt.Errorf("activities: opening the attendance: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	if err := tx.QueryRow(ctx, `SELECT gateway_completion.record_attendance($1, $2, $3, $4)`, a.id, teachers, leaders, now).Scan(&answer); err != nil {
		return Answer{}, fmt.Errorf("activities: recording the attendance: %w", err)
	}
	switch answer {
	case "":
	case "closed":
		return Answer{}, refuse(attendanceClosedMessage)
	default:
		return Answer{}, handOn("the attendance met " + answer)
	}
	if err := tx.Commit(ctx); err != nil {
		return Answer{}, fmt.Errorf("activities: committing the attendance: %w", err)
	}
	if err := s.auditAttendance(ctx, p, a.id, attendanceAuditPayload(form), origin); err != nil {
		s.logger.Warn("activities: the attendance's audit row was not written", "activity", a.id, "err", err)
	}
	// The activity's save marks its owner's target ledger for the year.
	if in(rules.LedgerCreditedTypes, a.activityType) && a.plannedDate != nil {
		if err := s.markOwnerYears(ctx, a.responsible, *a.plannedDate); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", a.id, "err", err)
		}
	}
	return Answer{ActivityID: a.id, Message: rules.Move.SavedMessage}, nil
}

func (s *Service) auditAttendance(ctx context.Context, p auth.Principal, activityID string, payload map[string]any, origin Origin) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, p.UserID, s.now())
	if err != nil {
		return err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "upload_attendance", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(activityID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Reason:    audit.Text("Attendance file and headcount uploaded"),
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
		Payload: withStamps(payload, cover),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
