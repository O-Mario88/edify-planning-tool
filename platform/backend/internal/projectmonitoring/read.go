package projectmonitoring

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// project is one live project row as the page reads it.
type project struct {
	ID, Code, Name, Status string
	// Intervention is the legacy single target; Targets the ordered list.
	Intervention string
	Targets      []string
}

// targetList is Project.target_intervention_list: the ordered targets, with
// the legacy single field added when it is not among them.
func (p project) targetList() []string {
	out := append([]string(nil), p.Targets...)
	if p.Intervention != "" && !in(out, p.Intervention) {
		out = append(out, p.Intervention)
	}
	return out
}

// plan is Project.intervention_plan: the primary SSA intervention and the
// supporting ones, General and unknown codes left out.
func (p project) plan() (string, []string) {
	targets := []string{}
	for _, t := range p.targetList() {
		if isIntervention(t) && !in(targets, t) {
			targets = append(targets, t)
		}
	}
	if len(targets) == 0 {
		return "", nil
	}
	primary := targets[0]
	if in(targets, p.Intervention) {
		primary = p.Intervention
	}
	supporting := []string{}
	for _, t := range targets {
		if t != primary {
			supporting = append(supporting, t)
		}
	}
	return primary, supporting
}

// measuredBySSA is Project.measured_by_ssa.
func (p project) measuredBySSA() bool {
	targets := p.targetList()
	for _, t := range targets {
		if isIntervention(t) {
			return true
		}
	}
	return !in(targets, rules.GeneralIntervention)
}

// statusLabel is Project.status_label.
func (p project) statusLabel() string {
	if p.Status == "" {
		return "Active"
	}
	return rules.StatusLabels[p.Status]
}

// enrolment is one current ProjectSchoolAssignment with its school.
type enrolment struct {
	ID, ProjectID, SchoolPK, SchoolCode, SchoolName, District string
	AssignedBy, Participation, Matched, SupportArea, Impact   string
	StartDate                                                 *time.Time
	CreatedAt                                                 time.Time
	Baseline                                                  *float64
}

// enrolledOn is the assignment's start date, else the day (UTC) it was made.
func (e enrolment) enrolledOn() time.Time {
	if e.StartDate != nil {
		return *e.StartDate
	}
	c := e.CreatedAt.UTC()
	return time.Date(c.Year(), c.Month(), c.Day(), 0, 0, 0, 0, time.UTC)
}

const projectColumns = `p.id, COALESCE(p.code, ''), p.name, p.status, COALESCE(p.intervention, ''), p.target_interventions`

func scanProjects(rows pgx.Rows, err error) ([]project, error) {
	if err != nil {
		return nil, fmt.Errorf("projectmonitoring: reading the projects: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (project, error) {
		var p project
		var targets []byte
		if err := r.Scan(&p.ID, &p.Code, &p.Name, &p.Status, &p.Intervention, &targets); err != nil {
			return p, err
		}
		var list []any
		if len(targets) > 0 {
			if err := json.Unmarshal(targets, &list); err != nil {
				return p, fmt.Errorf("projectmonitoring: reading a project's targets: %w", err)
			}
		}
		for _, t := range list {
			if s, ok := t.(string); ok {
				p.Targets = append(p.Targets, s)
			} else {
				return p, errUnread
			}
		}
		return p, nil
	})
}

// projectsFor is monitoring._projects_for: every live project this reader
// may watch, by name.
func projectsFor(ctx context.Context, q schooldirectory.Querier, l lens, scope schooldirectory.Scope) ([]project, error) {
	base := `SELECT ` + projectColumns + ` FROM project p WHERE p.deleted_at IS NULL AND p.status = ANY($1)`
	switch {
	case l.whole:
		return scanProjects(q.Query(ctx, base+` ORDER BY p.name ASC`, rules.LiveStatuses))
	case l.controls:
		// planning_service._scoped_projects for a coordinator: every project
		// for a country-scoped reader, else the ones they manage or are
		// actively assigned to.
		if scope.CountryScope {
			return scanProjects(q.Query(ctx, base+` ORDER BY p.name ASC`, rules.LiveStatuses))
		}
		if l.staffID == "" {
			return nil, nil
		}
		return scanProjects(q.Query(ctx, base+` AND (p.manager_staff_id = $2 OR EXISTS (
  SELECT 1 FROM project_staff_assignment sa WHERE sa.project_id = p.id AND sa.staff_id = $2 AND sa.is_active))
ORDER BY p.name ASC`, rules.LiveStatuses, l.staffID))
	}
	if len(l.mine) == 0 {
		return nil, nil
	}
	return scanProjects(q.Query(ctx, base+` AND EXISTS (
  SELECT 1 FROM project_school_assignment a WHERE a.project_id = p.id AND a.assigned_by = ANY($2))
ORDER BY p.name ASC`, rules.LiveStatuses, l.mine))
}

// enrolments is monitoring._visible_assignments: the current enrolments in
// these projects the reader may see, by school name.
func enrolments(ctx context.Context, q schooldirectory.Querier, l lens, projectIDs []string) ([]enrolment, error) {
	if !l.whole && !l.controls && len(l.mine) == 0 {
		return nil, nil
	}
	sql := `
SELECT a.id, a.project_id, s.id, COALESCE(s.school_id, ''), s.name, COALESCE(d.name, ''), COALESCE(a.assigned_by, ''),
  COALESCE(a.participation_type, ''), COALESCE(a.matched_intervention, ''), COALESCE(a.support_area, ''),
  a.impact_classification, a.start_date, a.created_at, a.baseline_score
FROM project_school_assignment a INNER JOIN school s ON a.school_id = s.id
INNER JOIN project p ON a.project_id = p.id LEFT OUTER JOIN district d ON s.district_id = d.id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1) AND a.project_id = ANY($2)`
	args := []any{rules.OperatingStatuses, projectIDs}
	if !l.whole && !l.controls {
		sql += ` AND a.assigned_by = ANY($3)`
		args = append(args, l.mine)
	}
	rows, err := q.Query(ctx, sql+` ORDER BY s.name ASC`, args...)
	if err != nil {
		return nil, fmt.Errorf("projectmonitoring: reading the enrolments: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (enrolment, error) {
		var e enrolment
		err := r.Scan(&e.ID, &e.ProjectID, &e.SchoolPK, &e.SchoolCode, &e.SchoolName, &e.District, &e.AssignedBy,
			&e.Participation, &e.Matched, &e.SupportArea, &e.Impact, &e.StartDate, &e.CreatedAt, &e.Baseline)
		if e.SchoolCode == "" {
			e.SchoolCode = e.SchoolPK
		}
		return e, err
	})
}

// allEnrolments is ProjectSchoolAssignment.objects.filter(project=project):
// every enrolment of the project, closed schools' included, for the impact
// engine's whole-project cohort.
func allEnrolments(ctx context.Context, q schooldirectory.Querier, projectID string) ([]enrolment, error) {
	rows, err := q.Query(ctx, `
SELECT a.impact_classification, a.baseline_score FROM project_school_assignment a WHERE a.project_id = $1`, projectID)
	if err != nil {
		return nil, fmt.Errorf("projectmonitoring: reading the project's cohort: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (enrolment, error) {
		var e enrolment
		return e, r.Scan(&e.Impact, &e.Baseline)
	})
}

// hasWork is whether anything this piece does not draw exists in view:
// project activities (any year, any state, which also decide the withdrawal
// blocks), partner hand-overs, or school allocations of these projects or of
// the reader. The page then needs the work lines Go does not build yet.
func hasWork(ctx context.Context, q schooldirectory.Querier, projectIDs []string, staffID string) (bool, error) {
	var found bool
	err := q.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM activity WHERE project_id = ANY($1) AND deleted_at IS NULL)
  OR EXISTS (SELECT 1 FROM partner_assignment WHERE project_id = ANY($1))
  OR EXISTS (SELECT 1 FROM project_staff_capacity WHERE project_id = ANY($1))
  OR EXISTS (SELECT 1 FROM project_staff_capacity c INNER JOIN project p ON c.project_id = p.id
             WHERE $2 <> '' AND c.staff_id = $2 AND p.deleted_at IS NULL)`, projectIDs, staffID).Scan(&found)
	if err != nil {
		return false, fmt.Errorf("projectmonitoring: looking for project work: %w", err)
	}
	return found, nil
}

// reading is one confirmed score of one intervention at one school.
type reading struct {
	Day   time.Time
	Score float64
}

// focusReadings is monitoring._focus_readings: confirmed in-scale scores per
// school and intervention, oldest first, in the statement Django issues.
func focusReadings(ctx context.Context, q schooldirectory.Querier, codes, schoolIDs []string) (map[string]map[string][]reading, error) {
	out := map[string]map[string][]reading{}
	if len(codes) == 0 || len(schoolIDs) == 0 {
		return out, nil
	}
	rows, err := q.Query(ctx, `
SELECT ssa_record.school_id, ssa_score.intervention, ssa_score.score, ssa_record.date_of_ssa
FROM ssa_score INNER JOIN ssa_record ON (ssa_score.ssa_record_id = ssa_record.id)
WHERE (ssa_score.intervention = ANY($1) AND ssa_record.deleted_at IS NULL AND ssa_record.school_id = ANY($2)
  AND ssa_record.verification_status = $3) ORDER BY 4 ASC`, codes, schoolIDs, rules.Confirmed)
	if err != nil {
		return nil, fmt.Errorf("projectmonitoring: reading the SSA scores: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var school, code string
		var score float64
		var assessed *time.Time
		if err := rows.Scan(&school, &code, &score, &assessed); err != nil {
			return nil, fmt.Errorf("projectmonitoring: reading the SSA scores: %w", err)
		}
		if assessed == nil || score < rules.ScoreMin || score > rules.ScoreMax {
			continue
		}
		a := assessed.UTC()
		if out[school] == nil {
			out[school] = map[string][]reading{}
		}
		out[school][code] = append(out[school][code], reading{
			Day:   time.Date(a.Year(), a.Month(), a.Day(), 0, 0, 0, 0, time.UTC),
			Score: pyRound(score, 2),
		})
	}
	return out, rows.Err()
}

// peopleNames is monitoring._people_names: display names for ids in either
// id space.
func peopleNames(ctx context.Context, q schooldirectory.Querier, ids []string) (map[string]string, error) {
	names := map[string]string{}
	if len(ids) == 0 {
		return names, nil
	}
	rows, err := q.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_profile sp LEFT OUTER JOIN "user" u ON sp.user_id = u.id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, ids)
	if err != nil {
		return nil, fmt.Errorf("projectmonitoring: reading the staff names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, userID, label string
		if err := rows.Scan(&id, &userID, &label); err != nil {
			return nil, fmt.Errorf("projectmonitoring: reading the staff names: %w", err)
		}
		names[id] = label
		if userID != "" {
			names[userID] = label
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rest := []string{}
	for _, id := range ids {
		if _, ok := names[id]; !ok {
			rest = append(rest, id)
		}
	}
	if len(rest) == 0 {
		return names, nil
	}
	rows, err = q.Query(ctx, `SELECT id, COALESCE(NULLIF(name, ''), email, '') FROM "user" WHERE id = ANY($1)`, rest)
	if err != nil {
		return nil, fmt.Errorf("projectmonitoring: reading the user names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, label string
		if err := rows.Scan(&id, &label); err != nil {
			return nil, fmt.Errorf("projectmonitoring: reading the user names: %w", err)
		}
		names[id] = label
	}
	return names, rows.Err()
}
