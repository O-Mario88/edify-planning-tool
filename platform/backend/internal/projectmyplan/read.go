package projectmyplan

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

type project struct{ id, name string }

// projects is _project_queryset: every live project for a country reader;
// otherwise those the person manages (a coordinator) or is assigned to, or
// that hold a school in their reach.
func projects(ctx context.Context, db schooldirectory.Querier, p auth.Principal, sc schooldirectory.Scope) ([]project, error) {
	where, args := "TRUE", []any{}
	switch {
	case sc.CountryScope:
	case p.StaffProfileID != "":
		args = append(args, p.StaffProfileID)
		assigned := `EXISTS (SELECT 1 FROM project_staff_assignment a WHERE a.project_id = p.id AND a.staff_id = $1 AND a.is_active)`
		switch {
		case p.ActiveRole == "ProjectCoordinator":
			where = "(p.manager_staff_id = $1 OR " + assigned + ")"
		case len(sc.SchoolIDs) > 0:
			args = append(args, sc.SchoolIDs)
			where = "(" + assigned + ` OR EXISTS (SELECT 1 FROM project_school_assignment psa WHERE psa.project_id = p.id AND psa.school_id = ANY($2)))`
		default:
			where = assigned
		}
	case len(sc.SchoolIDs) > 0:
		args = append(args, sc.SchoolIDs)
		where = `EXISTS (SELECT 1 FROM project_school_assignment psa WHERE psa.project_id = p.id AND psa.school_id = ANY($1))`
	default:
		return nil, nil
	}
	rows, err := db.Query(ctx, `SELECT p.id, p.name FROM project p WHERE p.deleted_at IS NULL AND `+where+` ORDER BY p.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the projects: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (project, error) {
		var pr project
		err := row.Scan(&pr.id, &pr.name)
		return pr, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the projects: %w", err)
	}
	return out, nil
}

// query is get_my_plan's activity filter as SQL on activity `a`, its school
// `s`, the school's district `sd` and its cluster `cl`.
type query struct {
	where string
	args  []any
}

func (q *query) arg(v any) string {
	q.args = append(q.args, v)
	return fmt.Sprintf("$%d", len(q.args))
}

const fromActivities = `FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN district sd ON sd.id = s.district_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN district cd ON cd.id = cl.district_id`

// likeEscape is the pattern Django's icontains writes for a term.
func likeEscape(s string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(s) + "%"
}

func baseQuery(ids []string, f filters) *query {
	q := &query{}
	q.where = "a.deleted_at IS NULL AND a.project_id = ANY(" + q.arg(ids) + ")"
	fy := q.arg(f.fy)
	q.where += " AND (a.fy = " + fy + " OR a.fiscal_year = " + fy + ")"
	if !in(rules.ActiveExclusions, f.status) {
		q.where += " AND NOT (a.status = ANY(" + q.arg(rules.ActiveExclusions) + "))"
	}
	if f.region != "" {
		r := q.arg(f.region)
		q.where += " AND (s.region_id = " + r + " OR cl.region_id = " + r + ")"
	}
	if f.district != "" {
		d := q.arg(f.district)
		q.where += " AND (s.district_id = " + d + " OR cl.district_id = " + d + ")"
	}
	if f.project != "" {
		q.where += " AND a.project_id = " + q.arg(f.project)
	}
	if f.partner != "" {
		q.where += " AND a.assigned_partner_id = " + q.arg(f.partner)
	}
	if f.activityType != "" {
		q.where += " AND a.activity_type = " + q.arg(f.activityType)
	}
	switch f.status {
	case "":
	case "returned":
		q.where += " AND a.status = ANY(" + q.arg(rules.ReturnedStates) + ")"
	case "review":
		q.where += " AND a.status = ANY(" + q.arg(rules.ReviewStates) + ")"
	default:
		q.where += " AND a.status = " + q.arg(f.status)
	}
	if f.search != "" {
		t := q.arg(likeEscape(f.search))
		q.where += " AND (UPPER(s.name::text) LIKE UPPER(" + t + ") OR UPPER(cl.name::text) LIKE UPPER(" + t +
			") OR UPPER(sd.name::text) LIKE UPPER(" + t + ") OR UPPER(a.activity_purpose_text::text) LIKE UPPER(" + t + "))"
	}
	return q
}

// work is one piece of project work with what the page shows of it.
type work struct {
	id, kind, delivery, staff, status, salesforce, evidence, purpose, focus, partnerID, projectID string
	planned, plannedBefore, delivered                                                             *time.Time
	reschedules, teachers, leaders, others                                                        int
	schoolCode, school, schoolDistrict, cluster, clusterDistrict                                  string
	hasSchool, hasCluster                                                                         bool
	lines                                                                                         int
	advances                                                                                      []string
}

func (s *Service) works(ctx context.Context, q *query, start, end time.Time) ([]work, error) {
	args := append([]any{}, q.args...)
	args = append(args, start, end)
	n := len(args)
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.activity_type, COALESCE(a.delivery_type, ''), COALESCE(a.responsible_staff_id, ''), a.status,
  COALESCE(a.salesforce_activity_id, ''), COALESCE(a.evidence_status, ''), COALESCE(a.activity_purpose_text, ''),
  COALESCE(a.focus_intervention, ''), COALESCE(a.assigned_partner_id, ''), COALESCE(a.project_id, ''),
  a.planned_date, a.planned_date_before_completion, a.actual_delivery_date,
  COALESCE(a.reschedule_count, 0), COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0),
  COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(sd.name, ''), COALESCE(cl.name, ''), COALESCE(cd.name, ''),
  a.school_id IS NOT NULL, a.cluster_id IS NOT NULL,
  (SELECT COUNT(*) FROM activity_schedule_cost_line l WHERE l.activity_id = a.id),
  COALESCE((SELECT array_agg(r.status) FROM activity_schedule_cost_line l JOIN advance_request r ON r.budget_line_id = l.id
            WHERE l.activity_id = a.id), '{}')
`+fromActivities+`
WHERE `+q.where+fmt.Sprintf(` AND a.planned_date BETWEEN $%d AND $%d
ORDER BY a.planned_date, a.created_at`, n-1, n), args...)
	if err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the work: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (work, error) {
		var w work
		err := row.Scan(&w.id, &w.kind, &w.delivery, &w.staff, &w.status, &w.salesforce, &w.evidence, &w.purpose,
			&w.focus, &w.partnerID, &w.projectID, &w.planned, &w.plannedBefore, &w.delivered,
			&w.reschedules, &w.teachers, &w.leaders, &w.others,
			&w.schoolCode, &w.school, &w.schoolDistrict, &w.cluster, &w.clusterDistrict, &w.hasSchool, &w.hasCluster,
			&w.lines, &w.advances)
		return w, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the work: %w", err)
	}
	return out, nil
}

func (s *Service) count(ctx context.Context, q *query, start, end time.Time) (int, error) {
	args := append(append([]any{}, q.args...), start, end)
	var n int
	err := s.db.QueryRow(ctx, `SELECT COUNT(DISTINCT a.id) `+fromActivities+` WHERE `+q.where+
		fmt.Sprintf(` AND a.planned_date BETWEEN $%d AND $%d`, len(args)-1, len(args)), args...).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("projectmyplan: counting the work: %w", err)
	}
	return n, nil
}

// option is one filter choice.
type option struct{ value, label string }

func (s *Service) collect(ctx context.Context, sql string, args ...any) ([]option, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the filter choices: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (option, error) {
		var o option
		err := row.Scan(&o.value, &o.label)
		return o, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the filter choices: %w", err)
	}
	return out, nil
}

// partners is the live partners the work names, by name.
func (s *Service) partners(ctx context.Context, q *query) ([]option, error) {
	return s.collect(ctx, `SELECT p.id, p.name FROM partner p WHERE p.deleted_at IS NULL AND p.id IN (
  SELECT a.assigned_partner_id `+fromActivities+` WHERE `+q.where+` AND a.assigned_partner_id IS NOT NULL) ORDER BY p.name`, q.args...)
}

// districts is the districts any of the projects' work reaches through its
// school or its cluster, deleted rows included, in the chosen region.
func (s *Service) districts(ctx context.Context, ids []string, region string) ([]option, error) {
	args := []any{ids}
	extra := ""
	if region != "" {
		args = append(args, region)
		extra = " AND d.region_id = $2"
	}
	return s.collect(ctx, `SELECT d.id, d.name FROM district d WHERE (
  d.id IN (SELECT s.district_id FROM activity a JOIN school s ON s.id = a.school_id WHERE a.project_id = ANY($1))
  OR d.id IN (SELECT cl.district_id FROM activity a JOIN cluster cl ON cl.id = a.cluster_id WHERE a.project_id = ANY($1)))`+extra+`
ORDER BY d.name`, args...)
}

// kinds is the activity types the work holds.
func (s *Service) kinds(ctx context.Context, q *query) ([]string, error) {
	rows, err := s.db.Query(ctx, `SELECT DISTINCT a.activity_type `+fromActivities+` WHERE `+q.where+` ORDER BY a.activity_type`, q.args...)
	if err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the activity types: %w", err)
	}
	out, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the activity types: %w", err)
	}
	return out, nil
}

// advanced is how many of the work have an advance request.
func (s *Service) advanced(ctx context.Context, ids []string) (int, error) {
	if len(ids) == 0 {
		return 0, nil
	}
	var n int
	err := s.db.QueryRow(ctx, `SELECT COUNT(DISTINCT activity_id) FROM advance_request WHERE activity_id = ANY($1)`, ids).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("projectmyplan: counting the advances: %w", err)
	}
	return n, nil
}
