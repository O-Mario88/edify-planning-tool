package planningoversight

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
)

// flagged_schools.team_flagged_schools for the team: the schools the team
// plans at in the month, each under its highest unresolved problem as
// urgent_attention.resolve_urgent_issue classifies it, grouped by the
// officer who owns the first visit. A school whose problem is the
// recommendation engine's (SSA, visit and training all in) is not drawn
// here yet: the page is handed on.

const (
	flaggedOwnersPerPage = 5
	tablePageSize        = 50
)

type flaggedRow struct {
	pk, code, name, district, key, label, severity string
	planned                                        *time.Time
	delegated                                      bool
}

type flaggedGroup struct {
	owner, name         string
	rows                []flaggedRow
	critical, delegated int
}

type flaggedSchools struct {
	groups []flaggedGroup
	total  int
}

// monthBounds is the month the flagged schools read: the chosen month,
// else today's, of the page's year.
func monthBounds(per partneroversight.Period, now time.Time) (string, time.Time, time.Time) {
	month := int(now.In(zone).Month())
	if per.Kind == "month" {
		month = per.Month
	}
	year, _ := strconv.Atoi(per.FY)
	if month < 10 {
		year++
	}
	first := time.Date(year-1, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
	return per.FY, first, first.AddDate(0, 1, 0)
}

// flaggedFor is team_flagged_schools (team nil: the country's); errHandOn
// where a school's problem is the recommendation engine's.
func (s *Service) flaggedFor(ctx context.Context, team []string, per partneroversight.Period, now time.Time) (flaggedSchools, error) {
	fy, start, end := monthBounds(per, now)
	rows, err := s.db.Query(ctx, `
SELECT a.school_id, COALESCE(a.responsible_staff_id, ''), a.planned_date,
  COALESCE(s.school_id, ''), COALESCE(s.name, ''), s.school_type, COALESCE(d.name, '')
FROM activity a JOIN school s ON s.id = a.school_id LEFT JOIN district d ON d.id = s.district_id
WHERE a.fy = $1 AND a.planned_date >= $2::date AND a.planned_date < $3::date AND a.deleted_at IS NULL
  AND (a.status IS NULL OR NOT a.status = ANY($4)) AND ($5::text[] IS NULL OR a.responsible_staff_id = ANY($5))
ORDER BY a.planned_date, a.id`, fy, start, end, rules.TeamPlan.NotPlannedStatuses, team)
	if err != nil {
		return flaggedSchools{}, fmt.Errorf("planningoversight: reading the month's planned schools: %w", err)
	}
	type school struct {
		pk, owner, code, name, district string
		schoolType                      *string
		planned                         *time.Time
	}
	order, firstOf := []string{}, map[string]school{}
	for rows.Next() {
		var sc school
		if err := rows.Scan(&sc.pk, &sc.owner, &sc.planned, &sc.code, &sc.name, &sc.schoolType, &sc.district); err != nil {
			rows.Close()
			return flaggedSchools{}, fmt.Errorf("planningoversight: reading the month's planned schools: %w", err)
		}
		if _, seen := firstOf[sc.pk]; !seen {
			firstOf[sc.pk] = sc
			order = append(order, sc.pk)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return flaggedSchools{}, err
	}
	if len(order) == 0 {
		return flaggedSchools{}, nil
	}
	f := rules.TeamPlan.Flagged
	delegated, err := s.idSet(ctx, `SELECT DISTINCT school_id FROM team_action WHERE school_id = ANY($1) AND fy = $2 AND state = ANY($3)`, order, fy, f.ActiveActionStates)
	if err != nil {
		return flaggedSchools{}, err
	}
	ssa, err := s.idSet(ctx, `SELECT DISTINCT school_id FROM ssa_record WHERE school_id = ANY($1) AND fy = $2 AND verification_status = 'confirmed' AND deleted_at IS NULL`, order, fy)
	if err != nil {
		return flaggedSchools{}, err
	}
	visited, err := s.idSet(ctx, `SELECT DISTINCT school_id FROM activity WHERE school_id = ANY($1) AND activity_type = ANY($2) AND fy = $3 AND status = ANY($4) AND deleted_at IS NULL`,
		order, f.VisitTypes, fy, f.IAVerifiedStatuses)
	if err != nil {
		return flaggedSchools{}, err
	}
	trained, err := s.idSet(ctx, `
SELECT a.school_id FROM activity a WHERE a.school_id = ANY($1) AND a.activity_type = ANY($2) AND a.status = ANY($3)
  AND a.deleted_at IS NULL AND a.fy = $6
UNION SELECT c.school_id FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
  WHERE c.school_id = ANY($1) AND c.attended AND a.activity_type = ANY($4) AND a.status = ANY($5) AND a.deleted_at IS NULL AND a.fy = $6
UNION SELECT x FROM activity a, unnest(a.attended_school_ids) x
  WHERE a.activity_type = ANY($4) AND a.status = ANY($5) AND a.deleted_at IS NULL AND a.fy = $6 AND x = ANY($1)`,
		order, f.SchoolTrainingTypes, f.SchoolTrainingDoneStatuses, f.ClusterTrainingTypes, f.ClusterCreditStatuses, fy)
	if err != nil {
		return flaggedSchools{}, err
	}
	owners := []string{}
	for _, pk := range order {
		owners = append(owners, firstOf[pk].owner)
	}
	names, err := s.staffNames(ctx, owners)
	if err != nil {
		return flaggedSchools{}, err
	}
	out := flaggedSchools{}
	index := map[[2]string]int{}
	for _, pk := range order {
		sc := firstOf[pk]
		row := flaggedRow{pk: pk, code: sc.code, name: sc.name, district: sc.district, planned: sc.planned, delegated: delegated[pk]}
		visit := visited[pk]
		training := trained[pk] || (sc.schoolType != nil && !slices.Contains(f.TrainedTypes, *sc.schoolType))
		switch {
		case !ssa[pk]:
			row.key, row.label, row.severity = "no_ssa", "No SSA", "critical"
		case !visit && !training:
			row.key, row.label, row.severity = "no_visit_or_training", "No Visit or Training", "critical"
		case !training:
			row.key, row.label, row.severity = "no_training", "No Training", "high"
		case !visit:
			row.key, row.label, row.severity = "no_visit", "No Visit", "high"
		default:
			return flaggedSchools{}, errHandOn
		}
		owner := sc.owner
		name := first(names[owner].name, "Unassigned")
		key := [2]string{owner, name}
		i, ok := index[key]
		if !ok {
			i = len(out.groups)
			index[key] = i
			out.groups = append(out.groups, flaggedGroup{owner: owner, name: name})
		}
		g := &out.groups[i]
		g.rows = append(g.rows, row)
		if row.severity == "critical" {
			g.critical++
		}
		if row.delegated {
			g.delegated++
		}
		out.total++
	}
	for i := range out.groups {
		slices.SortStableFunc(out.groups[i].rows, func(x, y flaggedRow) int {
			if c := f.Precedence[x.key] - f.Precedence[y.key]; c != 0 {
				return c
			}
			if c := compareDay(x.planned, y.planned); c != 0 {
				return c
			}
			return compareText(x.name, y.name)
		})
	}
	slices.SortStableFunc(out.groups, func(x, y flaggedGroup) int {
		if x.critical != y.critical {
			return y.critical - x.critical
		}
		if len(x.rows) != len(y.rows) {
			return len(y.rows) - len(x.rows)
		}
		return compareText(x.name, y.name)
	})
	if len(out.groups) > flaggedOwnersPerPage {
		return flaggedSchools{}, errHandOn
	}
	for _, g := range out.groups {
		if len(g.rows) > tablePageSize {
			return flaggedSchools{}, errHandOn
		}
	}
	return out, nil
}

// compareText is Python's str ordering (by code point).
func compareText(a, b string) int {
	ra, rb := []rune(a), []rune(b)
	for i := 0; i < len(ra) && i < len(rb); i++ {
		if ra[i] != rb[i] {
			return int(ra[i]) - int(rb[i])
		}
	}
	return len(ra) - len(rb)
}

func (s *Service) idSet(ctx context.Context, sql string, args ...any) (map[string]bool, error) {
	out := map[string]bool{}
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the schools' support: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id *string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the schools' support: %w", err)
		}
		if id != nil {
			out[*id] = true
		}
	}
	return out, rows.Err()
}

func plural(n int, one, many string) string {
	if n == 1 {
		return strconv.Itoa(n) + " " + one
	}
	return strconv.Itoa(n) + " " + many
}

// flaggedBlocks is flagged_schools.html.
func flaggedBlocks(f flaggedSchools, r Reader) []*screensv1.PageBlock {
	if len(f.groups) == 0 {
		return []*screensv1.PageBlock{panel(flaggedTitle, flaggedSubtitle, text(flaggedNone))}
	}
	blocks := []*screensv1.PageBlock{panel(flaggedTitle, flaggedSubtitle,
		text(plural(f.total, "school", "schools")+" · "+plural(len(f.groups), "staff member", "staff members")))}
	for _, g := range f.groups {
		line := strconv.Itoa(len(g.rows)) + " flagged"
		if g.critical > 0 {
			line += " · " + strconv.Itoa(g.critical) + " critical"
		}
		if g.delegated > 0 {
			line += " · " + strconv.Itoa(g.delegated) + " already assigned"
		}
		rows := []*screensv1.PageRow{}
		for _, row := range g.rows {
			code := row.code
			if code == "" {
				code = "ID unavailable"
			}
			school := row.name
			if row.district != "" {
				school += " " + row.district
			}
			schoolCell := &screensv1.PageCell{Text: school}
			if r.OpenSchool {
				schoolCell.Href = "/schools/" + row.pk
			}
			planned := "—"
			if row.planned != nil {
				planned = strconv.Itoa(row.planned.Day()) + " " + row.planned.Month().String()[:3]
			}
			status := "Not yet assigned"
			if row.delegated {
				status = "Assigned"
			}
			rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: code}, schoolCell, {Text: row.label}, {Text: planned}, {Text: status},
			}})
		}
		blocks = append(blocks, panel("", "", text(g.name), text(line)), &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Columns: columns("School ID", "School", "Issue", "Planned", "Status"),
			Rows:    rows,
		}}})
	}
	return blocks
}

func columns(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, len(labels))
	for i, l := range labels {
		out[i] = &screensv1.PageColumn{Label: l}
	}
	return out
}
