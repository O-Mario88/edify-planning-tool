package clusterlead

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// The cluster management report (brief A7), counted from the existing
// activities and the portal's own records for one financial year.

// ReportData is what the report is made of.
type ReportData struct {
	MeetingsPlanned, MeetingsHeld, TrainingsPlanned, TrainingsHeld int32
	SchoolsInvited, SchoolsParticipating, OpenItems                int32
	Absent                                                         []AbsentSchool
	TrainingByIntervention, SSAStatus                              []Count
	PlansToReview, OpenRequests                                    int32
}

// AbsentSchool is a member school absent from held activities it was invited to.
type AbsentSchool struct {
	ID, SchoolID, Name string
	Absences, Invited  int32
}

// Count is a labelled count.
type Count struct {
	Label string
	Count int32
}

// fyActivities is the cluster's activities whose day falls in [$2, $3).
const fyActivities = `
SELECT a.id, a.status, COALESCE(a.meeting_kind, '') AS kind, COALESCE(a.training_course_id, '') AS course,
       COALESCE(a.attended_school_ids, '{}') AS attended
FROM activity a
WHERE a.cluster_id = $1 AND a.deleted_at IS NULL
  AND COALESCE((a.scheduled_date AT TIME ZONE $4)::date, a.planned_date) >= $2
  AND COALESCE((a.scheduled_date AT TIME ZONE $4)::date, a.planned_date) < $3`

// Report counts the cluster's year from start (inclusive) to end (exclusive).
func (s *Store) Report(ctx context.Context, clusterID string, start, end time.Time) (ReportData, error) {
	var r ReportData
	err := s.db.QueryRow(ctx, `
WITH fy AS (`+fyActivities+`),
held AS (SELECT * FROM fy WHERE status = ANY($5)),
invited AS (
  SELECT i.school_id, i.activity_id FROM cluster_leadership.invitation i JOIN fy ON fy.id = i.activity_id),
attended AS (
  SELECT DISTINCT unnest(attended) AS school_id FROM held
  UNION
  SELECT r.school_id FROM cluster_leadership.attendance_record r JOIN fy ON fy.id = r.activity_id WHERE r.attended)
SELECT
  (SELECT count(*) FROM fy WHERE kind <> 'training' AND status = ANY($6)),
  (SELECT count(*) FROM held WHERE kind <> 'training'),
  (SELECT count(*) FROM fy WHERE kind = 'training' AND status = ANY($6)),
  (SELECT count(*) FROM held WHERE kind = 'training'),
  (SELECT count(DISTINCT school_id) FROM invited),
  (SELECT count(*) FROM attended),
  (SELECT count(*) FROM cluster_leadership.action_item WHERE cluster_id = $1 AND status = 'open'),
  (SELECT count(*) FROM cluster_leadership.meeting_plan WHERE cluster_id = $1 AND status = 'submitted'),
  (SELECT count(*) FROM cluster_leadership.leader_request WHERE cluster_id = $1 AND status = 'open')`,
		clusterID, start, end, zoneName, deliveredStatuses, plannedStatuses).Scan(
		&r.MeetingsPlanned, &r.MeetingsHeld, &r.TrainingsPlanned, &r.TrainingsHeld,
		&r.SchoolsInvited, &r.SchoolsParticipating, &r.OpenItems, &r.PlansToReview, &r.OpenRequests)
	if err != nil {
		return ReportData{}, fmt.Errorf("clusterlead: counting the report: %w", err)
	}

	absentRows, err := s.db.Query(ctx, `
WITH fy AS (`+fyActivities+`),
held AS (SELECT * FROM fy WHERE status = ANY($5)),
per_school AS (
  SELECT i.school_id,
         count(*) AS invited,
         count(*) FILTER (WHERE NOT (i.school_id = ANY(h.attended)) AND NOT EXISTS (
           SELECT 1 FROM cluster_leadership.attendance_record r
           WHERE r.activity_id = h.id AND r.school_id = i.school_id AND r.attended)) AS absences
  FROM cluster_leadership.invitation i JOIN held h ON h.id = i.activity_id
  GROUP BY i.school_id)
SELECT s.id, s.school_id, s.name, p.absences, p.invited
FROM per_school p JOIN school s ON s.id = p.school_id
WHERE p.absences >= 2
ORDER BY p.absences DESC, s.name`, clusterID, start, end, zoneName, deliveredStatuses)
	if err != nil {
		return ReportData{}, fmt.Errorf("clusterlead: reading absences: %w", err)
	}
	if r.Absent, err = pgx.CollectRows(absentRows, func(row pgx.CollectableRow) (AbsentSchool, error) {
		var a AbsentSchool
		return a, row.Scan(&a.ID, &a.SchoolID, &a.Name, &a.Absences, &a.Invited)
	}); err != nil {
		return ReportData{}, err
	}

	if r.TrainingByIntervention, err = s.counts(ctx, `
WITH fy AS (`+fyActivities+`)
SELECT COALESCE(NULLIF(c.ssa_indicator_label, ''), 'Not named'), count(*)
FROM fy LEFT JOIN activity_catalogue_item c ON c.id = fy.course
WHERE fy.kind = 'training' AND fy.status = ANY($5)
GROUP BY 1 ORDER BY 2 DESC, 1`, clusterID, start, end, zoneName, deliveredStatuses); err != nil {
		return ReportData{}, err
	}
	if r.SSAStatus, err = s.counts(ctx, `
SELECT COALESCE(NULLIF(s.current_fy_ssa_status, ''), 'none'), count(*)
FROM school s WHERE`+memberPredicate+`
GROUP BY 1 ORDER BY 2 DESC, 1`, clusterID); err != nil {
		return ReportData{}, err
	}
	return r, nil
}

func (s *Store) counts(ctx context.Context, sql string, args ...any) ([]Count, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: counting: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (Count, error) {
		var c Count
		return c, row.Scan(&c.Label, &c.Count)
	})
}
