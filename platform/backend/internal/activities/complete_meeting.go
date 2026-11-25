package activities

// Completing an officer's own staff cluster meeting from My Plan's Complete
// drawer, with the existing application absent: my_plan_views.
// complete_activity_action, which starts the meeting if it was not started,
// and services.complete, which reserves its Training ID, mirrors the register
// into the attendance rows (_cluster_member_school_ids, _sync_cluster_attendance
// with release_absent) and hands it in to the Programme Lead. The writes go
// through one narrow function (deploy/db/completion_roles.sql
// hand_in_cluster_meeting). A meeting with a visiting school on its register,
// one done on another day than planned, and every other cluster session are
// handed on.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

const (
	clusterMeetingType      = "cluster_meeting"
	clusterTrainingType     = "cluster_training"
	trainingAttendanceAsked = "Training completion requires attendance (teachers and/or school leaders)"
	trainingFormsRefusal    = "Enter the Salesforce ID as TS-…, or the record's own Salesforce ID."
	absentReleasedAction    = "activity.absent_schools_released"
	absentReleasedReason    = "Invited, not ticked as attending at completion: back to unplanned for this training or meeting."
	attendedSchoolsField    = "attended_school_ids"
)

// salesforceTrainingForms are _TS_RE and _RECORD_ID_RE, once normalised.
var salesforceTrainingForms = []*regexp.Regexp{
	regexp.MustCompile(`^TS-[A-Z0-9-]{3,}$`),
	regexp.MustCompile(`^[A-Z0-9]{15}(?:[A-Z0-9]{3})?$`),
}

// meetingHandedOnFields take a meeting's completion out of Go's case: a
// visit's purpose, a pair's training, a school's feedback, an
// accountability, visiting schools.
var meetingHandedOnFields = []string{"training_salesforce_id", "feedback_finding", "school_improvements",
	"visiting_school_ids", "training_course_id"}

// meetingRecordTypes are the catalogue record types a meeting's ID is kept
// under as a training (sf_kind_for_activity), "" being none recorded.
var meetingRecordTypes = []string{"", "TRAINING"}

// completedSessionTypes are the cluster sessions Go completes: a meeting,
// and a group training no Core school takes a place at.
var completedSessionTypes = []string{clusterMeetingType, clusterTrainingType}

// completedMeeting is the session as its completion reads it.
type completedMeeting struct {
	id, kind, status, clusterID, responsible string
	verification, recordType, reference      string
	planned                                  *time.Time
	other                                    bool
}

func readCompletedMeeting(ctx context.Context, q Querier, id string) (*completedMeeting, error) {
	var m completedMeeting
	var responsible, verification, recordType, reference *string
	err := q.QueryRow(ctx, `
SELECT a.id, a.activity_type, a.status, a.cluster_id, a.responsible_staff_id, a.planned_date, a.ia_verification_status,
       a.salesforce_record_type_snapshot, a.salesforce_activity_id,
       (a.school_id IS NOT NULL OR a.project_id IS NOT NULL OR a.assigned_partner_id IS NOT NULL
        OR a.delivery_type IS DISTINCT FROM 'staff' OR a.paired_school_visit_id IS NOT NULL
        OR a.monitored_by_staff_id IS NOT NULL
        OR EXISTS (SELECT 1 FROM cluster_activity_attendance x WHERE x.activity_id = a.id AND x.is_guest)
        -- A meeting holding a Core training slot from before 2026-10-02 gives
        -- it back on its save (cluster_credit.credit_cluster_session).
        OR EXISTS (SELECT 1 FROM core_activity_slot cs WHERE cs.activity_id = a.id))
FROM activity a
WHERE a.id = $1 AND a.deleted_at IS NULL AND a.activity_type = ANY($2) AND a.cluster_id IS NOT NULL`,
		id, completedSessionTypes).Scan(&m.id, &m.kind, &m.status, &m.clusterID, &responsible, &m.planned, &verification,
		&recordType, &reference, &m.other)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the meeting: %w", err)
	}
	m.responsible, m.verification = text(responsible), text(verification)
	m.recordType, m.reference = text(recordType), text(reference)
	return &m, nil
}

// outOfCase says why the meeting is not Go's case ("" when it is).
func (m *completedMeeting) outOfCase(p auth.Principal) string {
	switch {
	case m.other:
		return "a meeting at a school, in a project, a pair or a partner's hands, with visiting schools or a Core slot"
	case !ownsVisit(p, m.responsible):
		return "someone else's meeting"
	case m.status != startedStatus && !in(startableStatuses, m.status):
		return "a meeting in status " + m.status
	case m.verification == confirmedVerification:
		return "a meeting IA has confirmed"
	case !in(meetingRecordTypes, strings.ToUpper(m.recordType)):
		return "a meeting kept under another Salesforce record type"
	case m.reference != "":
		return "a meeting that already holds a Salesforce ID"
	case m.planned == nil:
		return "a meeting with no planned day"
	}
	return ""
}

// meetingInCase reads the meeting and decides whether Go completes it for
// p: nil and ErrHandOn when it does not.
func (s *Service) meetingInCase(ctx context.Context, p auth.Principal, id string) (*completedMeeting, error) {
	if !officerOwn(p) {
		if !s.completesOwnVisit(p) {
			return nil, handOn("not an officer completing their own meeting")
		}
		// A lead completes their own visit in Go; their meetings are handed on.
		m, err := readCompletedMeeting(ctx, s.db, id)
		if err != nil || m == nil {
			return nil, err
		}
		return nil, handOn("a lead's own meeting")
	}
	m, err := readCompletedMeeting(ctx, s.db, id)
	if err != nil || m == nil {
		return nil, err
	}
	if why := m.outOfCase(p); why != "" {
		return nil, handOn(why)
	}
	access, err := myplan.ReadActivityAccess(ctx, s.db, p, m.id, s.now())
	if err != nil {
		return nil, err
	}
	if !access.Decided || !access.Found || !access.Visible || !access.Runnable {
		return nil, handOn("a meeting the person may not run")
	}
	ownerUID, err := fundingOwner(ctx, s.db, m.responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	why, err := moveNotices(ctx, s.db, m.id, ownerUID)
	if err != nil {
		return nil, err
	}
	if why != "" {
		return nil, handOn(why)
	}
	return m, nil
}

// completeMeeting is Complete for a cluster meeting.
func (s *Service) completeMeeting(ctx context.Context, p auth.Principal, m *completedMeeting, form url.Values, origin Origin) (CompleteAnswer, error) {
	pl := &completionPlan{
		p: p, origin: origin, now: s.now(), sessions: true,
		a: completedVisit{id: m.id, activityType: m.kind, status: m.status, responsible: m.responsible,
			plannedDate: *m.planned},
	}
	if err := s.readMeetingForm(pl, form); err != nil {
		return CompleteAnswer{}, err
	}
	if m.kind == clusterTrainingType {
		if err := s.noCoreSchoolCredited(ctx, m, pl.attended); err != nil {
			return CompleteAnswer{}, err
		}
	}
	if !sameDay(pl.delivered, pl.a.plannedDate) {
		var err error
		if pl.done, err = s.prepareDoneDay(ctx, pl, true); err != nil {
			return CompleteAnswer{}, err
		}
	}
	if err := s.writeMeetingCompletion(ctx, pl); err != nil {
		return CompleteAnswer{}, err
	}
	s.afterDoneDay(ctx, pl)
	s.afterCompletion(ctx, pl)
	return CompleteAnswer{ActivityID: m.id, Status: handedInStatus, Message: rules.Move.SavedMessage}, nil
}

// readMeetingForm is what the view and complete() read from a meeting's
// post, in their order: the completed day, the head counts, the register,
// the attendance a training needs, then the Training ID's form.
func (s *Service) readMeetingForm(pl *completionPlan, form url.Values) error {
	for _, field := range meetingHandedOnFields {
		if form.Has(field) {
			return handOn("the drawer posted " + field)
		}
	}
	if pyStrip(form.Get("netsuite_id")) != "" || pyStrip(form.Get("purpose_type")) != "" {
		return handOn("an accountability, or a purpose given at completion")
	}
	delivered, err := s.completedOn(form.Get("actual_delivery_date"))
	if err != nil {
		return err
	}
	if !sameDay(delivered, pl.a.plannedDate) && !pl.sessions {
		return handOn("done on another day than planned: the work and its money move")
	}
	pl.delivered = delivered
	counts := make([]int, 0, 3)
	for _, field := range []string{"teachers_attended", "leaders_attended", "other_participants"} {
		n, err := attendance(form, field)
		if err != nil {
			return err
		}
		counts = append(counts, n)
	}
	if counts[2] != 0 {
		return handOn("other participants posted on a meeting")
	}
	pl.teachers, pl.leaders = counts[0], counts[1]
	pl.posted = form[attendedSchoolsField]
	pl.attended = postedIDs(pl.posted)
	pl.outcome, pl.observations, pl.notes = posted(form, "actual_outcome"), posted(form, "actual_observations"),
		posted(form, "follow_up_note")
	pl.raw = pyStrip(form.Get("salesforce_id"))
	pl.payload = completionPayload(pl, form)
	pl.payload["attendedSchoolIds"] = anyStrings(pl.posted)
	pl.payload["visitingSchoolIds"] = []any{}
	if pl.teachers <= 0 && pl.leaders <= 0 {
		return refuse("%s", trainingAttendanceAsked)
	}
	return s.judgeTrainingID(pl)
}

// postedIDs is the register as _cluster_member_school_ids first reads it:
// each id stripped, empty ones dropped, each kept once in its first place.
func postedIDs(values []string) []string {
	ids := []string{}
	for _, value := range values {
		if id := pyStrip(value); id != "" && !slices.Contains(ids, id) {
			ids = append(ids, id)
		}
	}
	return ids
}

func anyStrings(values []string) []any {
	out := make([]any, 0, len(values))
	for _, value := range values {
		out = append(out, value)
	}
	return out
}

// judgeTrainingID is normalize_salesforce_id and is_valid_new_entry for a
// training.
func (s *Service) judgeTrainingID(pl *completionPlan) error {
	if len(pl.raw) > maxSalesforceRaw {
		return handOn("a Salesforce ID longer than its reference keeps")
	}
	normalized, ok := normalizeSalesforceID(pl.raw)
	if !ok {
		return handOn("a Salesforce ID outside ASCII")
	}
	if !slices.ContainsFunc(salesforceTrainingForms, func(form *regexp.Regexp) bool { return form.MatchString(normalized) }) {
		return refuse("%s", trainingFormsRefusal)
	}
	pl.normalized = normalized
	return nil
}

// writeMeetingCompletion is the start, the reservation, the register and the
// hand-in in one transaction, with the reservation's audit row and, when
// invitations were removed, the release's.
func (s *Service) writeMeetingCompletion(ctx context.Context, pl *completionPlan) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the meeting's completion: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	var released []string
	err = tx.QueryRow(ctx, `SELECT answer, released FROM gateway_completion.hand_in_cluster_meeting($1, $2, $3, $4,
  $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)`,
		pl.a.id, pl.delivered, pl.raw, pl.normalized, pl.teachers, pl.leaders, pl.attended,
		pl.outcome, pl.observations, pl.notes, pl.p.UserID, pl.now, cuid.New(), cuid.New()).Scan(&answer, &released)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
		return refuse("%s", salesforceTakenRefusal)
	}
	if err != nil {
		return fmt.Errorf("activities: handing the meeting in: %w", err)
	}
	if holder, held := strings.CutPrefix(answer, "held:"); held {
		message, err := takenBy(ctx, tx, holder)
		if err != nil {
			return err
		}
		return refuse("%s", message)
	}
	if answer != "" {
		return handOn("the meeting's hand-in met " + answer)
	}
	if err := s.appendSalesforceRow(ctx, tx, pl); err != nil {
		return err
	}
	if len(released) > 0 {
		if err := s.appendReleasedRow(ctx, tx, pl, released); err != nil {
			return err
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the meeting's completion: %w", err)
	}
	return nil
}

// appendReleasedRow is complete()'s `activity.absent_schools_released` row.
func (s *Service) appendReleasedRow(ctx context.Context, tx pgx.Tx, pl *completionPlan, released []string) error {
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, s.now())
	if err != nil {
		return err
	}
	role := pl.p.ActiveRole
	reason := absentReleasedReason
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: absentReleasedAction, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(pl.a.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: true, Reason: &reason,
		Payload:   withStamps(map[string]any{"schoolIds": anyStrings(released)}, cover),
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now()); err != nil {
		return fmt.Errorf("activities: writing the release's audit row: %w", err)
	}
	return nil
}

// noCoreSchoolCredited hands on a group training whose register would give
// a Core school a training slot (cluster_credit.credit_cluster_session, run
// on the session's save): a Core member invited to it or ticked as attending.
// Go's group training refuses to invite one, so only an older session meets it.
func (s *Service) noCoreSchoolCredited(ctx context.Context, m *completedMeeting, attended []string) error {
	var core bool
	if err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM school s WHERE s.cluster_id = $1 AND s.deleted_at IS NULL AND s.school_type = $2
  AND (s.id = ANY($3) OR EXISTS (SELECT 1 FROM cluster_activity_attendance x
                                  WHERE x.activity_id = $4 AND x.school_id = s.id AND x.invited)))`,
		m.clusterID, coreSchoolType, attended, m.id).Scan(&core); err != nil {
		return fmt.Errorf("activities: reading the training's Core schools: %w", err)
	}
	if core {
		return handOn("a group training a Core school takes a place at")
	}
	return nil
}
