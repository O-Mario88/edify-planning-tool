package myplan

import (
	"context"
	"fmt"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// ReadinessRules are what Planned and remaining's lists are named by
// (planning_monitor.GAP_LABELS: the schools behind each figure).
type ReadinessRules struct {
	GapLabels map[string]string `json:"gap_labels"`
}

// visitTarget is staff_plan.visits_target (rules.planning_role, then
// target_for): a Programme Lead before a CCEO, the role in use read as held.
func visitTarget(p auth.Principal) int {
	held := append([]string{p.ActiveRole}, p.Roles...)
	switch {
	case in(held, rules.ProgramLeadRole):
		return rules.VisitTargets[rules.ProgramLeadRole]
	case in(held, rules.CCEORole):
		return rules.VisitTargets[rules.CCEORole]
	}
	return 0
}

// plannerHoldsAnything is, beside holdsAnything, what a planner's Planned
// and remaining reads that Go does not count yet: a project ceiling set for
// them, or a school they added to a project
// (planning_monitor._count_project_places). A planner Go answers has
// neither and holds no school, so every figure but the target and their
// own visits is 0.
func plannerHoldsAnything(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (bool, error) {
	var held bool
	err := db.QueryRow(ctx, `SELECT
    EXISTS (SELECT 1 FROM project_staff_capacity c WHERE c.staff_id = ANY($1))
 OR EXISTS (SELECT 1 FROM project_school_assignment pa WHERE pa.assigned_staff_id = ANY($1))`, ownerIDs(p)).Scan(&held)
	if err != nil {
		return false, fmt.Errorf("myplan: reading what the planner holds: %w", err)
	}
	return held, nil
}

// lastValue is QueryDict.get: the key's last value, "" when absent.
func (q Query) lastValue(key string) (string, bool) {
	value, found := "", false
	for i, k := range q.keys {
		if k == key {
			value, found = q.values[i], true
		}
	}
	return value, found
}

// readinessList is the key of the list asked for (`?list=`, stripped) when
// Planned and remaining draws one (_readiness_list: a key of GAP_LABELS).
func readinessList(request Query) string {
	raw, _ := request.lastValue("list")
	key := closedschools.PyStrip(raw)
	if _, ok := rules.Readiness.GapLabels[key]; !ok {
		return ""
	}
	return key
}

// readinessCell is _readiness_count.html for a figure with a list behind it:
// a zero is a muted 0, anything else opens the list under the table.
func readinessCell(n int, key, tone string, request Query) *screensv1.PageCell {
	if n == 0 {
		return &screensv1.PageCell{Text: "0"}
	}
	href := request.With("list", key).Without("list_page").String(request) + "#plan-list"
	return &screensv1.PageCell{Text: comma(n), Href: href, Tone: tone}
}

// emptyReadiness is Planned and remaining (partials/my_plan/readiness.html)
// for a planner who holds no school and has planned nothing: their visits
// against the role's target, and the five other parts asking nothing.
// fy is the year as sent (my_plan_readiness_view: request.GET["fy"]).
func emptyReadiness(target int, fy string, request Query) *screensv1.PageBlock {
	return readinessTable(target, 0, fy, request)
}

// readinessTable is Planned and remaining for a planner who holds no school
// and has planned visits of which none is past the target: Your visits
// counts them (staff_plan.visit_tallies over the year as sent).
func readinessTable(target, planned int, fy string, request Query) *screensv1.PageBlock {
	none := func(label string) *screensv1.PageRow {
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: label}, {Text: "0"}, {Text: "None required"}, {Text: "0"}, {Text: "100%", Tone: "neutral"},
		}}
	}
	// Line.percent stops at 100 and is rounded down; its tone (Line.tone).
	percent := min(100, max(0, planned*100/target))
	tone := "warning"
	switch {
	case target-planned == 0:
		tone = "success"
	case percent >= 50:
		tone = "info"
	}
	rows := []*screensv1.PageRow{
		{Cells: []*screensv1.PageCell{
			{Text: "Your visits"}, readinessCell(planned, "staff_scheduled", "", request),
			readinessCell(target, "staff_queue", "", request),
			readinessCell(target-planned, "staff_visits_left", "warning", request),
			{Text: fmt.Sprintf("%d%%", percent), Tone: tone},
		}},
		none("Schools in training in-school and group trainings"),
		none("Partner visits dated by Partners"),
		none("Core partner trainings"),
		none("Schools assigned to a Partner"),
		none("Schools assigned to a project those you added, of your project ceilings put together"),
	}
	// Each part's share stops at 100; readiness is their plain average,
	// rounded down: the visits part at 0 and three parts asking nothing.
	score := (percent + 100 + 100 + 100) / 4
	t := comma(target)
	footnote := "Your target is " + t + " visit" + pluralS(target) + " a year. You have scheduled visits at 0 of your schools yourself. " +
		"Your schools take 0 of those " + t + " visits: recruit " + t + " more school" + pluralS(target) + " to meet your target. " +
		"No project ceiling is set for you, so no project target is asked of you. " +
		"Readiness is the average of your visits, schools in training, schools with a Partner and schools added to projects."
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:    closedschools.PyCollapse("Planned and remaining · FY " + fy),
		Subtitle: fmt.Sprintf("Readiness %d%% · 0 schools held", score),
		Columns: []*screensv1.PageColumn{
			{Label: "Part of the plan"}, {Label: "Planned", Numeric: true}, {Label: "Target", Numeric: true},
			{Label: "Remaining", Numeric: true}, {Label: "Share", Numeric: true},
		},
		Rows: rows, Footnote: footnote,
	}}}
}

// emptyReadinessList is readiness_list.html for a planner who holds no
// school: the list's title, "0 schools · Close list", and its empty row.
func emptyReadinessList(key string) *screensv1.PageBlock {
	label := rules.Readiness.GapLabels[key]
	columns := []*screensv1.PageColumn{}
	for _, c := range []string{"School ID", "School", "Type", "District", "Cluster", "Visit", "Training", "Project"} {
		columns = append(columns, &screensv1.PageColumn{Label: c})
	}
	columns = append(columns, &screensv1.PageColumn{Label: "Actions", Numeric: true})
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title: label, Subtitle: "0 schools · Close list", Columns: columns,
		Rows: []*screensv1.PageRow{{Cells: []*screensv1.PageCell{
			{Text: closedschools.PyCollapse("None of your schools: " + strings.ToLower(label) + ".")},
		}}},
	}}}
}

// pluralS is |pluralize of a count.
func pluralS(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// targetVisitsTile is the visits tile's line and note for a reader with a
// target (get_frontend_context's visit_helper, cut by brief_helper): the
// tile keeps "of N a year", the sentence becomes its note. A planner Go
// answers has no outreach visits and is within the target.
func targetVisitsTile(m *screensv1.PageMetric, target int, c PlanCounts) {
	t := comma(target)
	m.Helper = "of " + t + " a year"
	m.Note = "Follow up and In-school Training visits you planned, toward the " + t +
		" your role plans in a year: " + comma(c.CoreVisits) + " at Core schools, " + comma(c.ClientVisits) +
		" at Client, Core Trained and Core Graduate schools."
}

// yearVisits is staff_plan.visit_tallies' total for the reader in the year
// as sent (my_plan_readiness_view: request.GET["fy"], not stripped): their
// counted visits wherever they are, by who planned them.
func yearVisits(ctx context.Context, db schooldirectory.Querier, owners []string, fy string) (int, error) {
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return 0, err
	}
	if outside == nil {
		outside = []string{}
	}
	b := &sqlb{}
	where := "a.deleted_at IS NULL AND a.fy = " + b.arg(fy) + " AND a.responsible_staff_id = ANY(" + b.arg(owners) + ") AND " + countedVisit(b, outside)
	var n int
	if err := db.QueryRow(ctx, `SELECT count(*) `+planFrom+` WHERE `+where, b.args...).Scan(&n); err != nil {
		return 0, fmt.Errorf("myplan: counting the year's visits: %w", err)
	}
	return n, nil
}
