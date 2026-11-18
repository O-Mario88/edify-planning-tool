package clusterlead

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// The Cluster Action Register's records (migration 0004). Every write runs in
// Store.inWrite with its event appended in the same transaction; nothing is
// deleted. The official activity is only ever read.

// ErrStale: the action or school changed since the caller read it.
var ErrStale = errors.New("clusterlead: changed meanwhile")

// ActionRecord is one action as stored.
type ActionRecord struct {
	ID, Ref, ClusterID, ClusterName               string
	Source, SourceActivityID, SourcePlanID        string
	SupportKind, TrainingCourseID, TrainingCourse string
	Title, Description, ExpectedOutcome, Priority string
	TargetOn                                      time.Time
	SchoolIDs                                     []string
	FiscalYear                                    int32
	Status, CloseSummary                          string
	Version                                       int32
	CreatedBy, CreatedByName                      string
	CreatedAt, UpdatedAt                          time.Time
	SubmittedAt, ClosedAt                         *time.Time
	SourceMeeting                                 string
	Schools                                       []ActionSchoolRecord
	LatestEvent                                   string
	LatestEventAt                                 *time.Time
}

// ActionSchoolRecord is one school of a sent action, with its linked
// official activity as it stands now.
type ActionSchoolRecord struct {
	ID, SchoolID, EdifySchoolID, Name        string
	ResponsibleStaffID, ResponsibleStaff     string
	ResponsibleUserID                        string
	SupervisorStaffID, SupervisorUserID      string
	RoutedTo, Status, Note                   string
	ActivityID, ActivityName, ActivityStatus string
	ActivityDate                             *time.Time
	ReminderAt, EscalatedAt                  *time.Time
	UpdatedAt                                time.Time
}

// Route is where a school's request goes when the action is sent.
type Route struct {
	ResponsibleStaffID, SupervisorStaffID, RoutedTo string
}

// ActionEventRecord is one entry of an action's history.
type ActionEventRecord struct {
	Event, Actor, ActorRole, School, FromStatus, ToStatus, Note string
	At                                                          time.Time
}

// ReviewRecord is a meeting's review of an action.
type ReviewRecord struct {
	ID, Meeting, Progress, Challenges, NextStep, Outcome, By string
	At                                                       time.Time
}

// EscalationRecord is an escalation of an action.
type EscalationRecord struct {
	ID, SchoolID, Reason, RaisedBy, ToStaffID, ToStaff, ToUserID, Status, Resolution string
	At                                                                               time.Time
}

// NoticeRecord is a notice to a person, delivered by the relay worker.
type NoticeRecord struct {
	ID, ActionID, RecipientUserID, Event, Title, Body, TargetRoute, SenderUserID, DedupKey string
	Attempts                                                                               int32
}

// ActionWrite is one change in a transaction: its event, and its notices.
type ActionWrite struct {
	ActorID, ActorRole string
	Events             []ActionEventRecord
	Notices            []NoticeRecord
}

const selectAction = `
SELECT a.id::text, a.ref, a.cluster_id, COALESCE(c.name, ''), a.source, COALESCE(a.source_activity_id, ''),
       COALESCE(a.source_plan_id::text, ''), a.support_kind, COALESCE(a.training_course_id, ''),
       COALESCE(ci.display_name, ''), a.title, a.description, a.expected_outcome, a.priority, a.target_on,
       a.school_ids, a.fiscal_year, a.status, a.close_summary, a.version, a.created_by, COALESCE(u.name, ''),
       a.created_at, a.updated_at, a.submitted_at, a.closed_at,
       COALESCE(sa.activity_name_snapshot, mp.title, ''),
       COALESCE(le.event, ''), le.at
FROM cluster_leadership.cluster_action a
LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.training_course_id
LEFT JOIN "user" u ON u.id = a.created_by
LEFT JOIN activity sa ON sa.id = a.source_activity_id
LEFT JOIN cluster_leadership.meeting_plan mp ON mp.id = a.source_plan_id
LEFT JOIN LATERAL (
  SELECT e.event, e.at FROM cluster_leadership.cluster_action_event e
  WHERE e.action_id = a.id ORDER BY e.at DESC, e.id DESC LIMIT 1) le ON true`

func scanAction(row pgx.CollectableRow) (ActionRecord, error) {
	var a ActionRecord
	err := row.Scan(&a.ID, &a.Ref, &a.ClusterID, &a.ClusterName, &a.Source, &a.SourceActivityID, &a.SourcePlanID,
		&a.SupportKind, &a.TrainingCourseID, &a.TrainingCourse, &a.Title, &a.Description, &a.ExpectedOutcome,
		&a.Priority, &a.TargetOn, &a.SchoolIDs, &a.FiscalYear, &a.Status, &a.CloseSummary, &a.Version, &a.CreatedBy,
		&a.CreatedByName, &a.CreatedAt, &a.UpdatedAt, &a.SubmittedAt, &a.ClosedAt, &a.SourceMeeting,
		&a.LatestEvent, &a.LatestEventAt)
	return a, err
}

const selectActionSchool = `
SELECT s.id::text, s.school_id, COALESCE(sc.school_id, ''), COALESCE(sc.name, ''),
       COALESCE(s.responsible_staff_id, ''), COALESCE(ru.name, ''), COALESCE(rsp.user_id, ''),
       COALESCE(s.supervisor_staff_id, ''), COALESCE(ssp.user_id, ''),
       COALESCE(s.routed_to, ''), s.status, s.status_note,
       COALESCE(s.activity_id, ''), COALESCE(act.activity_name_snapshot, ''), COALESCE(act.status, ''),
       COALESCE((act.scheduled_date AT TIME ZONE 'Africa/Kampala')::date, act.planned_date),
       s.reminded_at, s.escalated_at, s.updated_at, s.action_id::text
FROM cluster_leadership.cluster_action_school s
LEFT JOIN school sc ON sc.id = s.school_id
LEFT JOIN staff_profile rsp ON rsp.id = s.responsible_staff_id
LEFT JOIN "user" ru ON ru.id = rsp.user_id
LEFT JOIN staff_profile ssp ON ssp.id = s.supervisor_staff_id
LEFT JOIN activity act ON act.id = s.activity_id AND act.deleted_at IS NULL`

type schoolRow struct {
	ActionSchoolRecord
	actionID string
}

func scanActionSchool(row pgx.CollectableRow) (schoolRow, error) {
	var r schoolRow
	err := row.Scan(&r.ID, &r.SchoolID, &r.EdifySchoolID, &r.Name, &r.ResponsibleStaffID, &r.ResponsibleStaff,
		&r.ResponsibleUserID, &r.SupervisorStaffID, &r.SupervisorUserID, &r.RoutedTo, &r.Status, &r.Note,
		&r.ActivityID, &r.ActivityName, &r.ActivityStatus, &r.ActivityDate, &r.ReminderAt, &r.EscalatedAt,
		&r.UpdatedAt, &r.actionID)
	return r, err
}

// withSchools fills each action's schools in one query.
func (s *Store) withSchools(ctx context.Context, actions []ActionRecord) ([]ActionRecord, error) {
	if len(actions) == 0 {
		return actions, nil
	}
	ids := make([]string, len(actions))
	index := map[string]int{}
	for i, a := range actions {
		ids[i], index[a.ID] = a.ID, i
	}
	rows, err := s.db.Query(ctx, selectActionSchool+` WHERE s.action_id::text = ANY($1) ORDER BY sc.name, s.school_id`, ids)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading action schools: %w", err)
	}
	schools, err := pgx.CollectRows(rows, scanActionSchool)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading action schools: %w", err)
	}
	for _, r := range schools {
		i := index[r.actionID]
		actions[i].Schools = append(actions[i].Schools, r.ActionSchoolRecord)
	}
	return actions, nil
}

// Action is one action with its schools; ErrNotFound when there is none.
func (s *Store) Action(ctx context.Context, id string) (ActionRecord, error) {
	rows, err := s.db.Query(ctx, selectAction+` WHERE a.id::text = $1`, id)
	if err != nil {
		return ActionRecord{}, fmt.Errorf("clusterlead: reading an action: %w", err)
	}
	action, err := pgx.CollectOneRow(rows, scanAction)
	if errors.Is(err, pgx.ErrNoRows) {
		return ActionRecord{}, ErrNotFound
	}
	if err != nil {
		return ActionRecord{}, fmt.Errorf("clusterlead: reading an action: %w", err)
	}
	out, err := s.withSchools(ctx, []ActionRecord{action})
	if err != nil {
		return ActionRecord{}, err
	}
	return out[0], nil
}

// ActionByKey is the action a client's idempotency key made; ErrNotFound if none.
func (s *Store) ActionByKey(ctx context.Context, key string) (ActionRecord, error) {
	var id string
	err := s.db.QueryRow(ctx, `SELECT id::text FROM cluster_leadership.cluster_action WHERE idempotency_key = $1`, key).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return ActionRecord{}, ErrNotFound
	}
	if err != nil {
		return ActionRecord{}, fmt.Errorf("clusterlead: reading an idempotency key: %w", err)
	}
	return s.Action(ctx, id)
}

// ClusterActions is every action of a cluster, newest first, with schools.
func (s *Store) ClusterActions(ctx context.Context, clusterID string, limit int) ([]ActionRecord, error) {
	rows, err := s.db.Query(ctx, selectAction+` WHERE a.cluster_id = $1 ORDER BY a.created_at DESC, a.id LIMIT $2`, clusterID, limit)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: listing actions: %w", err)
	}
	actions, err := pgx.CollectRows(rows, scanAction)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: listing actions: %w", err)
	}
	return s.withSchools(ctx, actions)
}

// QueueFilter picks the school requests a staff member sees.
type QueueFilter struct {
	// Staff-profile ids the requests are routed to as responsible CCEO.
	Responsible []string
	// Staff-profile ids the requests are routed to as supervisor.
	Supervisor []string
	// Unassigned requests too (no responsible CCEO and no supervisor),
	// kept to the schools of these registry countries when not nil
	// (docs/migration/80, §16).
	Unassigned          bool
	UnassignedCountries []string
}

// SupportQueue is the sent actions with a school routed to the filter, with
// those schools (other schools of the same action are left out).
func (s *Store) SupportQueue(ctx context.Context, f QueueFilter, limit int) ([]ActionRecord, error) {
	rows, err := s.db.Query(ctx, selectActionSchool+`
JOIN cluster_leadership.cluster_action ca ON ca.id = s.action_id
WHERE ca.status IN ('submitted', 'closed')
  AND (s.responsible_staff_id = ANY($1)
       OR (s.routed_to <> 'owner' AND s.supervisor_staff_id = ANY($2))
       OR ($3 AND s.routed_to = 'unassigned' AND ($5::text[] IS NULL OR EXISTS (
         SELECT 1 FROM school us WHERE us.id = s.school_id AND `+registry.SchoolIn("us", "$5")+`))))
ORDER BY ca.target_on, s.updated_at DESC
LIMIT $4`, f.Responsible, f.Supervisor, f.Unassigned, limit, f.UnassignedCountries)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading the support queue: %w", err)
	}
	schools, err := pgx.CollectRows(rows, scanActionSchool)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading the support queue: %w", err)
	}
	var out []ActionRecord
	index := map[string]int{}
	for _, r := range schools {
		i, ok := index[r.actionID]
		if !ok {
			action, err := s.Action(ctx, r.actionID)
			if err != nil {
				return nil, err
			}
			action.Schools = nil
			out = append(out, action)
			i = len(out) - 1
			index[r.actionID] = i
		}
		out[i].Schools = append(out[i].Schools, r.ActionSchoolRecord)
	}
	return out, nil
}

// SchoolActions is every sent action naming the school, newest first.
func (s *Store) SchoolActions(ctx context.Context, schoolID string, limit int) ([]ActionRecord, error) {
	rows, err := s.db.Query(ctx, selectAction+`
WHERE a.id IN (SELECT action_id FROM cluster_leadership.cluster_action_school WHERE school_id = $1)
ORDER BY a.created_at DESC LIMIT $2`, schoolID, limit)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading a school's actions: %w", err)
	}
	actions, err := pgx.CollectRows(rows, scanAction)
	if err != nil {
		return nil, err
	}
	return s.withSchools(ctx, actions)
}

// ActionHistory is an action's events, reviews and escalations.
func (s *Store) ActionHistory(ctx context.Context, actionID string) ([]ActionEventRecord, []ReviewRecord, []EscalationRecord, error) {
	rows, err := s.db.Query(ctx, `
SELECT e.event, COALESCE(u.name, CASE WHEN e.actor_id = 'system' THEN 'Edify follow-up' ELSE '' END), e.actor_role,
       COALESCE(sc.name, ''), e.from_status, e.to_status, e.note, e.at
FROM cluster_leadership.cluster_action_event e
LEFT JOIN "user" u ON u.id = e.actor_id
LEFT JOIN school sc ON sc.id = e.school_id
WHERE e.action_id::text = $1 ORDER BY e.at, e.id`, actionID)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("clusterlead: reading action history: %w", err)
	}
	events, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (ActionEventRecord, error) {
		var e ActionEventRecord
		return e, row.Scan(&e.Event, &e.Actor, &e.ActorRole, &e.School, &e.FromStatus, &e.ToStatus, &e.Note, &e.At)
	})
	if err != nil {
		return nil, nil, nil, err
	}
	rows, err = s.db.Query(ctx, `
SELECT r.id::text, COALESCE(act.activity_name_snapshot, mp.title, ''), r.progress, r.challenges, r.next_step,
       r.outcome, COALESCE(u.name, ''), r.created_at
FROM cluster_leadership.cluster_action_review r
LEFT JOIN activity act ON act.id = r.activity_id
LEFT JOIN cluster_leadership.meeting_plan mp ON mp.id = r.plan_id
LEFT JOIN "user" u ON u.id = r.created_by
WHERE r.action_id::text = $1 ORDER BY r.created_at, r.id`, actionID)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("clusterlead: reading reviews: %w", err)
	}
	reviews, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (ReviewRecord, error) {
		var r ReviewRecord
		return r, row.Scan(&r.ID, &r.Meeting, &r.Progress, &r.Challenges, &r.NextStep, &r.Outcome, &r.By, &r.At)
	})
	if err != nil {
		return nil, nil, nil, err
	}
	rows, err = s.db.Query(ctx, `
SELECT x.id::text, COALESCE(x.school_id, ''), x.reason,
       CASE WHEN x.raised_by_kind = 'policy' THEN 'Edify follow-up' ELSE COALESCE(u.name, '') END,
       COALESCE(x.to_staff_id, ''), COALESCE(tu.name, ''), COALESCE(tsp.user_id, ''), x.status, x.resolution, x.created_at
FROM cluster_leadership.cluster_action_escalation x
LEFT JOIN "user" u ON u.id = x.raised_by
LEFT JOIN staff_profile tsp ON tsp.id = x.to_staff_id
LEFT JOIN "user" tu ON tu.id = tsp.user_id
WHERE x.action_id::text = $1 ORDER BY x.created_at, x.id`, actionID)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("clusterlead: reading escalations: %w", err)
	}
	escalations, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (EscalationRecord, error) {
		var x EscalationRecord
		return x, row.Scan(&x.ID, &x.SchoolID, &x.Reason, &x.RaisedBy, &x.ToStaffID, &x.ToStaff, &x.ToUserID,
			&x.Status, &x.Resolution, &x.At)
	})
	return events, reviews, escalations, err
}

// Routes is where each school's request goes: the staff member holding the
// school (a CCEO first), their supervisor; or, when nobody holds it, the
// supervisor of the cluster's responsible staff for assignment.
func (s *Store) Routes(ctx context.Context, clusterID string, schoolIDs []string) (map[string]Route, error) {
	rows, err := s.db.Query(ctx, `
WITH holder AS (
  SELECT DISTINCT ON (a.school_id) a.school_id, a.staff_id
  FROM staff_school_assignment a
  JOIN staff_profile sp ON sp.id = a.staff_id AND sp.deleted_at IS NULL
  JOIN "user" u ON u.id = sp.user_id AND u.deleted_at IS NULL AND u.is_active
  WHERE a.school_id = ANY($2)
  ORDER BY a.school_id, ('CCEO' = ANY(u.roles)) DESC, a.staff_id),
cluster_staff AS (
  SELECT sp.id FROM cluster c
  JOIN staff_profile sp ON (sp.id = c.responsible_staff_id OR sp.user_id = c.responsible_staff_id) AND sp.deleted_at IS NULL
  WHERE c.id = $1 LIMIT 1)
SELECT s.id, COALESCE(h.staff_id, ''),
       COALESCE((SELECT supervisor_id FROM staff_supervisor_assignment WHERE supervisee_id = h.staff_id ORDER BY supervisor_id LIMIT 1), ''),
       COALESCE((SELECT supervisor_id FROM staff_supervisor_assignment
                 WHERE supervisee_id = (SELECT id FROM cluster_staff) ORDER BY supervisor_id LIMIT 1), '')
FROM unnest($2::varchar[]) AS s(id)
LEFT JOIN holder h ON h.school_id = s.id`, clusterID, schoolIDs)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: routing requests: %w", err)
	}
	defer rows.Close()
	out := map[string]Route{}
	for rows.Next() {
		var school, holder, holderSupervisor, clusterSupervisor string
		if err := rows.Scan(&school, &holder, &holderSupervisor, &clusterSupervisor); err != nil {
			return nil, err
		}
		switch {
		case holder != "":
			out[school] = Route{ResponsibleStaffID: holder, SupervisorStaffID: holderSupervisor, RoutedTo: "owner"}
		case clusterSupervisor != "":
			out[school] = Route{SupervisorStaffID: clusterSupervisor, RoutedTo: "supervisor"}
		default:
			out[school] = Route{RoutedTo: "unassigned"}
		}
	}
	return out, rows.Err()
}

// UserOfStaff is the account of a staff profile; empty when there is none.
func (s *Store) UserOfStaff(ctx context.Context, staffID string) (string, error) {
	var user string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(user_id, '') FROM staff_profile WHERE id = $1 AND deleted_at IS NULL`, staffID).Scan(&user)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	return user, err
}

// Supervisees is the staff-profile ids a supervisor supervises.
func (s *Store) SuperviseesOf(ctx context.Context, staffID string) ([]string, error) {
	rows, err := s.db.Query(ctx, `SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1`, staffID)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading supervisees: %w", err)
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

// SupervisorOf is a staff member's supervisor's staff-profile id, or "".
func (s *Store) SupervisorOf(ctx context.Context, staffID string) (string, error) {
	var id string
	err := s.db.QueryRow(ctx, `SELECT supervisor_id FROM staff_supervisor_assignment WHERE supervisee_id = $1 ORDER BY supervisor_id LIMIT 1`, staffID).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	return id, err
}

// LeadersOf is the user ids of a cluster's live leaders on day.
func (s *Store) LeadersOf(ctx context.Context, clusterID string, day time.Time) ([]string, error) {
	rows, err := s.db.Query(ctx, `
SELECT user_id FROM cluster_leadership.leader_assignment
WHERE cluster_id = $1 AND status = 'active' AND starts_on <= $2 AND (ends_on IS NULL OR ends_on >= $2)`, clusterID, day)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading leaders: %w", err)
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

// LinkableActivity is an official activity a school's support may link to.
type LinkableActivity struct {
	ID, Name, Status string
	Date             *time.Time
}

// LinkableActivities is the school's own activities and the cluster's
// activities (a cluster training reaches its member schools), not deleted
// and not ended, dated from since on, soonest first.
func (s *Store) LinkableActivities(ctx context.Context, schoolID, clusterID string, since time.Time) ([]LinkableActivity, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_name_snapshot, a.activity_type, ''), a.status,
       COALESCE((a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date, a.planned_date)
FROM activity a
WHERE a.deleted_at IS NULL AND (a.school_id = $1 OR a.cluster_id = $2)
  AND a.status <> ALL($3)
  AND COALESCE((a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date, a.planned_date, $4) >= $4
ORDER BY 4 NULLS LAST, a.id
LIMIT 100`, schoolID, clusterID, activityEnded, since)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading linkable activities: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (LinkableActivity, error) {
		var a LinkableActivity
		return a, row.Scan(&a.ID, &a.Name, &a.Status, &a.Date)
	})
}

// ActivityReach is an activity's school and cluster, to check a link.
func (s *Store) ActivityReach(ctx context.Context, id string) (schoolID, clusterID, status string, err error) {
	err = s.db.QueryRow(ctx, `
SELECT COALESCE(school_id, ''), COALESCE(cluster_id, ''), status FROM activity WHERE id = $1 AND deleted_at IS NULL`,
		id).Scan(&schoolID, &clusterID, &status)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", "", "", ErrNotFound
	}
	return schoolID, clusterID, status, err
}

// SaveActionDraft creates an action, or edits a draft at the version read.
func (s *Store) SaveActionDraft(ctx context.Context, a ActionRecord, idempotencyKey string, isNew bool, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if isNew {
			_, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.cluster_action
  (id, ref, cluster_id, source, source_activity_id, source_plan_id, support_kind, training_course_id, title,
   description, expected_outcome, priority, target_on, school_ids, fiscal_year, status, idempotency_key, created_by, country_code)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,'draft',$16,$17, `+registry.ClusterCountryCode("$3")+`)`,
				a.ID, a.Ref, a.ClusterID, a.Source, nullable(a.SourceActivityID), nullable(a.SourcePlanID), a.SupportKind,
				nullable(a.TrainingCourseID), a.Title, a.Description, a.ExpectedOutcome, a.Priority, a.TargetOn, a.SchoolIDs,
				a.FiscalYear, nullable(idempotencyKey), w.ActorID)
			if isUniqueViolation(err) {
				return ErrAlreadyAssigned
			}
			if err != nil {
				return fmt.Errorf("clusterlead: creating an action: %w", err)
			}
		} else {
			tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action SET
  source = $3, source_activity_id = $4, source_plan_id = $5, support_kind = $6, training_course_id = $7, title = $8,
  description = $9, expected_outcome = $10, priority = $11, target_on = $12, school_ids = $13,
  version = version + 1, updated_at = now()
WHERE id::text = $1 AND status = 'draft' AND version = $2`,
				a.ID, a.Version, a.Source, nullable(a.SourceActivityID), nullable(a.SourcePlanID), a.SupportKind,
				nullable(a.TrainingCourseID), a.Title, a.Description, a.ExpectedOutcome, a.Priority, a.TargetOn, a.SchoolIDs)
			if err != nil {
				return fmt.Errorf("clusterlead: editing an action: %w", err)
			}
			if tag.RowsAffected() == 0 {
				return ErrStale
			}
		}
		return s.record(ctx, tx, a.ID, w)
	})
}

// SubmitAction sends a draft: each school gets its routed row.
func (s *Store) SubmitAction(ctx context.Context, actionID string, version int32, routes map[string]Route, schoolIDs []string, ids []string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action SET status = 'submitted', submitted_at = now(), updated_at = now(),
  version = version + 1
WHERE id::text = $1 AND status = 'draft' AND version = $2`, actionID, version)
		if err != nil {
			return fmt.Errorf("clusterlead: sending an action: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrStale
		}
		for i, school := range schoolIDs {
			r := routes[school]
			if _, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.cluster_action_school
  (id, action_id, school_id, responsible_staff_id, supervisor_staff_id, routed_to, status, country_code)
VALUES ($1, $2::uuid, $3, $4, $5, $6, 'awaiting_review', (SELECT a.country_code FROM cluster_leadership.cluster_action a WHERE a.id = $2::uuid))`,
				ids[i], actionID, school, nullable(r.ResponsibleStaffID), nullable(r.SupervisorStaffID), r.RoutedTo); err != nil {
				return fmt.Errorf("clusterlead: routing a school: %w", err)
			}
		}
		return s.record(ctx, tx, actionID, w)
	})
}

// MoveSchool moves one school's request from one of from to status.
func (s *Store) MoveSchool(ctx context.Context, actionID, schoolID string, from []string, status, note string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action_school SET status = $4, status_note = $5, updated_at = now()
WHERE action_id::text = $1 AND school_id = $2 AND status = ANY($3)`, actionID, schoolID, from, status, note)
		if err != nil {
			return fmt.Errorf("clusterlead: updating a school request: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrStale
		}
		return s.record(ctx, tx, actionID, w)
	})
}

// LinkSchoolActivity links (or, with activityID empty, unlinks) the official
// activity delivering a school's accepted support.
func (s *Store) LinkSchoolActivity(ctx context.Context, actionID, schoolID, activityID string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action_school SET activity_id = $3,
  linked_by = CASE WHEN $3::varchar IS NULL THEN NULL ELSE $4 END,
  linked_at = CASE WHEN $3::varchar IS NULL THEN NULL ELSE now() END, updated_at = now()
WHERE action_id::text = $1 AND school_id = $2 AND status = 'accepted'`,
			actionID, schoolID, nullable(activityID), w.ActorID)
		if err != nil {
			return fmt.Errorf("clusterlead: linking an activity: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrStale
		}
		return s.record(ctx, tx, actionID, w)
	})
}

// EndAction cancels (with every unfinished school) or closes an action.
func (s *Store) EndAction(ctx context.Context, actionID, status, summary string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action SET status = $2, close_summary = $3, closed_at = now(), updated_at = now(),
  version = version + 1
WHERE id::text = $1 AND status IN ('draft', 'submitted')`, actionID, status, summary)
		if err != nil {
			return fmt.Errorf("clusterlead: ending an action: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrStale
		}
		if status == "cancelled" {
			if _, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action_school SET status = 'cancelled', status_note = $2, updated_at = now()
WHERE action_id::text = $1 AND status IN ('awaiting_review', 'under_review', 'clarification_requested', 'accepted')
  AND activity_id IS NULL`, actionID, summary); err != nil {
				return fmt.Errorf("clusterlead: cancelling schools: %w", err)
			}
		}
		return s.record(ctx, tx, actionID, w)
	})
}

// AddReview records a meeting's review of an action.
func (s *Store) AddReview(ctx context.Context, r ReviewRecord, actionID, activityID, planID string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.cluster_action_review
  (id, action_id, activity_id, plan_id, progress, challenges, next_step, outcome, created_by, country_code)
VALUES ($1, $2::uuid, $3, $4::uuid, $5, $6, $7, $8, $9, (SELECT a.country_code FROM cluster_leadership.cluster_action a WHERE a.id = $2::uuid))`, r.ID, actionID, nullable(activityID), nullable(planID),
			r.Progress, r.Challenges, r.NextStep, r.Outcome, w.ActorID); err != nil {
			return fmt.Errorf("clusterlead: recording a review: %w", err)
		}
		return s.record(ctx, tx, actionID, w)
	})
}

// AddEscalation records an escalation and marks the schools it covers.
func (s *Store) AddEscalation(ctx context.Context, x EscalationRecord, actionID, kind, fromStaffID string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.cluster_action_escalation
  (id, action_id, school_id, reason, raised_by_kind, raised_by, from_staff_id, to_staff_id, country_code)
VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, (SELECT a.country_code FROM cluster_leadership.cluster_action a WHERE a.id = $2::uuid))`, x.ID, actionID, nullable(x.SchoolID), x.Reason, kind, w.ActorID,
			nullable(fromStaffID), nullable(x.ToStaffID)); err != nil {
			return fmt.Errorf("clusterlead: recording an escalation: %w", err)
		}
		if _, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action_school SET escalated_at = now()
WHERE action_id::text = $1 AND ($2 = '' OR school_id = $2)`, actionID, x.SchoolID); err != nil {
			return fmt.Errorf("clusterlead: marking escalated schools: %w", err)
		}
		return s.record(ctx, tx, actionID, w)
	})
}

// ResolveEscalation resolves an open escalation.
func (s *Store) ResolveEscalation(ctx context.Context, id, actionID, resolution string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action_escalation SET status = 'resolved', resolved_at = now(), resolved_by = $2,
  resolution = $3
WHERE id::text = $1 AND status = 'open'`, id, w.ActorID, resolution)
		if err != nil {
			return fmt.Errorf("clusterlead: resolving an escalation: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrStale
		}
		return s.record(ctx, tx, actionID, w)
	})
}

// EscalationByID is one escalation and its action.
func (s *Store) EscalationByID(ctx context.Context, id string) (actionID, toStaffID, status string, err error) {
	err = s.db.QueryRow(ctx, `SELECT action_id::text, COALESCE(to_staff_id, ''), status FROM cluster_leadership.cluster_action_escalation WHERE id::text = $1`,
		id).Scan(&actionID, &toStaffID, &status)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", "", "", ErrNotFound
	}
	return actionID, toStaffID, status, err
}

// MarkReminded notes that a school's request was reminded about.
func (s *Store) MarkReminded(ctx context.Context, actionID, schoolID string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE cluster_leadership.cluster_action_school SET reminded_at = now() WHERE action_id::text = $1 AND school_id = $2`,
			actionID, schoolID); err != nil {
			return fmt.Errorf("clusterlead: marking a reminder: %w", err)
		}
		return s.record(ctx, tx, actionID, w)
	})
}

// record appends the write's events and notices in the same transaction.
func (s *Store) record(ctx context.Context, tx pgx.Tx, actionID string, w ActionWrite) error {
	for _, e := range w.Events {
		if _, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.cluster_action_event (action_id, school_id, event, actor_id, actor_role, from_status, to_status, note, country_code)
VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, (SELECT a.country_code FROM cluster_leadership.cluster_action a WHERE a.id = $1::uuid))`, actionID, nullable(e.School), e.Event, w.ActorID, w.ActorRole,
			e.FromStatus, e.ToStatus, e.Note); err != nil {
			return fmt.Errorf("clusterlead: recording an action event: %w", err)
		}
	}
	for _, n := range w.Notices {
		id, err := newID()
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.cluster_action_notice
  (id, action_id, recipient_user_id, event, title, body, target_route, sender_user_id, dedup_key, country_code)
VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, (SELECT a.country_code FROM cluster_leadership.cluster_action a WHERE a.id = $2::uuid))
ON CONFLICT (dedup_key) DO NOTHING`, id, actionID, n.RecipientUserID, n.Event, n.Title, n.Body, n.TargetRoute,
			nullable(n.SenderUserID), n.DedupKey); err != nil {
			return fmt.Errorf("clusterlead: queueing a notice: %w", err)
		}
	}
	return nil
}

// PendingNotices is notices not yet delivered, oldest first.
func (s *Store) PendingNotices(ctx context.Context, maxAttempts, limit int) ([]NoticeRecord, error) {
	rows, err := s.db.Query(ctx, `
SELECT n.id::text, n.action_id::text, n.recipient_user_id, n.event, n.title, n.body, n.target_route,
       COALESCE(n.sender_user_id, ''), n.dedup_key, n.attempts
FROM cluster_leadership.cluster_action_notice n
WHERE n.status IN ('pending', 'failed') AND n.attempts < $1
ORDER BY n.created_at LIMIT $2`, maxAttempts, limit)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading notices: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (NoticeRecord, error) {
		var n NoticeRecord
		return n, row.Scan(&n.ID, &n.ActionID, &n.RecipientUserID, &n.Event, &n.Title, &n.Body, &n.TargetRoute,
			&n.SenderUserID, &n.DedupKey, &n.Attempts)
	})
}

// NoticeDelivered records a delivery attempt's outcome.
func (s *Store) NoticeDelivered(ctx context.Context, id string, deliveryErr error) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var err error
		if deliveryErr == nil {
			_, err = tx.Exec(ctx, `UPDATE cluster_leadership.cluster_action_notice SET status = 'sent', sent_at = now(),
  attempts = attempts + 1, last_error = '' WHERE id::text = $1`, id)
		} else {
			message := deliveryErr.Error()
			if len(message) > 500 {
				message = message[:500]
			}
			_, err = tx.Exec(ctx, `UPDATE cluster_leadership.cluster_action_notice SET status = 'failed',
  attempts = attempts + 1, last_error = $2 WHERE id::text = $1`, id, message)
		}
		if err != nil {
			return fmt.Errorf("clusterlead: recording a notice delivery: %w", err)
		}
		return nil
	})
}

// FollowUpCandidates is sent actions with a school still open, for the
// follow-up worker.
func (s *Store) FollowUpCandidates(ctx context.Context, limit int) ([]ActionRecord, error) {
	rows, err := s.db.Query(ctx, selectAction+`
WHERE a.status = 'submitted' AND EXISTS (
  SELECT 1 FROM cluster_leadership.cluster_action_school x
  WHERE x.action_id = a.id AND x.status NOT IN ('returned', 'declined', 'cancelled'))
ORDER BY a.target_on LIMIT $1`, limit)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading follow-up candidates: %w", err)
	}
	actions, err := pgx.CollectRows(rows, scanAction)
	if err != nil {
		return nil, err
	}
	return s.withSchools(ctx, actions)
}

// QueueNotices writes notices (each at most once, by its dedup key) with
// no other change.
func (s *Store) QueueNotices(ctx context.Context, actionID string, w ActionWrite) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error { return s.record(ctx, tx, actionID, w) })
}
