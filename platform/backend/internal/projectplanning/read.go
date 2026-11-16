package projectplanning

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

type project struct{ id, name, category, manager string }

// projects is _scoped_projects: every live project for a country reader; a
// coordinator's own (managed or assigned); otherwise those the person
// manages or is assigned to, or that hold a school in their reach.
func projects(ctx context.Context, db schooldirectory.Querier, p auth.Principal, sc schooldirectory.Scope) ([]project, error) {
	where, args := "TRUE", []any{}
	assigned := func(n int) string {
		return fmt.Sprintf(`(p.manager_staff_id = $%d OR EXISTS (SELECT 1 FROM project_staff_assignment a
  WHERE a.project_id = p.id AND a.staff_id = $%d AND a.is_active))`, n, n)
	}
	switch {
	case sc.CountryScope:
	case p.ActiveRole == "ProjectCoordinator":
		if p.StaffProfileID == "" {
			return nil, nil
		}
		args = append(args, p.StaffProfileID)
		where = assigned(1)
	default:
		parts := []string{}
		if p.StaffProfileID != "" {
			args = append(args, p.StaffProfileID)
			parts = append(parts, assigned(len(args)))
		}
		if len(sc.SchoolIDs) > 0 {
			args = append(args, sc.SchoolIDs)
			parts = append(parts, fmt.Sprintf(`EXISTS (SELECT 1 FROM project_school_assignment psa WHERE psa.project_id = p.id AND psa.school_id = ANY($%d))`, len(args)))
		}
		if len(parts) == 0 {
			return nil, nil
		}
		where = "(" + strings.Join(parts, " OR ") + ")"
	}
	rows, err := db.Query(ctx, `SELECT p.id, p.name, COALESCE(p.category, ''), COALESCE(p.manager_staff_id, '')
FROM project p WHERE p.deleted_at IS NULL AND `+where+` ORDER BY p.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("projectplanning: reading the projects: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (project, error) {
		var pr project
		err := row.Scan(&pr.id, &pr.name, &pr.category, &pr.manager)
		return pr, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectplanning: reading the projects: %w", err)
	}
	return out, nil
}

// assignment is one school a project holds, with what the queue shows of it.
type assignment struct {
	id, projectID, projectName, projectCategory, projectType string
	schoolPK, schoolCode, schoolName, schoolType             string
	districtID, district, regionID, region                   string
	ssaDate                                                  *time.Time
	ssaAverage                                               *float64
	weakest                                                  string
	weakestScore                                             *float64
}

// likeEscape is the pattern Django's icontains writes for a term.
func likeEscape(s string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(s) + "%"
}

// assignments is current_enrolments over the projects under the filters, by
// project and then school, each with its year's latest confirmed SSA and
// that SSA's weakest intervention.
func (s *Service) assignments(ctx context.Context, ids []string, f filters) ([]assignment, error) {
	args := []any{ids, rules.OperatingSchoolStatuses, f.fy}
	arg := func(v any) string { args = append(args, v); return fmt.Sprintf("$%d", len(args)) }
	where := ""
	if f.project != "" {
		where += " AND psa.project_id = " + arg(f.project)
	}
	if f.region != "" {
		where += " AND s.region_id = " + arg(f.region)
	}
	if f.district != "" {
		where += " AND s.district_id = " + arg(f.district)
	}
	if f.staff != "" {
		where += " AND p.manager_staff_id = " + arg(f.staff)
	}
	if f.projectType != "" {
		t := arg(f.projectType)
		where += " AND (psa.project_type = " + t + " OR p.category = " + t + ")"
	}
	if f.search != "" {
		t := arg(likeEscape(f.search))
		like := func(col string) string { return "UPPER(" + col + "::text) LIKE UPPER(" + t + ")" }
		where += " AND (" + strings.Join([]string{like("s.name"), like("s.school_id"), like("p.name"), like("p.code"),
			like("d.name"), like("sc.name"), like("s.account_owner_name_raw"),
			`psa.project_id IN (SELECT ppa.project_id FROM project_partner_assignment ppa JOIN partner pa ON pa.id = ppa.partner_id WHERE ` + like("pa.name") + `)`},
			" OR ") + ")"
	}
	rows, err := s.db.Query(ctx, `
SELECT psa.id, p.id, p.name, COALESCE(p.category, ''), COALESCE(psa.project_type, ''),
  s.id, COALESCE(s.school_id, ''), s.name, COALESCE(s.school_type, ''),
  COALESCE(s.district_id, ''), COALESCE(d.name, ''), COALESCE(s.region_id, ''), COALESCE(r.name, ''),
  ssa.date_of_ssa, ssa.average_score, COALESCE(w.intervention, ''), w.score
FROM project_school_assignment psa
JOIN project p ON p.id = psa.project_id
JOIN school s ON s.id = psa.school_id
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN region r ON r.id = s.region_id
LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
LEFT JOIN LATERAL (SELECT x.id, x.date_of_ssa, x.average_score FROM ssa_record x
  WHERE x.school_id = s.id AND x.fy = $3 AND x.deleted_at IS NULL AND x.verification_status = 'confirmed'
  ORDER BY x.date_of_ssa DESC LIMIT 1) ssa ON TRUE
LEFT JOIN LATERAL (SELECT sco.intervention, sco.score FROM ssa_score sco WHERE sco.ssa_record_id = ssa.id
  ORDER BY sco.score, sco.intervention LIMIT 1) w ON TRUE
WHERE psa.project_id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2)`+where+`
ORDER BY p.name, s.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("projectplanning: reading the project schools: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (assignment, error) {
		var a assignment
		var score *float64
		err := row.Scan(&a.id, &a.projectID, &a.projectName, &a.projectCategory, &a.projectType,
			&a.schoolPK, &a.schoolCode, &a.schoolName, &a.schoolType, &a.districtID, &a.district, &a.regionID, &a.region,
			&a.ssaDate, &a.ssaAverage, &a.weakest, &score)
		a.weakestScore = score
		return a, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectplanning: reading the project schools: %w", err)
	}
	return out, nil
}

// activity is one piece of project work this quarter at a school.
type activity struct {
	id, projectID, schoolID, status, delivery, kind, partnerID string
	planned                                                    *time.Time
	ssaExpected                                                bool
	reschedules                                                int
}

// activities is the projects' live work of the year and quarter at a school,
// newest first.
func (s *Service) activities(ctx context.Context, ids []string, fy, quarter string) ([]activity, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.project_id, a.school_id, a.status, COALESCE(a.delivery_type, ''), a.activity_type, COALESCE(a.assigned_partner_id, ''),
  a.planned_date, COALESCE(a.ssa_collection_expected, false), COALESCE(a.reschedule_count, 0)
FROM activity a WHERE a.deleted_at IS NULL AND a.project_id = ANY($1) AND a.fy = $2 AND a.quarter = $3
  AND a.school_id IS NOT NULL AND NOT (a.status = ANY($4))
ORDER BY a.created_at DESC`, ids, fy, quarter, notPlanned)
	if err != nil {
		return nil, fmt.Errorf("projectplanning: reading the project work: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (activity, error) {
		var a activity
		err := row.Scan(&a.id, &a.projectID, &a.schoolID, &a.status, &a.delivery, &a.kind, &a.partnerID,
			&a.planned, &a.ssaExpected, &a.reschedules)
		return a, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectplanning: reading the project work: %w", err)
	}
	return out, nil
}

// handover is a project handover a partner has not dated yet.
type handover struct {
	partner   string
	scheduled *time.Time
}

// handovers is the latest open handover of each project and school.
func (s *Service) handovers(ctx context.Context, ids []string) (map[[2]string]handover, error) {
	rows, err := s.db.Query(ctx, `
SELECT h.project_id, h.school_id, COALESCE(pa.name, ''), h.scheduled_date
FROM partner_assignment h LEFT JOIN partner pa ON pa.id = h.partner_id
WHERE h.project_id = ANY($1) AND h.school_id IS NOT NULL AND h.status = ANY($2)
ORDER BY h.created_at`, ids, rules.UnscheduledHandoverStatuses)
	if err != nil {
		return nil, fmt.Errorf("projectplanning: reading the handovers: %w", err)
	}
	defer rows.Close()
	out := map[[2]string]handover{}
	for rows.Next() {
		var project, school string
		var h handover
		if err := rows.Scan(&project, &school, &h.partner, &h.scheduled); err != nil {
			return nil, fmt.Errorf("projectplanning: reading the handovers: %w", err)
		}
		out[[2]string{project, school}] = h
	}
	return out, rows.Err()
}

// names is id → name over a two-column query.
func (s *Service) names(ctx context.Context, sql string, args ...any) (map[string]string, []string, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, nil, fmt.Errorf("projectplanning: reading names: %w", err)
	}
	defer rows.Close()
	out, order := map[string]string{}, []string{}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, nil, fmt.Errorf("projectplanning: reading names: %w", err)
		}
		out[id] = name
		order = append(order, id)
	}
	return out, order, rows.Err()
}

func (s *Service) budget(ctx context.Context, ids []string) (int64, error) {
	if len(ids) == 0 {
		return 0, nil
	}
	var total int64
	err := s.db.QueryRow(ctx, `SELECT COALESCE(SUM(amount), 0) FROM activity_schedule_cost_line WHERE activity_id = ANY($1)`, ids).Scan(&total)
	if err != nil {
		return 0, fmt.Errorf("projectplanning: reading the budget: %w", err)
	}
	return total, nil
}
