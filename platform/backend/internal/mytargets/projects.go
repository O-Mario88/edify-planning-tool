package mytargets

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// projectIntro is partials/targets/project_priorities.html's paragraph.
const projectIntro = "Projects assigned by IA, the Country Director, or Admin become planning priorities. They remain separate from weighted achievement until an approved target allocation exists."

// maxCardWords is card_grids.MAX_CARD_WORDS: a card with more words is not
// read as a record.
const maxCardWords = 40

// cardWordsBesides are the words a Project card holds besides its own
// lines: the figure strip's labels and values ("Schools 2 Activities 3
// Completed 1"), its scroll hint ("Swipe for more →") and the link ("Plan
// this Project →").
const cardWordsBesides = 6 + 4 + 4

// project is one row of staff_project_priorities, as the card prints it.
type project struct {
	id, name, code, focus, responsibility string
	interventions                         []string
	schools, activities, completed        int
	byType                                map[string]int
	planningURL                           string
}

// status is the card's pill.
func (r project) status() string {
	switch {
	case r.activities > 0:
		return "In progress"
	case r.schools == 0:
		return "Schools needed"
	}
	return "Ready to plan"
}

func (r project) eyebrow() string {
	if r.code == "" {
		return "Project priority"
	}
	return r.code
}

func (r project) role() string { return r.responsibility + " · " + r.focus }

func (r project) interventionLine() string {
	if len(r.interventions) == 0 {
		return "No intervention declared"
	}
	return strings.Join(r.interventions, " · ")
}

func (r project) breakdown() string {
	parts := []string{}
	for _, t := range rules.SchoolTypes {
		if n := r.byType[t[0]]; n > 0 {
			parts = append(parts, strconv.Itoa(n)+" "+t[1])
		}
	}
	if len(parts) == 0 {
		return "No schools assigned"
	}
	return strings.Join(parts, " · ")
}

// words is the card's word count as card_grids reads it.
func (r project) words() int {
	n := cardWordsBesides
	for _, line := range []string{r.eyebrow(), r.name, r.role(), r.status(), r.interventionLine(), r.breakdown()} {
		n += len(strings.Fields(line))
	}
	return n
}

func (r project) facts() []*screensv1.PageFact {
	return []*screensv1.PageFact{{Label: "Schools", Value: strconv.Itoa(r.schools)},
		{Label: "Activities", Value: strconv.Itoa(r.activities)}, {Label: "Completed", Value: strconv.Itoa(r.completed)}}
}

// record is the card as the feed reads a grid of small cards.
func (r project) record() *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Record{Record: &screensv1.PageRecord{
		Title: r.name, Href: r.planningURL,
		Subtitle: r.eyebrow() + " · " + strings.Join([]string{r.role(), r.interventionLine(), r.breakdown(), "→"}, " "),
		Badges:   []*screensv1.PageBadge{{Text: r.status(), Tone: "plain"}},
		Facts:    r.facts(),
	}}}
}

// parts are the card as the feed reads one on its own: its name, its
// interventions, its figures and its link (the eyebrow is not read).
func (r project) parts() []*screensv1.PageBlock {
	metrics := []*screensv1.PageMetric{}
	for _, f := range r.facts() {
		metrics = append(metrics, &screensv1.PageMetric{Label: f.Label, Value: f.Value})
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: r.name, Subtitle: r.role(),
			Items: []*screensv1.PagePanelItem{text(r.status())}}}},
		textPanel("", r.interventionLine()),
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Performance overview", Metrics: metrics}}},
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			text(r.breakdown()), links(&screensv1.PageLink{Text: "Plan this Project →", Href: r.planningURL})}}}},
	}
}

// projectPriorities is staff_project_priorities as
// partials/targets/project_priorities.html draws it. Several cards are read
// as records only while each is a small card; otherwise the feed reads
// them apart, and that is handed on.
func projectPriorities(ctx context.Context, db schooldirectory.Querier, pg *page) ([]*screensv1.PageBlock, error) {
	rows, err := assignedProjects(ctx, db, pg)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "Assigned Project Priorities", Subtitle: projectIntro,
			Items: []*screensv1.PagePanelItem{text("No Projects assigned as priorities"),
				text("When IA, the Country Director, or Admin assigns a Project, it will appear here with its eligible school-planning action.")},
		}}}}, nil
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Assigned Project Priorities",
		Items: []*screensv1.PagePanelItem{text("Assigned execution portfolio"), text(projectIntro)},
	}}}}
	if len(rows) == 1 {
		return append(out, rows[0].parts()...), nil
	}
	for _, r := range rows {
		if r.words() > maxCardWords {
			return nil, fmt.Errorf("a long Project card: %w", errPassOn)
		}
		out = append(out, r.record())
	}
	return out, nil
}

// assignedProjects is project_priorities_for_users for the reader: their
// active assignments of the year to a live Project, by the Project's name,
// each with the Project's schools in the reader's portfolio (their own and
// their supervisees') and the Project's activities of the year the reader
// is responsible for or monitors.
func assignedProjects(ctx context.Context, db schooldirectory.Querier, pg *page) ([]project, error) {
	staffID, fy := pg.p.StaffProfileID, pg.fy
	if staffID == "" {
		return nil, nil
	}
	rows, err := db.Query(ctx, `
SELECT p.id, p.name, coalesce(p.code, ''), p.school_focus, a.responsibility,
       coalesce(p.target_interventions, '[]'::jsonb), coalesce(p.intervention, '')
FROM project_staff_assignment a JOIN project p ON p.id = a.project_id
WHERE a.staff_id = $1 AND a.fy = $2 AND a.is_active AND p.deleted_at IS NULL AND p.status = ANY($3)
ORDER BY p.name, a.id`, staffID, fy, rules.LiveProjectStatuses)
	if err != nil {
		return nil, fmt.Errorf("mytargets: the assigned Projects: %w", err)
	}
	defer rows.Close()
	var out []project
	for rows.Next() {
		var r project
		var focus, responsibility, intervention string
		var targeted []string
		if err := rows.Scan(&r.id, &r.name, &r.code, &focus, &responsibility, &targeted, &intervention); err != nil {
			return nil, fmt.Errorf("mytargets: the assigned Projects: %w", err)
		}
		r.focus = display(rules.SchoolFocusLabels, focus)
		r.responsibility = display(rules.ResponsibilityLabels, responsibility)
		if intervention != "" && !slices.Contains(targeted, intervention) {
			targeted = append(targeted, intervention)
		}
		for _, code := range targeted {
			label, ok := rules.InterventionLabels[code]
			if !ok {
				label = pyTitle(strings.ReplaceAll(code, "_", " "))
			}
			r.interventions = append(r.interventions, label)
		}
		r.byType = map[string]int{}
		r.planningURL = "/projects/planning?project=" + r.id + "&fy=" + fy
		out = append(out, r)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("mytargets: the assigned Projects: %w", err)
	}
	if len(out) == 0 {
		return nil, nil
	}
	if len(out) > pageRows {
		return nil, fmt.Errorf("many Projects: %w", errPassOn)
	}
	byID := map[string]*project{}
	ids := []string{}
	for i := range out {
		byID[out[i].id] = &out[i]
		ids = append(ids, out[i].id)
	}
	if err := projectSchools(ctx, db, staffID, ids, byID); err != nil {
		return nil, err
	}
	if err := projectActivities(ctx, db, pg, ids, byID); err != nil {
		return nil, err
	}
	return out, nil
}

func projectSchools(ctx context.Context, db schooldirectory.Querier, staffID string, ids []string, byID map[string]*project) error {
	rows, err := db.Query(ctx, `
WITH portfolio AS (
  SELECT school_id FROM staff_school_assignment
  WHERE staff_id = $1 OR staff_id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1))
SELECT psa.project_id, coalesce(s.school_type, ''), count(*)
FROM project_school_assignment psa JOIN school s ON s.id = psa.school_id
WHERE psa.project_id = ANY($2) AND psa.school_id IN (SELECT school_id FROM portfolio)
GROUP BY 1, 2`, staffID, ids)
	if err != nil {
		return fmt.Errorf("mytargets: the Projects' schools: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, kind string
		var n int
		if err := rows.Scan(&id, &kind, &n); err != nil {
			return fmt.Errorf("mytargets: the Projects' schools: %w", err)
		}
		byID[id].schools += n
		byID[id].byType[kind] += n
	}
	return rows.Err()
}

func projectActivities(ctx context.Context, db schooldirectory.Querier, pg *page, ids []string, byID map[string]*project) error {
	owners := []string{pg.p.StaffProfileID, pg.p.UserID}
	rows, err := db.Query(ctx, `
SELECT project_id, count(*), count(*) FILTER (WHERE status = ANY($4))
FROM activity
WHERE project_id = ANY($1) AND fy = $2 AND deleted_at IS NULL
  AND (responsible_staff_id = ANY($3) OR monitored_by_staff_id = ANY($3))
GROUP BY project_id`, ids, pg.fy, owners, rules.ProjectCompletedStates)
	if err != nil {
		return fmt.Errorf("mytargets: the Projects' activities: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var planned, completed int
		if err := rows.Scan(&id, &planned, &completed); err != nil {
			return fmt.Errorf("mytargets: the Projects' activities: %w", err)
		}
		byID[id].activities, byID[id].completed = planned, completed
	}
	return rows.Err()
}

// display is a choice's label (get_FOO_display), or the stored value.
func display(labels map[string]string, value string) string {
	if label, ok := labels[value]; ok {
		return label
	}
	return value
}
