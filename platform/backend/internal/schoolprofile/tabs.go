package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// errTooLong: a table longer than a page, which the web pages and Go does
// not yet; the profile is passed to the existing application.
var errTooLong = errors.New("schoolprofile: a table longer than a page")

// status is profile_records._status: "in_review" is "In review".
func status(value string) string {
	s := strings.ToLower(strings.ReplaceAll(value, "_", " "))
	if s == "" {
		return ""
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

// ── Projects (the engine's _projects) ──────────────────────────────────────

func (s *Service) projectsTab(ctx context.Context, d doors, sc school, l lens) ([]*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `
SELECT psa.project_id, COALESCE(p.name, ''), COALESCE(p.status, '')
FROM project_school_assignment psa LEFT JOIN project p ON p.id = psa.project_id
WHERE psa.school_id = $1 ORDER BY p.name, psa.project_id`, sc.ID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading projects: %w", err)
	}
	projects := []*projectRow{}
	byID := map[string]*projectRow{}
	for rows.Next() {
		p := &projectRow{}
		if err := rows.Scan(&p.id, &p.name, &p.status); err != nil {
			rows.Close()
			return nil, err
		}
		if byID[p.id] == nil {
			byID[p.id] = p
			projects = append(projects, p)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(projects) > maxRows {
		return nil, errTooLong
	}
	table := recordTable{
		title:   "Projects",
		summary: fmt.Sprintf("%d project%s · %s", len(projects), plural(len(projects)), fyLabel(l.fy)),
		empty:   "No project has a school in this portfolio.",
		footer: "Project Schools is every school on the project, wherever it is; Capacity is the schools its coordinator " +
			"allows the people who add schools to it, added up, and blank where none is set. Work is the project's " +
			"activities at this portfolio's schools.",
		columns: [][2]string{{"Project", ""}, {"Status", ""}, {"Schools Here", "num"}, {"Project Schools", "num"},
			{"Capacity", "num"}, {"Capacity Left", "num"}, {"Work Planned", "num"}, {"Work Completed", "num"},
			{fyLabel(previousFY(l.fy)), "num"}, {fyLabel(l.fy), "num"}, {"Change", "num"}, {"Improved", "num"}, {"Declined", "num"}},
	}
	if len(projects) > 0 {
		ids := []string{}
		for _, p := range projects {
			ids = append(ids, p.id)
		}
		if err := s.projectFigures(ctx, sc, l, ids, byID); err != nil {
			return nil, err
		}
		scores, err := s.schoolYearScores(ctx, []string{sc.ID}, l.fy)
		if err != nil {
			return nil, err
		}
		book, err := s.ruleBook(ctx)
		if err != nil {
			return nil, err
		}
		mine, hasScore := scores[sc.ID]
		for _, p := range projects {
			if hasScore {
				p.previous, p.current = pyMean([]*float64{mine.previous}), pyMean([]*float64{mine.current})
				switch book.overallChange(mine.previous, mine.current).status {
				case "improved":
					p.improved = 1
				case "declined":
					p.declined = 1
				}
			}
			p.verdict = book.overallChange(p.previous, p.current)
			name := textCell(p.name, "")
			if d.OpenProjects {
				name.href = "/projects/monitoring?project=" + p.id
			}
			capacity, left := cell{text: "—"}, cell{text: "—"}
			if p.capacity != nil {
				capacity = cell{text: intcomma(*p.capacity)}
				left = cell{text: intcomma(max(*p.capacity-p.total, 0))}
			}
			changeCell := cell{text: "—"}
			if p.verdict.delta != nil {
				changeCell = cell{text: signedTwoPlaces(*p.verdict.delta), tone: p.verdict.tone()}
			}
			table.rows = append(table.rows, []cell{
				name, textCell(projectStatus(p.status), ""), {text: "1"}, {text: intcomma(p.total)},
				capacity, left, {text: intcomma(p.planned)}, {text: intcomma(p.completed)},
				{text: score(p.previous)}, {text: score(p.current), strong: true}, changeCell,
				{text: intcomma(p.improved)}, {text: intcomma(p.declined)},
			})
		}
	}
	return []*screensv1.PageBlock{table.block()}, nil
}

// projectStatus is str(status).replace("_", " ").title().
func projectStatus(value string) string {
	words := strings.Fields(strings.ReplaceAll(value, "_", " "))
	for i, w := range words {
		words[i] = strings.ToUpper(w[:1]) + strings.ToLower(w[1:])
	}
	return strings.Join(words, " ")
}

// projectRow is one project working at the school.
type projectRow struct {
	id, name, status          string
	total, planned, completed int
	capacity                  *int
	previous, current         *float64
	verdict                   change
	improved, declined        int
}

// projectFigures fills each project's size (every school on it), the
// capacity its coordinator set (added up; none where none is set), and its
// work at the school this year, in the plan and completed.
func (s *Service) projectFigures(ctx context.Context, sc school, l lens, ids []string, byID map[string]*projectRow) error {
	rows, err := s.db.Query(ctx, `
SELECT project_id, COUNT(DISTINCT school_id) FROM project_school_assignment WHERE project_id = ANY($1) GROUP BY 1`, ids)
	if err != nil {
		return fmt.Errorf("schoolprofile: reading project sizes: %w", err)
	}
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			rows.Close()
			return err
		}
		byID[id].total = n
	}
	rows.Close()
	rows, err = s.db.Query(ctx, `
SELECT project_id, SUM(max_schools) FROM project_staff_capacity WHERE project_id = ANY($1) GROUP BY 1`, ids)
	if err != nil {
		return fmt.Errorf("schoolprofile: reading project capacity: %w", err)
	}
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			rows.Close()
			return err
		}
		byID[id].capacity = &n
	}
	rows.Close()
	args := []any{ids, sc.ID, l.fy, rules.Engine.NotInPlanStatuses, rules.Engine.CompletedWorkStatuses}
	inWindow := l.window.sql(&args)
	rows, err = s.db.Query(ctx, `
SELECT a.project_id, COUNT(a.id), COUNT(a.id) FILTER (WHERE a.status = ANY($5))
FROM activity a
WHERE a.project_id = ANY($1) AND a.school_id = $2 AND a.fy = $3 AND a.deleted_at IS NULL
  AND NOT (a.status = ANY($4)) AND `+inWindow+`
GROUP BY 1`, args...)
	if err != nil {
		return fmt.Errorf("schoolprofile: reading project work: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var planned, completed int
		if err := rows.Scan(&id, &planned, &completed); err != nil {
			return err
		}
		byID[id].planned, byID[id].completed = planned, completed
	}
	return rows.Err()
}

// ── Stories (profile_records.stories and _story_tables) ────────────────────

func (s *Service) storiesTab(ctx context.Context, sc school, l lens) ([]*screensv1.PageBlock, error) {
	end, _ := strconv.Atoi(l.fy)
	start, stop := time.Date(end-1, 10, 1, 0, 0, 0, 0, time.UTC), time.Date(end, 10, 1, 0, 0, 0, 0, time.UTC)
	rows, err := s.db.Query(ctx, `
SELECT st.story_date, COALESCE(st.title, ''), COALESCE(sch.school_id, ''), COALESCE(sch.name, ''), COALESCE(st.school_id, ''),
  COALESCE(st.intervention, ''), COALESCE(st.outcome_area, ''), st.status, COALESCE(st.evidence_uri, '') <> ''
FROM mscs_story st LEFT JOIN school sch ON sch.id = st.school_id
WHERE (st.school_id = $1 OR (st.school_id IS NULL AND st.cluster_id = (
    SELECT c.id FROM cluster c WHERE c.id = $2 AND c.deleted_at IS NULL)))
  AND st.story_date >= $3::date AND st.story_date < $4::date AND st.status <> $5
ORDER BY st.story_date DESC, st.created_at DESC, st.id`, sc.ID, sc.ClusterID, start, stop, rules.Engine.StoryStatuses.Draft)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading stories: %w", err)
	}
	type story struct {
		day                                              time.Time
		title, code, schoolName, schoolID, area, outcome string
		state                                            string
		evidence                                         bool
	}
	stories, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (story, error) {
		var st story
		err := row.Scan(&st.day, &st.title, &st.code, &st.schoolName, &st.schoolID, &st.area, &st.outcome, &st.state, &st.evidence)
		return st, err
	})
	if err != nil {
		return nil, err
	}
	if len(stories) > maxRows {
		return nil, errTooLong
	}
	approved, waiting := 0, 0
	areas := map[string]int{}
	for _, st := range stories {
		if st.state == rules.Engine.StoryStatuses.Approved {
			approved++
		}
		for _, w := range rules.Engine.StoryStatuses.Waiting {
			if st.state == w {
				waiting++
			}
		}
		area := rules.SSAInterventions[st.area]
		if area == "" {
			area = "No intervention tagged"
		}
		areas[area]++
	}
	blocks := []*screensv1.PageBlock{strip("Most Significant Change Stories",
		kpi{label: "Stories", value: intcomma(len(stories)), link: "#profile-records-stories", helper: fyLabel(l.fy)},
		kpi{label: "Approved", value: intcomma(approved), link: l.records() + "stories_approved", helper: "count as evidence"},
		kpi{label: "With A Reviewer", value: intcomma(waiting), link: "#profile-records-stories", helper: "submitted or returned"},
	)}
	if len(areas) > 0 {
		// "By intervention: 2 Leadership · 1 Enrolment", most first, then by
		// name; the page blocks read the line as a panel of its own.
		names := make([]string, 0, len(areas))
		for name := range areas {
			names = append(names, name)
		}
		sort.Slice(names, func(i, j int) bool {
			if areas[names[i]] != areas[names[j]] {
				return areas[names[i]] > areas[names[j]]
			}
			return names[i] < names[j]
		})
		parts := []string{}
		for _, name := range names {
			parts = append(parts, intcomma(areas[name])+" "+name)
		}
		blocks = append(blocks, panelBlock(&screensv1.PagePanel{
			Badges: []*screensv1.PageBadge{},
			Items:  []*screensv1.PagePanelItem{text("By intervention: " + strings.Join(parts, " · "))},
		}))
	}
	table := recordTable{
		title:   "Most Significant Change stories",
		summary: recordsSummary(len(stories), l),
		empty:   "No record yet: the figure is 0.",
		footer:  "Only an approved story counts as evidence.",
		columns: [][2]string{{"Story Date", "date"}, {"Title", ""}, {"School ID", ""}, {"School", ""},
			{"Intervention", ""}, {"Outcome Area", ""}, {"Status", ""}, {"Evidence", ""}},
	}
	for _, st := range stories {
		schoolHref := ""
		if st.schoolID != "" {
			schoolHref = "/schools/" + st.schoolID
		}
		tone := ""
		if st.state == rules.Engine.StoryStatuses.Approved {
			tone = "success"
		}
		evidence := "No"
		if st.evidence {
			evidence = "Yes"
		}
		table.rows = append(table.rows, []cell{
			{text: jMY(st.day)}, textCell(st.title, ""), textCell(st.code, ""), textCell(st.schoolName, schoolHref),
			textCell(rules.SSAInterventions[st.area], ""), textCell(status(st.outcome), ""),
			{text: orDash(status(st.state)), tone: tone}, {text: evidence},
		})
	}
	return append(blocks, table.block()), nil
}

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}
