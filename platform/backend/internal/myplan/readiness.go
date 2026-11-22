package myplan

import (
	"context"
	"fmt"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// ReadinessLine is one row of Planned and remaining.
type ReadinessLine struct {
	Target, Planned, Remaining, Over, Percent int
	Required                                  bool
	Tone                                      string
}

// OwnReadiness is one planner's Readiness figures (planningmonitor.OwnReadiness).
type OwnReadiness struct {
	Score, SchoolsTotal                                      int
	StaffVisits, StaffTrainings, PartnerVisits               ReadinessLine
	PartnerTrainings, PartnerAssignment, ProjectAssignment   ReadinessLine
	PartnerBeyondStaff, PartnerCoreSchools                   int
	SchoolsStaffScheduled, SchoolsToRecruit, PortfolioVisits int
	ClientStaffAndPartner, CoreVisitsOver                    int
	ProjectCeiling, ProjectAdded, ProjectAssigned            int
	PartnerVisitsAwaiting                                    int
}

// ReadinessReader reads a planner's own Readiness summary (wired via
// planningmonitor.OwnReadiness in server.go).
type ReadinessReader func(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time) (*OwnReadiness, bool, error)

// WithReadiness attaches the personal readiness reader so My Plan renders
// Planned and remaining for planners who hold schools, clusters, or project places.
func (s *Service) WithReadiness(read ReadinessReader) *Service {
	s.readiness = read
	return s
}

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
		none("Schools in training (in-school and group trainings)"),
		none("Partner visits (dated by Partners)"),
		none("Core partner trainings"),
		none("Schools assigned to a Partner"),
		none("Schools assigned to a project (those you added, of your project ceilings put together)"),
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

// fullReadinessTable renders Planned and remaining (partials/my_plan/readiness.html)
// from a planner's real OwnReadiness figures.
func fullReadinessTable(r *OwnReadiness, fy string, request Query) *screensv1.PageBlock {
	lineRow := func(label, note string, l ReadinessLine, plannedKey, targetKey, leftKey, targetHref, leftHref string) *screensv1.PageRow {
		title := label
		if note != "" {
			title += " (" + note + ")"
		}
		plannedCell := readinessCell(l.Planned, plannedKey, "", request)
		if l.Over > 0 {
			plannedCell.Text += " (" + comma(l.Over) + " over)"
		}
		var targetCell *screensv1.PageCell
		if l.Required {
			if targetHref != "" {
				targetCell = &screensv1.PageCell{Text: comma(l.Target), Href: targetHref}
			} else {
				targetCell = readinessCell(l.Target, targetKey, "", request)
			}
		} else {
			targetCell = &screensv1.PageCell{Text: "None required"}
		}
		var remCell *screensv1.PageCell
		if leftHref != "" && l.Remaining > 0 {
			remCell = &screensv1.PageCell{Text: comma(l.Remaining), Href: leftHref, Tone: "warning"}
		} else {
			remCell = readinessCell(l.Remaining, leftKey, "warning", request)
		}
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: title}, plannedCell, targetCell, remCell,
			{Text: fmt.Sprintf("%d%%", l.Percent), Tone: l.Tone},
		}}
	}
	rows := []*screensv1.PageRow{
		lineRow("Your visits", "", r.StaffVisits, "staff_scheduled", "staff_queue", "staff_visits_left", "", ""),
		lineRow("Schools in training", "in-school and group trainings", r.StaffTrainings, "training", "training_due", "no_training", "", ""),
		lineRow("Partner visits", "dated by Partners", r.PartnerVisits, "partner_dated", "partner_queue", "partner_visits_left", "", ""),
		lineRow("Core partner trainings", "", r.PartnerTrainings, "core_partner_trainings", "core", "core_partner_trainings_left", "", ""),
		lineRow("Schools assigned to a Partner", "", r.PartnerAssignment, "with_partner", "partner_queue", "partner_left", "", ""),
		lineRow("Schools assigned to a project", "those you added, of your project ceilings put together",
			r.ProjectAssignment, "project_added", "", "", "/projects/monitoring#my-allocations-title", "/projects/monitoring#my-allocations-title"),
	}
	var b strings.Builder
	t := comma(r.StaffVisits.Target)
	b.WriteString("Your target is " + t + " visit" + pluralS(r.StaffVisits.Target) + " a year")
	if r.PartnerBeyondStaff > 0 {
		verb := "are"
		if r.PartnerBeyondStaff == 1 {
			verb = "is"
		}
		b.WriteString("; once you have planned them, " + comma(r.PartnerBeyondStaff) + " of your Client, Core Trained and Core Graduate schools " + verb + " the Partner's to visit")
	}
	if r.PartnerCoreSchools > 0 {
		b.WriteString("; the Partner also takes two visits and two trainings at each of your " + comma(r.PartnerCoreSchools) + " Core school" + pluralS(r.PartnerCoreSchools))
	}
	b.WriteString(". You have scheduled visits at " + comma(r.SchoolsStaffScheduled) + " of your schools yourself. ")
	if r.SchoolsToRecruit > 0 {
		b.WriteString("Your schools take " + comma(r.PortfolioVisits) + " of those " + t + " visits: recruit " + comma(r.SchoolsToRecruit) + " more school" + pluralS(r.SchoolsToRecruit) + " to meet your target. ")
	}
	if r.ProjectAssignment.Required {
		remVerb := ""
		if r.ProjectAssignment.Remaining == 1 {
			remVerb = "s"
		}
		b.WriteString("Your project ceilings add up to " + comma(r.ProjectCeiling) + " school" + pluralS(r.ProjectCeiling) +
			"; you have added " + comma(r.ProjectAdded) + ", so " + comma(r.ProjectAssignment.Remaining) + " remain" + remVerb + " to reach them")
		if r.ProjectAssigned > 0 {
			isAre, itThem := "are", "them"
			if r.ProjectAssigned == 1 {
				isAre, itThem = "is", "it"
			}
			b.WriteString(" (" + comma(r.ProjectAssigned) + " of the schools you hold " + isAre + " in a project, whoever added " + itThem + ")")
		}
		b.WriteString(". ")
	} else {
		b.WriteString("No project ceiling is set for you, so no project target is asked of you")
		if r.ProjectAdded > 0 {
			b.WriteString("; you have added " + comma(r.ProjectAdded) + " school" + pluralS(r.ProjectAdded) + " to projects")
		}
		b.WriteString(". ")
	}
	b.WriteString("Readiness is the average of your visits, schools in training, schools with a Partner and schools added to projects.")
	if r.PartnerVisitsAwaiting > 0 {
		isAre := "are"
		if r.PartnerVisitsAwaiting == 1 {
			isAre = "is"
		}
		b.WriteString(" " + comma(r.PartnerVisitsAwaiting) + " school" + pluralS(r.PartnerVisitsAwaiting) + " handed over " + isAre + " awaiting the Partner's date.")
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:    closedschools.PyCollapse("Planned and remaining · FY " + fy),
		Subtitle: fmt.Sprintf("Readiness %d%% · %s schools held", r.Score, comma(r.SchoolsTotal)),
		Columns: []*screensv1.PageColumn{
			{Label: "Part of the plan"}, {Label: "Planned", Numeric: true}, {Label: "Target", Numeric: true},
			{Label: "Remaining", Numeric: true}, {Label: "Share", Numeric: true},
		},
		Rows: rows, Footnote: b.String(),
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
