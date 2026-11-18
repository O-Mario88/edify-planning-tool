package schoolprofile

import (
	"context"
	"fmt"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Projects tab of a profile of many schools (profile_intelligence.
// _projects): each project with schools in the scope, its size against the
// capacity set for it, its work at these schools and how their SSA moved.

// scopeProject is one project's row.
type scopeProject struct {
	id, name, status   string
	schools            []string
	projectSchools     int
	capacity           *int
	planned, completed int
	current, previous  *float64
	verdict            change
	improved, declined int
}

const projectsNote = "Project Schools is every school on the project, wherever it is; Capacity is the schools its coordinator " +
	"allows the people who add schools to it, added up, and blank where none is set. Work is the project's activities at " +
	"this portfolio's schools."

func (s *Service) scopeProjects(ctx context.Context, pr *scopeProfile, l lens) ([]scopeProject, error) {
	ids := idsOf(pr.schools)
	rows, err := s.db.Query(ctx, `
SELECT p.id, p.name, COALESCE(p.status, ''), psa.school_id
FROM project_school_assignment psa JOIN project p ON p.id = psa.project_id
WHERE psa.school_id = ANY($1) ORDER BY p.name, p.id`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the profile's projects: %w", err)
	}
	out := []scopeProject{}
	at := map[string]int{}
	for rows.Next() {
		var id, name, status, school string
		if err := rows.Scan(&id, &name, &status, &school); err != nil {
			rows.Close()
			return nil, err
		}
		i, ok := at[id]
		if !ok {
			i = len(out)
			at[id] = i
			out = append(out, scopeProject{id: id, name: name, status: status})
		}
		if !contains(out[i].schools, school) {
			out[i].schools = append(out[i].schools, school)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(out) == 0 {
		return out, err
	}
	projectIDs := make([]string, len(out))
	for i, p := range out {
		projectIDs[i] = p.id
	}
	rows, err = s.db.Query(ctx, `
SELECT project_id, count(DISTINCT school_id) FROM project_school_assignment WHERE project_id = ANY($1) GROUP BY 1`, projectIDs)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the projects' schools: %w", err)
	}
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			rows.Close()
			return nil, err
		}
		out[at[id]].projectSchools = n
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `
SELECT project_id, sum(max_schools) FROM project_staff_capacity WHERE project_id = ANY($1) GROUP BY 1`, projectIDs)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the projects' capacity: %w", err)
	}
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			rows.Close()
			return nil, err
		}
		out[at[id]].capacity = &n
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	args := []any{projectIDs, ids, l.fy, rules.Engine.NotInPlanStatuses, rules.Engine.CompletedWorkStatuses}
	inWindow := l.window.sql(&args)
	rows, err = s.db.Query(ctx, `
SELECT a.project_id, count(a.id), count(a.id) FILTER (WHERE a.status = ANY($5))
FROM activity a WHERE a.project_id = ANY($1) AND a.school_id = ANY($2) AND a.fy = $3 AND a.deleted_at IS NULL
  AND NOT (a.status = ANY($4)) AND `+inWindow+` GROUP BY 1`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the projects' work: %w", err)
	}
	for rows.Next() {
		var id string
		var planned, done int
		if err := rows.Scan(&id, &planned, &done); err != nil {
			rows.Close()
			return nil, err
		}
		out[at[id]].planned, out[at[id]].completed = planned, done
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for i := range out {
		p := &out[i]
		current, previous := []*float64{}, []*float64{}
		for _, school := range p.schools {
			score := pr.scores[school]
			current, previous = append(current, score.current), append(previous, score.previous)
			switch pr.verdicts[school].status {
			case "improved":
				p.improved++
			case "declined":
				p.declined++
			}
		}
		p.current, p.previous = pyMean(current), pyMean(previous)
		p.verdict = pr.book.overallChange(p.previous, p.current)
	}
	return out, nil
}

// projectsBlocks is the Projects tab's table, fifty a page.
func projectsBlocks(l lens, projects []scopeProject, openProjects bool) []*screensv1.PageBlock {
	yearLabel, previousLabel := fyLabel(l.fy), fyLabel(previousFY(l.fy))
	t := &screensv1.PageTable{Title: "Projects", Subtitle: itoa(len(projects)) + " project" + plural(len(projects)) + " · " + yearLabel}
	if len(projects) == 0 {
		t.EmptyMessage = "No project has a school in this portfolio."
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	}
	t.Columns = []*screensv1.PageColumn{{Label: "Project"}, {Label: "Status"}, {Label: "Schools Here", Numeric: true},
		{Label: "Project Schools", Numeric: true}, {Label: "Capacity", Numeric: true}, {Label: "Capacity Left", Numeric: true},
		{Label: "Work Planned", Numeric: true}, {Label: "Work Completed", Numeric: true}, {Label: previousLabel, Numeric: true},
		{Label: yearLabel, Numeric: true}, {Label: "Change", Numeric: true}, {Label: "Improved", Numeric: true}, {Label: "Declined", Numeric: true}}
	page := tablepager.Paginate(len(projects), tablePageSize, l.query, "projects_page")
	for _, p := range projects[page.Start:page.End] {
		name := &screensv1.PageCell{Text: p.name}
		if openProjects {
			name.Href = "/projects/monitoring?project=" + p.id
		}
		capacity, left := "—", "—"
		if p.capacity != nil {
			capacity = intcomma(*p.capacity)
			left = intcomma(max(*p.capacity-p.projectSchools, 0))
		}
		changeCell := &screensv1.PageCell{Text: "—"}
		if p.verdict.delta != nil {
			changeCell = &screensv1.PageCell{Text: signedTwoPlaces(*p.verdict.delta), Tone: p.verdict.tone()}
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			name, {Text: projectStatus(p.status)}, {Text: intcomma(len(p.schools))}, {Text: intcomma(p.projectSchools)},
			{Text: capacity}, {Text: left}, {Text: intcomma(p.planned)}, {Text: intcomma(p.completed)},
			{Text: score(p.previous)}, {Text: score(p.current), Strong: true}, changeCell,
			{Text: intcomma(p.improved)}, {Text: intcomma(p.declined)},
		}})
	}
	t.Footnote = projectsNote
	if page.Pager != nil {
		t.Pager, t.Footnote = page.Pager, page.Pager.Summary
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
}
