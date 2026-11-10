package clusterlead

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// histories names each append-only history and the column that keys it; a
// history is read or added to only through this list.
var histories = map[string]string{
	"plan_event":        "plan_id",
	"invitation_event":  "invitation_id",
	"action_item_event": "action_item_id",
}

func historyKey(table, key string) error {
	if histories[table] != key {
		return fmt.Errorf("clusterlead: %q is not a history", table)
	}
	return nil
}

// The portal's operations records (migration 0002) and the existing records
// they hang on. Every write runs in Store.inWrite; nothing is deleted.

// deliveredStatuses is work delivered, awaiting or past verification
// (apps/planning/school_planning_badges.py AWAITING_VERIFICATION + VERIFIED).
var deliveredStatuses = []string{
	"evidence_uploaded", "evidence_accepted", "salesforce_id_required", "submitted_to_pl",
	"awaiting_ia_verification", "completed", "ia_verified", "accountant_confirmed", "closed",
}

// ActivityRecord is one existing activity of a cluster, as operations need it.
type ActivityRecord struct {
	Activity
	ClusterID        string
	TrainingCourseID string
	// The official attendance staff recorded at completion.
	AttendedSchoolIDs []string
}

// Plan is a leader's meeting proposal.
type Plan struct {
	ID, ClusterID, Category, Title, TrainingCourseID, TrainingCourse string
	PlannedOn                                                         time.Time
	StartsAt, Venue                                                   string
	IsOnline                                                          bool
	Objectives, Agenda                                                string
	ExpectedParticipants                                              int32
	Facilitator, Resources, Notes, Status, ActivityID, ReviewNote     string
	CreatedBy                                                         string
	History                                                           []Event
}

// Course is a governed training course a cluster may receive.
type Course struct {
	ID, Name, Category, Intervention string
}

// Invitation is one school's invitation to one activity.
type Invitation struct {
	ID, ClusterID, ActivityID, SchoolID, Status, Channel, DeliveryStatus, ResponseNote string
	InvitedAt                                                                          time.Time
	RespondedAt                                                                        *time.Time
	FollowUps                                                                          int32
}

// AttendanceRecord is the leader's record of one school at one activity.
type AttendanceRecord struct {
	SchoolID     string
	Attended     bool
	Participants int32
}

// MinutesRecord is a meeting's minutes.
type MinutesRecord struct {
	Discussion, Decisions, Status string
	SubmittedAt                   *time.Time
}

// Item is one action item.
type Item struct {
	ID, ClusterID, ActivityID, Title, OwnerSchoolID, Owner, Status string
	DueOn                                                          *time.Time
	History                                                        []Event
}

// Request is a leader's request or concern to staff.
type Request struct {
	ID, ClusterID, Subject, Body, Status, AskedBy, Answer, AnsweredBy string
	AskedAt                                                           time.Time
	AnsweredAt                                                        *time.Time
}

// ActivityFor is the existing activity id, ErrNotFound unless it is a live
// record of some cluster.
func (s *Store) ActivityFor(ctx context.Context, id string) (ActivityRecord, error) {
	var a ActivityRecord
	err := s.db.QueryRow(ctx, `
SELECT a.id, COALESCE(a.activity_name_snapshot, ''), COALESCE(a.meeting_kind, ''), a.status,
       COALESCE((a.scheduled_date AT TIME ZONE $2)::date, a.planned_date), COALESCE(a.venue, ''),
       COALESCE(a.schools_invited, 0), COALESCE(cardinality(a.attended_school_ids), 0),
       COALESCE(a.cluster_id, ''), COALESCE(a.training_course_id, ''),
       COALESCE(a.attended_school_ids, '{}')
FROM activity a
WHERE a.id = $1 AND a.deleted_at IS NULL AND a.cluster_id IS NOT NULL`, id, zoneName).Scan(
		&a.ID, &a.Name, &a.Kind, &a.Status, &a.Date, &a.Venue, &a.Invited, &a.Attended,
		&a.ClusterID, &a.TrainingCourseID, &a.AttendedSchoolIDs)
	if errors.Is(err, pgx.ErrNoRows) {
		return ActivityRecord{}, ErrNotFound
	}
	if err != nil {
		return ActivityRecord{}, fmt.Errorf("clusterlead: reading an activity: %w", err)
	}
	return a, nil
}

const selectPlan = `
SELECT p.id::text, p.cluster_id, p.category, p.title, COALESCE(p.training_course_id, ''),
       COALESCE(c.display_name, ''), p.planned_on, p.starts_at, p.venue, p.is_online,
       p.objectives, p.agenda, p.expected_participants, p.facilitator, p.resources, p.notes,
       p.status, COALESCE(p.activity_id, ''), p.review_note, p.created_by
FROM cluster_leadership.meeting_plan p
LEFT JOIN activity_catalogue_item c ON c.id = p.training_course_id`

func scanPlan(row pgx.CollectableRow) (Plan, error) {
	var p Plan
	err := row.Scan(&p.ID, &p.ClusterID, &p.Category, &p.Title, &p.TrainingCourseID, &p.TrainingCourse,
		&p.PlannedOn, &p.StartsAt, &p.Venue, &p.IsOnline, &p.Objectives, &p.Agenda,
		&p.ExpectedParticipants, &p.Facilitator, &p.Resources, &p.Notes, &p.Status,
		&p.ActivityID, &p.ReviewNote, &p.CreatedBy)
	return p, err
}

// Plans is the cluster's plans with their history, newest first.
func (s *Store) Plans(ctx context.Context, clusterID string) ([]Plan, error) {
	rows, err := s.db.Query(ctx, selectPlan+` WHERE p.cluster_id = $1 ORDER BY p.created_at DESC, p.id`, clusterID)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading plans: %w", err)
	}
	plans, err := pgx.CollectRows(rows, scanPlan)
	if err != nil {
		return nil, err
	}
	for i := range plans {
		if plans[i].History, err = s.history(ctx, "plan_event", "plan_id", plans[i].ID); err != nil {
			return nil, err
		}
	}
	return plans, nil
}

// Plan is one plan with its history.
func (s *Store) Plan(ctx context.Context, id string) (Plan, error) {
	rows, err := s.db.Query(ctx, selectPlan+` WHERE p.id::text = $1`, id)
	if err != nil {
		return Plan{}, fmt.Errorf("clusterlead: reading a plan: %w", err)
	}
	plan, err := pgx.CollectOneRow(rows, scanPlan)
	if errors.Is(err, pgx.ErrNoRows) {
		return Plan{}, ErrNotFound
	}
	if err != nil {
		return Plan{}, err
	}
	plan.History, err = s.history(ctx, "plan_event", "plan_id", id)
	return plan, err
}

// history reads an append-only event table. table and key are constants of
// this package, never caller input.
func (s *Store) history(ctx context.Context, table, key, id string) ([]Event, error) {
	if err := historyKey(table, key); err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `
SELECT e.event, COALESCE(u.name, ''), e.note, e.at
FROM cluster_leadership.`+table+` e
LEFT JOIN "user" u ON u.id = e.actor_id
WHERE e.`+key+`::text = $1
ORDER BY e.at, e.id`, id)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading history: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (Event, error) {
		var e Event
		return e, row.Scan(&e.Event, &e.Actor, &e.Reason, &e.At)
	})
}

// Courses is every active governed course a cluster may receive.
func (s *Store) Courses(ctx context.Context) ([]Course, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, display_name, COALESCE(training_category, ''), COALESCE(ssa_indicator_label, '')
FROM activity_catalogue_item
WHERE is_training_course AND status = 'active' AND cluster_delivery_allowed
ORDER BY display_name, id`)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading courses: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (Course, error) {
		var c Course
		return c, row.Scan(&c.ID, &c.Name, &c.Category, &c.Intervention)
	})
}

// SavePlan writes p as a new or edited plan with its event.
func (s *Store) SavePlan(ctx context.Context, p Plan, isNew bool, actorID, event string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		course := nullable(p.TrainingCourseID)
		var err error
		if isNew {
			_, err = tx.Exec(ctx, `
INSERT INTO cluster_leadership.meeting_plan
  (id, cluster_id, category, title, training_course_id, planned_on, starts_at, venue, is_online,
   objectives, agenda, expected_participants, facilitator, resources, notes, status, created_by, submitted_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
        CASE WHEN $16 = 'submitted' THEN now() END)`,
				p.ID, p.ClusterID, p.Category, p.Title, course, p.PlannedOn, p.StartsAt, p.Venue, p.IsOnline,
				p.Objectives, p.Agenda, p.ExpectedParticipants, p.Facilitator, p.Resources, p.Notes, p.Status, actorID)
		} else {
			var tag pgconn.CommandTag
			tag, err = tx.Exec(ctx, `
UPDATE cluster_leadership.meeting_plan SET
  category = $2, title = $3, training_course_id = $4, planned_on = $5, starts_at = $6, venue = $7,
  is_online = $8, objectives = $9, agenda = $10, expected_participants = $11, facilitator = $12,
  resources = $13, notes = $14, status = $15, updated_at = now(),
  submitted_at = CASE WHEN $15 = 'submitted' THEN now() ELSE submitted_at END
WHERE id::text = $1 AND status IN ('draft', 'returned')`,
				p.ID, p.Category, p.Title, course, p.PlannedOn, p.StartsAt, p.Venue, p.IsOnline,
				p.Objectives, p.Agenda, p.ExpectedParticipants, p.Facilitator, p.Resources, p.Notes, p.Status)
			if err == nil && tag.RowsAffected() == 0 {
				return ErrNotLive
			}
		}
		if err != nil {
			return fmt.Errorf("clusterlead: saving a plan: %w", err)
		}
		return appendTo(ctx, tx, "plan_event", "plan_id", p.ID, event, actorID, "")
	})
}

// MovePlan moves a plan from one of from to status, recording event; for a
// "scheduled" move, activityID is the official activity it is linked to.
func (s *Store) MovePlan(ctx context.Context, id string, from []string, status, event, actorID, note, activityID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.meeting_plan SET
  status = $3, updated_at = now(),
  review_note = CASE WHEN $3 IN ('approved', 'returned') THEN $5 ELSE review_note END,
  reviewed_by = CASE WHEN $3 IN ('approved', 'returned') THEN $4 ELSE reviewed_by END,
  reviewed_at = CASE WHEN $3 IN ('approved', 'returned') THEN now() ELSE reviewed_at END,
  activity_id = CASE WHEN $3 = 'scheduled' THEN $6 ELSE activity_id END
WHERE id::text = $1 AND status = ANY($2)`, id, from, status, actorID, note, nullable(activityID))
		if isUniqueViolation(err) {
			return ErrAlreadyAssigned
		}
		if err != nil {
			return fmt.Errorf("clusterlead: moving a plan: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrNotLive
		}
		return appendTo(ctx, tx, "plan_event", "plan_id", id, event, actorID, note)
	})
}

// Invitations is every invitation to an activity.
func (s *Store) Invitations(ctx context.Context, activityID string) ([]Invitation, error) {
	rows, err := s.db.Query(ctx, selectInvitation+` WHERE i.activity_id = $1`, activityID)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading invitations: %w", err)
	}
	return pgx.CollectRows(rows, scanInvitation)
}

// Invitation is one invitation.
func (s *Store) Invitation(ctx context.Context, id string) (Invitation, error) {
	rows, err := s.db.Query(ctx, selectInvitation+` WHERE i.id::text = $1`, id)
	if err != nil {
		return Invitation{}, fmt.Errorf("clusterlead: reading an invitation: %w", err)
	}
	invitation, err := pgx.CollectOneRow(rows, scanInvitation)
	if errors.Is(err, pgx.ErrNoRows) {
		return Invitation{}, ErrNotFound
	}
	return invitation, err
}

const selectInvitation = `
SELECT i.id::text, i.cluster_id, i.activity_id, i.school_id, i.status, i.channel, i.delivery_status,
       i.response_note, i.invited_at, i.responded_at, i.follow_up_count
FROM cluster_leadership.invitation i`

func scanInvitation(row pgx.CollectableRow) (Invitation, error) {
	var i Invitation
	err := row.Scan(&i.ID, &i.ClusterID, &i.ActivityID, &i.SchoolID, &i.Status, &i.Channel,
		&i.DeliveryStatus, &i.ResponseNote, &i.InvitedAt, &i.RespondedAt, &i.FollowUps)
	return i, err
}

// Invite records an invitation for each school not yet invited; the ids
// are new invitation ids, one per school, in order.
func (s *Store) Invite(ctx context.Context, clusterID, activityID string, schoolIDs, ids []string, channel, actorID string) (int, error) {
	invited := 0
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		for index, schoolID := range schoolIDs {
			tag, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.invitation (id, cluster_id, activity_id, school_id, status, channel, invited_by)
VALUES ($1, $2, $3, $4, 'invited', $5, $6)
ON CONFLICT (activity_id, school_id) DO NOTHING`, ids[index], clusterID, activityID, schoolID, channel, actorID)
			if err != nil {
				return fmt.Errorf("clusterlead: inviting a school: %w", err)
			}
			if tag.RowsAffected() == 1 {
				invited++
				if err := appendTo(ctx, tx, "invitation_event", "invitation_id", ids[index], "invited", actorID, channel); err != nil {
					return err
				}
			}
		}
		return nil
	})
	return invited, err
}

// RespondInvitation records what the school answered.
func (s *Store) RespondInvitation(ctx context.Context, id, status, note, actorID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE cluster_leadership.invitation SET status = $2, response_note = $3, responded_at = now()
WHERE id::text = $1`, id, status, note); err != nil {
			return fmt.Errorf("clusterlead: recording an answer: %w", err)
		}
		return appendTo(ctx, tx, "invitation_event", "invitation_id", id, status, actorID, note)
	})
}

// FollowUpInvitation counts one more follow-up.
func (s *Store) FollowUpInvitation(ctx context.Context, id, note, actorID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE cluster_leadership.invitation SET follow_up_count = follow_up_count + 1, last_follow_up_at = now()
WHERE id::text = $1`, id); err != nil {
			return fmt.Errorf("clusterlead: recording a follow-up: %w", err)
		}
		return appendTo(ctx, tx, "invitation_event", "invitation_id", id, "followed_up", actorID, note)
	})
}

// Attendance is the leader's attendance record for an activity.
func (s *Store) Attendance(ctx context.Context, activityID string) ([]AttendanceRecord, error) {
	rows, err := s.db.Query(ctx, `
SELECT school_id, attended, participants FROM cluster_leadership.attendance_record
WHERE activity_id = $1`, activityID)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading attendance: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (AttendanceRecord, error) {
		var r AttendanceRecord
		return r, row.Scan(&r.SchoolID, &r.Attended, &r.Participants)
	})
}

// RecordAttendance writes the leader's attendance for each entry; the ids
// are new record ids, one per entry, used when the school has none yet.
func (s *Store) RecordAttendance(ctx context.Context, clusterID, activityID string, entries []AttendanceRecord, ids []string, actorID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		for index, entry := range entries {
			if _, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.attendance_record
  (id, cluster_id, activity_id, school_id, attended, participants, recorded_by)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (activity_id, school_id) DO UPDATE
SET attended = EXCLUDED.attended, participants = EXCLUDED.participants,
    recorded_by = EXCLUDED.recorded_by, recorded_at = now()`,
				ids[index], clusterID, activityID, entry.SchoolID, entry.Attended, entry.Participants, actorID); err != nil {
				return fmt.Errorf("clusterlead: recording attendance: %w", err)
			}
		}
		return nil
	})
}

// MinutesOf is the activity's minutes, nil when none are written.
func (s *Store) MinutesOf(ctx context.Context, activityID string) (*MinutesRecord, error) {
	var m MinutesRecord
	err := s.db.QueryRow(ctx, `
SELECT discussion, decisions, status, submitted_at FROM cluster_leadership.meeting_minutes
WHERE activity_id = $1`, activityID).Scan(&m.Discussion, &m.Decisions, &m.Status, &m.SubmittedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading minutes: %w", err)
	}
	return &m, nil
}

// SaveMinutes writes the activity's minutes unless they are submitted.
func (s *Store) SaveMinutes(ctx context.Context, id, clusterID, activityID, discussion, decisions string, submit bool, actorID string) error {
	status := "draft"
	if submit {
		status = "submitted"
	}
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.meeting_minutes
  (id, cluster_id, activity_id, discussion, decisions, status, written_by, submitted_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, CASE WHEN $6 = 'submitted' THEN now() END)
ON CONFLICT (activity_id) DO UPDATE
SET discussion = EXCLUDED.discussion, decisions = EXCLUDED.decisions, status = EXCLUDED.status,
    written_by = EXCLUDED.written_by, updated_at = now(), submitted_at = EXCLUDED.submitted_at
WHERE cluster_leadership.meeting_minutes.status = 'draft'`,
			id, clusterID, activityID, discussion, decisions, status, actorID)
		if err != nil {
			return fmt.Errorf("clusterlead: saving minutes: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrNotLive
		}
		return nil
	})
}

func nullable(value string) any {
	if value == "" {
		return nil
	}
	return value
}

// appendTo adds an event to one of the append-only histories. table and
// key are constants of this package, never caller input.
func appendTo(ctx context.Context, tx pgx.Tx, table, key, id, event, actorID, note string) error {
	if err := historyKey(table, key); err != nil {
		return err
	}
	_, err := tx.Exec(ctx, `INSERT INTO cluster_leadership.`+table+` (`+key+`, event, actor_id, note)
VALUES ($1, $2, $3, $4)`, id, event, actorID, note)
	if err != nil {
		return fmt.Errorf("clusterlead: recording what changed: %w", err)
	}
	return nil
}
