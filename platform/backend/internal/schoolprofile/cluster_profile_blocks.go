package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// The words the Cluster Profile uses where there is nothing to measure: a
// school or cluster with no confirmed SSA is never drawn as a score of zero.
const (
	clusterNotAssessed = "Not Assessed"
	clusterNotCompared = "Not Compared"
)

func clusterFacts(cl clusterDetail, pr *scopeProfile, openStaff bool) []*screensv1.PageFact {
	ceeo := &screensv1.PageFact{Label: "CCEO", Value: orDash(cl.staffName), Href: hrefIf(openStaff && cl.staffID != "", "/staff/"+cl.staffID)}
	if cl.staffName == "" {
		ceeo = peopleFact("CCEO", pr.staff, openStaff, "/staff/")
		ceeo.Label = "CCEO"
	}
	lead := peopleFact("Programme Lead", pr.leads, openStaff, "/staff/")
	lead.Label = "Programme Lead"
	facts := []*screensv1.PageFact{
		{Label: "District", Value: orDash(cl.districtName), Href: hrefIf(cl.districtID != "", "/districts/"+cl.districtID)},
		{Label: "Sub-county", Value: orDash(cl.subCounty)},
		{Label: "Type", Value: orDash(clusterWords(cl.clusterType))},
		{Label: "Status", Value: clusterWords(cl.status)},
		ceeo,
		lead,
		{Label: "Cluster Leader", Value: formatLeader(cl.leaderName, cl.leaderPhone)},
	}
	if cl.partnerName != "" {
		facts = append(facts, &screensv1.PageFact{Label: "Facilitating Partner", Value: cl.partnerName, Href: "/partners/" + cl.partnerID})
	}
	return facts
}

// clusterWords writes a stored word for reading ("sub_county" → "Sub County").
func clusterWords(value string) string {
	parts := strings.Fields(strings.ReplaceAll(value, "_", " "))
	for i, part := range parts {
		parts[i] = strings.ToUpper(part[:1]) + strings.ToLower(part[1:])
	}
	return strings.Join(parts, " ")
}

func clusterHeader(cl clusterDetail, access ClusterAccess, base, fy string) *screensv1.PageHeader {
	line := []string{}
	if cl.districtName != "" {
		line = append(line, "District: "+cl.districtName)
	}
	if cl.subCounty != "" {
		line = append(line, "Sub-county: "+cl.subCounty)
	}
	line = append(line, fyLabel(fy))
	drawer := func(key, label, href string) *screensv1.PageAction {
		return &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href, Drawer: true}
	}
	actions := []*screensv1.PageAction{{Key: "profile", Label: "Cluster Profile", Enabled: true, Href: base + "?tab=analytics&fy=" + fy}}
	if access.Plan {
		actions = append(actions,
			drawer("schedule_group_training", "Schedule Group Training", "/clusters/schedule-training-drawer?cluster_id="+cl.id),
			drawer("schedule_cluster_meeting", "Schedule Cluster Meeting", "/clusters/schedule-meeting-drawer?cluster_id="+cl.id),
			&screensv1.PageAction{Key: "route", Label: "Plan Cluster Route", Enabled: true, Href: "/my-plan/smart-route?cluster=" + url.QueryEscape(cl.id)})
	}
	if access.AddSchools {
		actions = append(actions, drawer("add_schools", "Add Schools", base+"/bulk-assign-drawer"))
	}
	if access.Edit {
		actions = append(actions, drawer("edit_details", "Edit Details", base+"/edit-drawer"))
		reason := access.DeleteBlock
		if reason == "" {
			reason = "Delete this cluster from the Clusters page of the existing application."
		}
		actions = append(actions, &screensv1.PageAction{Key: "delete", Label: "Delete Cluster", Reason: reason})
	}
	return &screensv1.PageHeader{
		BackLabel: "Back to Clusters", BackHref: "/clusters", Title: cl.name, Description: strings.Join(line, " · "),
		Badges:  []*screensv1.PageBadge{{Text: clusterWords(cl.status), Tone: clusterStatusTone(cl.status)}},
		Actions: actions,
	}
}

func clusterStatusTone(status string) string {
	if strings.EqualFold(status, "active") {
		return "good"
	}
	return "caution"
}

func clusterYearFilter(running, fy, tab string) *screensv1.PageBlock {
	options := make([]*screensv1.PageFilterOption, 0, 3)
	for _, year := range fyChoices(running) {
		options = append(options, &screensv1.PageFilterOption{Value: year, Label: fyLabel(year)})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{{Name: "fy", Label: "Fiscal Year", Value: fy, Options: options}},
		Hidden:  map[string]string{"tab": tab},
	}}}
}

func clusterMetric(label, value, helper, href string) *screensv1.PageMetric {
	return &screensv1.PageMetric{Label: label, Value: value, Helper: helper, Href: href}
}

func clusterStrip(title string, metrics ...*screensv1.PageMetric) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: title, Metrics: metrics}}}
}

// countOf writes a count with its noun ("1 visit", "3 visits").
func countOf(n int, noun string) string { return intcomma(n) + " " + noun + plural(n) }

func workParts(visits, trainings, meetings int) string {
	return countOf(visits, "visit") + " · " + countOf(trainings, "training") + " · " + countOf(meetings, "meeting")
}

// clusterSummaryStrip is the page's seven figures, the Cluster Page's own
// (page_summary.operational_summary), for the year.
func clusterSummaryStrip(pr *scopeProfile, ex executionFigures, outstanding int, base, fy string) *screensv1.PageBlock {
	v, t, m := ex.visits, ex.trainings, ex.meetings
	records := base + "?fy=" + fy + "&what="
	counts := map[string]int{}
	for _, x := range pr.schools {
		counts[x.kind]++
	}
	types := []string{}
	for _, key := range rules.Engine.Scope.SchoolTypeOrder {
		if counts[key] > 0 {
			types = append(types, intcomma(counts[key])+" "+rules.SchoolTypes[key])
		}
	}
	ssa, assessed := clusterNotAssessed, fmt.Sprintf("%s of %s assessed", intcomma(pr.assessed), intcomma(pr.assessable))
	if pr.cmp.current != nil {
		ssa = twoPlaces(*pr.cmp.current)
	}
	upcoming := func(f kindFigures) int { return f.notStarted - f.overdue }
	return clusterStrip("Cluster Summary",
		clusterMetric("Member Schools", intcomma(len(pr.schools)), strings.Join(types, " · "), base+"?tab=schools&fy="+fy),
		clusterMetric("In Visit Plan", intcomma(v.planned), countOf(t.planned, "training")+" · "+countOf(m.planned, "meeting"), records+"visits"),
		clusterMetric("Completed", intcomma(v.completed+t.completed+m.completed), workParts(v.completed, t.completed, m.completed), records+"visits_done"),
		clusterMetric("Upcoming", intcomma(upcoming(v)+upcoming(t)+upcoming(m)), workParts(upcoming(v), upcoming(t), upcoming(m)), base+"?tab=activities&fy="+fy),
		clusterMetric("Past Their Date", intcomma(v.overdue+t.overdue+m.overdue), workParts(v.overdue, t.overdue, m.overdue), records+"visits_overdue"),
		clusterMetric("Outstanding Actions", intcomma(outstanding), "need follow-up", base+"?tab=overview&fy="+fy),
		clusterMetric("Cluster SSA Score", ssa, assessed, base+"?tab=ssa&fy="+fy),
	)
}

// clusterSSARail is the cluster's SSA over the schools with a confirmed
// assessment only: unassessed schools are counted as unassessed, never as 0.
func clusterSSARail(pr *scopeProfile, l lens) *screensv1.PageBlock {
	figure := clusterNotAssessed
	if pr.cmp.current != nil {
		figure = twoPlaces(*pr.cmp.current)
	}
	note := fmt.Sprintf("%s of %s schools assessed", intcomma(pr.assessed), intcomma(pr.assessable))
	if pr.assessed == 0 {
		note = "No verified SSA data for " + fyLabel(l.fy)
	}
	change := clusterNotCompared
	if pr.cmp.current != nil && pr.cmp.previous != nil && pr.overall.delta != nil {
		change = signedTwoPlaces(*pr.overall.delta) + " since " + fyLabel(previousFY(l.fy))
	}
	meters := make([]*screensv1.PageMeter, 0, len(pr.cmp.rows))
	for _, r := range pr.cmp.rows {
		meter := &screensv1.PageMeter{Label: r.label, Value: clusterNotAssessed, Href: l.records() + "intervention&key=" + url.QueryEscape(r.key)}
		if r.current != nil {
			meter.Value = twoPlaces(*r.current)
			meter.Fraction = math.Min(math.Max(*r.current/10, 0), 1)
		}
		meters = append(meters, meter)
	}
	lines := []string{}
	if best, weakest := picks(pr.cmp.rows); best != nil {
		lines = append(lines, "Strongest: "+best.row.label)
		if weakest != nil {
			lines = append(lines, "Weakest: "+weakest.row.label)
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Rail{Rail: &screensv1.PageRail{
		Title: "SSA Performance", Subtitle: fyLabel(l.fy),
		Parts: []*screensv1.PageRailPart{{
			Key: "ssa", Title: change, Figure: figure, FigureHref: l.href() + "tab=ssa&fy=" + l.fy,
			FigureNote: note, Meters: meters, Note: strings.Join(lines, " · "),
		}},
	}}}
}

// clusterReadiness is each school's confirmed SSA this year.
func clusterReadiness(pr *scopeProfile, openSchools bool) *screensv1.PageBlock {
	items := make([]*screensv1.PagePanelItem, 0, len(pr.schools))
	for _, x := range pr.schools {
		meter := &screensv1.PageMeter{Label: x.name, Value: clusterNotAssessed, Href: hrefIf(openSchools, "/schools/"+x.id)}
		if c := pr.scores[x.id].current; c != nil {
			meter.Value = twoPlaces(*c)
			meter.Fraction = math.Min(math.Max(*c/10, 0), 1)
		}
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Meter{Meter: meter}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "SSA Readiness by School", Items: items}}}
}

func clusterActivityStrip(ex executionFigures, base, fy string) *screensv1.PageBlock {
	v, t, m := ex.visits, ex.trainings, ex.meetings
	planned := v.planned + t.planned + m.planned
	completed := v.completed + t.completed + m.completed
	notStarted := v.notStarted + t.notStarted + m.notStarted
	href := base + "?tab=activities&fy=" + fy
	return clusterStrip("Cluster Activities",
		clusterMetric("Planned", intcomma(planned), "", href),
		clusterMetric("Completed", intcomma(completed), "", href),
		clusterMetric("Ongoing", intcomma(planned-completed-notStarted), "", href),
		clusterMetric("Outstanding", intcomma(planned-completed), "", href),
	)
}

func clusterAttendanceStrip(ex executionFigures, card ClusterCard, base, fy string) *screensv1.PageBlock {
	rate := "—"
	if card.Rate != nil {
		rate = strconv.Itoa(*card.Rate) + "%"
	}
	href := base + "?tab=attendance&fy=" + fy
	return clusterStrip("Meeting Attendance",
		clusterMetric("Meetings Held", intcomma(ex.meetings.completed), "of "+intcomma(ex.meetings.planned)+" scheduled", href),
		clusterMetric("Schools Invited", intcomma(card.Invited), "", href),
		clusterMetric("Schools Represented", intcomma(card.Attended), "", href),
		clusterMetric("Attendance Rate", rate, intcomma(card.Sessions)+" with a register", href),
		clusterMetric("Teachers Attended", intcomma(card.Teachers), "", href),
		clusterMetric("Leaders Attended", intcomma(card.Leaders), "", href),
		clusterMetric("Repeatedly Absent", intcomma(card.Absent), "schools", href),
	)
}

// attentionLinks are the engine's Needs Attention lines for this profile.
func (pr *scopeProfile) attentionLinks(l lens, openSchools bool) []*screensv1.PageLink {
	for _, block := range pr.tables(l, pr.book, pr.focus, openSchools, map[string][]part{}) {
		rail := block.GetRail()
		if rail == nil {
			continue
		}
		for _, p := range rail.GetParts() {
			if p.GetKey() == "attention" {
				return p.GetLinks()
			}
		}
	}
	return nil
}

func clusterLinksPanel(title string, links []*screensv1.PageLink, empty string) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	if len(links) > 0 {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})
	} else {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: empty}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

func clusterInsights(attention []*screensv1.PageLink) *screensv1.PageBlock {
	return clusterLinksPanel("Cluster Insights", attention, "Nothing needs attention in this cluster.")
}

// clusterRecommended are the next steps the year's own figures call for,
// each opening the place the step is taken.
func clusterRecommended(cl clusterDetail, pr *scopeProfile, ex executionFigures, access ClusterAccess, base, fy string) *screensv1.PageBlock {
	links := []*screensv1.PageLink{}
	noSSA := 0
	for _, x := range pr.schools {
		if rules.Engine.Requirements[x.kind].TakesSSA && pr.scores[x.id].current == nil {
			noSSA++
		}
	}
	if noSSA > 0 {
		links = append(links, &screensv1.PageLink{Text: fmt.Sprintf("Schedule an SSA for %s school%s", intcomma(noSSA), plural(noSSA)), Href: base + "?tab=schools&fy=" + fy + "&show=no_ssa"})
	}
	if access.Plan && ex.meetings.planned == 0 {
		links = append(links, &screensv1.PageLink{Text: "Plan a cluster meeting", Href: "/clusters/schedule-meeting-drawer?cluster_id=" + cl.id, Drawer: true})
	}
	if access.Plan && ex.trainings.planned == 0 {
		links = append(links, &screensv1.PageLink{Text: "Plan a group training", Href: "/clusters/schedule-training-drawer?cluster_id=" + cl.id, Drawer: true})
	}
	if overdue := ex.visits.overdue + ex.trainings.overdue + ex.meetings.overdue; overdue > 0 {
		links = append(links, &screensv1.PageLink{Text: fmt.Sprintf("Follow up %s activit%s past their date", intcomma(overdue), map[bool]string{true: "y", false: "ies"}[overdue == 1]), Href: base + "?tab=activities&fy=" + fy})
	}
	return clusterLinksPanel("Recommended Actions", links, "No action is recommended right now.")
}

// ── The year-by-year history ────────────────────────────────────────────

type clusterChartKind int

const (
	chartSSATrend clusterChartKind = iota
	chartSSACoverage
	chartVisitCoverage
	chartTrainingCoverage
	chartActionClosure
)

type clusterYear struct {
	fy                         string
	ssa                        *float64
	assessed, visited, trained int
	inPlan, done               int
}

type clusterHistoryData struct {
	years   []clusterYear
	schools int
}

// clusterYears are the last four financial years, oldest first.
func clusterYears(running string) []string {
	end, err := strconv.Atoi(running)
	if err != nil {
		return []string{running}
	}
	return []string{strconv.Itoa(end - 3), strconv.Itoa(end - 2), strconv.Itoa(end - 1), strconv.Itoa(end)}
}

func (s *Service) clusterYearHistory(ctx context.Context, clusterID string, ids []string, running string) (clusterHistoryData, error) {
	names := clusterYears(running)
	at := map[string]int{}
	out := clusterHistoryData{schools: len(ids), years: make([]clusterYear, len(names))}
	for i, fy := range names {
		out.years[i].fy = fy
		at[fy] = i
	}
	rows, err := s.db.Query(ctx, `
SELECT fy, AVG(average_score)::float8, COUNT(DISTINCT school_id) FROM ssa_record
WHERE school_id = ANY($1) AND fy = ANY($2) AND verification_status = 'confirmed' AND deleted_at IS NULL
GROUP BY fy`, ids, names)
	if err != nil {
		return out, fmt.Errorf("schoolprofile: reading the cluster's SSA by year: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var fy string
		var average *float64
		var assessed int
		if err := rows.Scan(&fy, &average, &assessed); err != nil {
			return out, fmt.Errorf("schoolprofile: scanning the cluster's SSA by year: %w", err)
		}
		if i, ok := at[fy]; ok {
			out.years[i].ssa, out.years[i].assessed = average, assessed
		}
	}
	if err := rows.Err(); err != nil {
		return out, err
	}
	work, err := s.db.Query(ctx, `
SELECT a.fy,
  COUNT(a.id) FILTER (WHERE NOT a.status = ANY($3)),
  COUNT(a.id) FILTER (WHERE a.status = ANY($4)),
  COUNT(DISTINCT a.school_id) FILTER (WHERE a.activity_type = ANY($5) AND a.status = ANY($4)),
  COUNT(DISTINCT a.school_id) FILTER (WHERE a.activity_type = ANY($6) AND a.status = ANY($4))
FROM activity a
WHERE a.deleted_at IS NULL AND a.fy = ANY($2) AND (a.cluster_id = $1 OR a.school_id = ANY($7::text[]))
GROUP BY a.fy`, clusterID, names, rules.Engine.NotInPlanStatuses, rules.Engine.CompletedWorkStatuses,
		rules.Engine.VisitTypes, rules.Engine.TrainingTypes, ids)
	if err != nil {
		return out, fmt.Errorf("schoolprofile: reading the cluster's work by year: %w", err)
	}
	defer work.Close()
	for work.Next() {
		var fy string
		var y clusterYear
		if err := work.Scan(&fy, &y.inPlan, &y.done, &y.visited, &y.trained); err != nil {
			return out, fmt.Errorf("schoolprofile: scanning the cluster's work by year: %w", err)
		}
		if i, ok := at[fy]; ok {
			out.years[i].inPlan, out.years[i].done, out.years[i].visited, out.years[i].trained = y.inPlan, y.done, y.visited, y.trained
		}
	}
	return out, work.Err()
}

func percent(part, whole int) float64 {
	return math.Round(float64(part) * 100 / float64(whole))
}

// chart draws one history. A year with nothing to measure is left off the
// chart rather than drawn as a zero.
func (h clusterHistoryData) chart(kind clusterChartKind) *screensv1.PageBlock {
	title, subtitle, series, top := "", "", "", 100.0
	value := func(clusterYear) (float64, bool) { return 0, false }
	// A year with no record of that work at all has nothing to show, which is
	// not the same as a year where none of the schools were reached.
	share := func(part func(clusterYear) int, recorded func(clusterYear) bool) func(clusterYear) (float64, bool) {
		return func(y clusterYear) (float64, bool) {
			if h.schools == 0 || !recorded(y) {
				return 0, false
			}
			return percent(part(y), h.schools), true
		}
	}
	planned := func(y clusterYear) bool { return y.inPlan > 0 }
	switch kind {
	case chartSSATrend:
		title, subtitle, series, top = "SSA Trend", "Average confirmed SSA of the assessed schools", "Average SSA score", 10
		value = func(y clusterYear) (float64, bool) {
			if y.ssa == nil {
				return 0, false
			}
			return pyRound(*y.ssa, 2), true
		}
	case chartSSACoverage:
		title, subtitle, series = "SSA Coverage", "Share of today's member schools with a confirmed SSA", "Schools assessed (%)"
		value = share(func(y clusterYear) int { return y.assessed }, func(y clusterYear) bool { return y.assessed > 0 })
	case chartVisitCoverage:
		title, subtitle, series = "Visit Coverage", "Share of today's member schools with a completed visit", "Schools visited (%)"
		value = share(func(y clusterYear) int { return y.visited }, planned)
	case chartTrainingCoverage:
		title, subtitle, series = "Training Coverage", "Share of today's member schools with a completed in-school training", "Schools trained (%)"
		value = share(func(y clusterYear) int { return y.trained }, planned)
	case chartActionClosure:
		title, subtitle, series = "Action Closure", "Share of the year's planned work that was completed", "Completed (%)"
		value = func(y clusterYear) (float64, bool) {
			if y.inPlan == 0 {
				return 0, false
			}
			return percent(y.done, y.inPlan), true
		}
	}
	categories, values := []string{}, []float64{}
	for _, y := range h.years {
		if v, ok := value(y); ok {
			categories = append(categories, fyLabel(y.fy))
			values = append(values, v)
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: &screensv1.PageChart{
		Title: title, Subtitle: subtitle, Categories: categories, Max: top,
		Series: []*screensv1.PageSeries{{Name: series, Values: values}},
	}}}
}

// ── The member schools ──────────────────────────────────────────────────

var clusterMemberColumns = []string{"School ID", "School Name", "Type", "SSA Avg", "Last Visit", "Last Training",
	"Visit Plan Status", "Training Plan Status", "Visit Lock", "Planning Readiness", "Responsible Staff", "Actions"}

func factValue(facts []*screensv1.PageFact, label string) *screensv1.PageFact {
	for _, f := range facts {
		if f.GetLabel() == label {
			return f
		}
	}
	return &screensv1.PageFact{}
}

// clusterMembers is the Clusters page's roster (its status pills, lock, row
// actions, ticks and opened row), with the columns the profile adds.
func (s *Service) clusterMembers(ctx context.Context, p auth.Principal, cl clusterDetail, pr *scopeProfile, fy string) (*screensv1.PageBlock, *screensv1.PageSelection, error) {
	table := &screensv1.PageTable{Title: "Member Schools", Columns: makeCols(clusterMemberColumns...),
		EmptyMessage: "This cluster has no schools yet."}
	roster, err := s.clusterWorkspace.Roster(ctx, p, cl.id, fy)
	if errors.Is(err, pagegate.ErrNotAvailable) {
		table.EmptyMessage = "Your role does not list this cluster's schools."
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	var source *screensv1.PageTable
	for _, block := range roster.GetBlocks() {
		if t := block.GetTable(); t != nil {
			source = t
		}
	}
	if source == nil {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}, roster.GetSelection(), nil
	}
	byCode := map[string]string{}
	for _, x := range pr.schools {
		byCode[x.code] = x.id
	}
	readiness, err := s.clusterReadinessWords(ctx, idsOf(pr.schools))
	if err != nil {
		return nil, nil, err
	}
	details, err := s.clusterSchoolSSA(ctx, idsOf(pr.schools), fy, pr)
	if err != nil {
		return nil, nil, err
	}
	at := map[string]int{}
	for i, c := range source.GetColumns() {
		at[c.GetLabel()] = i
	}
	cell := func(row *screensv1.PageRow, label string) *screensv1.PageCell {
		if i, ok := at[label]; ok && i < len(row.GetCells()) {
			return row.GetCells()[i]
		}
		return &screensv1.PageCell{Text: "—"}
	}
	for _, row := range source.GetRows() {
		id := byCode[cell(row, "ID").GetText()]
		// The year's confirmed score, the same figure the cluster's average is made of.
		ssaCell := &screensv1.PageCell{Text: clusterNotAssessed, Tone: "warning"}
		if c := pr.scores[id].current; c != nil {
			ssaCell = &screensv1.PageCell{Text: twoPlaces(*c) + "/10", Strong: true}
		}
		responsible := factValue(row.GetDetails(), "Staff Name").GetValue()
		if who := cell(row, "Responsible").GetText(); who == "Partner" {
			responsible = "Partner · " + responsible
		}
		built := &screensv1.PageRow{
			PickId: row.GetPickId(), PickLabel: row.GetPickLabel(), Details: row.GetDetails(), DetailsHref: row.GetDetailsHref(),
			DetailBlocks: row.GetDetailBlocks(),
			Cells: []*screensv1.PageCell{
				cell(row, "ID"), cell(row, "School Name"),
				{Text: factValue(row.GetDetails(), "School Type").GetValue()},
				ssaCell,
				{Text: factValue(row.GetDetails(), "Last Visit").GetValue(), Tone: toneWord(factValue(row.GetDetails(), "Last Visit").GetTone())},
				{Text: factValue(row.GetDetails(), "Last Training").GetValue(), Tone: toneWord(factValue(row.GetDetails(), "Last Training").GetTone())},
				cell(row, "Visit Plan Status"), cell(row, "Training Plan Status"), cell(row, "Visit Lock"),
				{Text: orDash(label(rules.Readiness, readiness[id]))},
				{Text: orDash(responsible)},
				cell(row, "Actions"),
			},
		}
		if d := details[id]; d != nil {
			built.DetailBlocks = []*screensv1.PageBlock{d}
		}
		table.Rows = append(table.Rows, built)
	}
	learners := 0
	for _, x := range pr.schools {
		learners += x.enrolment
	}
	table.Subtitle = fmt.Sprintf("%s school%s · %s students impacted", intcomma(len(table.Rows)), plural(len(table.Rows)), intcomma(learners))
	if kept := len(pr.schools) - len(table.Rows); kept > 0 {
		table.Footnote = fmt.Sprintf("%s Champion school%s kept in the Champion list.", intcomma(kept), plural(kept))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}, roster.GetSelection(), nil
}

// toneWord turns a fact's tone into a table cell's.
func toneWord(tone string) string {
	return map[string]string{"alert": "danger", "caution": "warning", "good": "success"}[tone]
}

func (s *Service) clusterReadinessWords(ctx context.Context, ids []string) (map[string]string, error) {
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(planning_readiness, '') FROM school WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading planning readiness: %w", err)
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var id, word string
		if err := rows.Scan(&id, &word); err != nil {
			return nil, fmt.Errorf("schoolprofile: scanning planning readiness: %w", err)
		}
		out[id] = word
	}
	return out, rows.Err()
}

type clusterSSARecord struct {
	school, fy, status string
	held               *time.Time
}

// clusterSchoolSSA is what opening a school's row shows: each intervention
// this year and last year, from the school's latest confirmed assessments.
func (s *Service) clusterSchoolSSA(ctx context.Context, ids []string, fy string, pr *scopeProfile) (map[string]*screensv1.PageBlock, error) {
	before := previousFY(fy)
	rows, err := s.db.Query(ctx, `
SELECT DISTINCT ON (r.school_id, r.fy) r.id, r.school_id, r.fy, r.date_of_ssa, COALESCE(r.verification_status, '')
FROM ssa_record r
WHERE r.school_id = ANY($1) AND r.fy = ANY($2) AND r.deleted_at IS NULL AND r.verification_status = ANY($3)
ORDER BY r.school_id, r.fy, r.date_of_ssa DESC, r.created_at DESC, r.id DESC`, ids, []string{fy, before}, rules.SSACurrentStatuses)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the schools' assessments: %w", err)
	}
	defer rows.Close()
	records := map[string]clusterSSARecord{}
	recordIDs := []string{}
	for rows.Next() {
		var id string
		var r clusterSSARecord
		if err := rows.Scan(&id, &r.school, &r.fy, &r.held, &r.status); err != nil {
			return nil, fmt.Errorf("schoolprofile: scanning the schools' assessments: %w", err)
		}
		records[id] = r
		recordIDs = append(recordIDs, id)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	scores := map[string]map[string]map[string]float64{}
	if len(recordIDs) > 0 {
		lines, err := s.db.Query(ctx, `SELECT ssa_record_id, intervention, score::float8 FROM ssa_score WHERE ssa_record_id = ANY($1) AND score IS NOT NULL`, recordIDs)
		if err != nil {
			return nil, fmt.Errorf("schoolprofile: reading the schools' scores: %w", err)
		}
		defer lines.Close()
		for lines.Next() {
			var recordID, intervention string
			var value float64
			if err := lines.Scan(&recordID, &intervention, &value); err != nil {
				return nil, fmt.Errorf("schoolprofile: scanning the schools' scores: %w", err)
			}
			r := records[recordID]
			if scores[r.school] == nil {
				scores[r.school] = map[string]map[string]float64{}
			}
			if scores[r.school][r.fy] == nil {
				scores[r.school][r.fy] = map[string]float64{}
			}
			scores[r.school][r.fy][intervention] = value
		}
		if err := lines.Err(); err != nil {
			return nil, err
		}
	}
	latest := map[string]clusterSSARecord{}
	for _, r := range records {
		if r.fy == fy {
			latest[r.school] = r
		}
	}
	out := map[string]*screensv1.PageBlock{}
	for _, id := range ids {
		table := &screensv1.PageTable{Title: "SSA by intervention", Columns: []*screensv1.PageColumn{{Label: "Intervention"},
			{Label: fyLabel(fy), Numeric: true}, {Label: fyLabel(before), Numeric: true}, {Label: "Change", Numeric: true}},
			EmptyMessage: "No confirmed SSA for " + fyLabel(fy) + "."}
		if r, ok := latest[id]; ok {
			when := "—"
			if r.held != nil {
				when = r.held.Format("2 Jan 2006")
			}
			table.Subtitle = "Assessed " + when + " · " + clusterWords(r.status)
		}
		for _, row := range pr.cmp.rows {
			now, hasNow := scores[id][fy][row.key]
			was, hasWas := scores[id][before][row.key]
			if !hasNow && !hasWas {
				continue
			}
			cells := []*screensv1.PageCell{{Text: row.label}, {Text: clusterNotAssessed}, {Text: "—"}, {Text: clusterNotCompared}}
			if hasNow {
				cells[1] = &screensv1.PageCell{Text: twoPlaces(now), Strong: true}
			}
			if hasWas {
				cells[2] = &screensv1.PageCell{Text: twoPlaces(was)}
			}
			if hasNow && hasWas {
				moved := pyRound(now-was, 2)
				tone := ""
				if moved > 0 {
					tone = "success"
				} else if moved < 0 {
					tone = "danger"
				}
				cells[3] = &screensv1.PageCell{Text: signedTwoPlaces(moved), Tone: tone}
			}
			table.Rows = append(table.Rows, &screensv1.PageRow{Cells: cells})
		}
		out[id] = &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}
	}
	return out, nil
}

// clusterParticipation is each member school's register for the year's
// delivered sessions, with the sessions it has missed in a row.
func (s *Service) clusterParticipation(ctx context.Context, clusterID, fy string, pr *scopeProfile, alertAfter int) (*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `
SELECT caa.school_id, caa.invited, caa.attended
FROM cluster_activity_attendance caa JOIN activity a ON a.id = caa.activity_id
WHERE a.cluster_id = $1 AND a.fy = $2 AND a.deleted_at IS NULL AND a.status = ANY($3) AND caa.school_id = ANY($4)
ORDER BY COALESCE(a.planned_date, (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date) DESC NULLS LAST`,
		clusterID, fy, rules.Engine.CompletedWorkStatuses, idsOf(pr.schools))
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the cluster's registers: %w", err)
	}
	defer rows.Close()
	type register struct {
		invited, attended, missed int
		stopped                   bool
	}
	seen := map[string]*register{}
	for rows.Next() {
		var school string
		var invited, attended bool
		if err := rows.Scan(&school, &invited, &attended); err != nil {
			return nil, fmt.Errorf("schoolprofile: scanning the cluster's registers: %w", err)
		}
		r := seen[school]
		if r == nil {
			r = &register{}
			seen[school] = r
		}
		if invited {
			r.invited++
		}
		if attended {
			r.attended++
			r.stopped = true
		} else if invited && !r.stopped {
			r.missed++
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	table := &screensv1.PageTable{
		Title: "School Participation", Subtitle: fyLabel(fy),
		Columns: []*screensv1.PageColumn{{Label: "School ID"}, {Label: "School Name"}, {Label: "Invited", Numeric: true},
			{Label: "Attended", Numeric: true}, {Label: "Rate", Numeric: true}, {Label: "Missed In A Row", Numeric: true}},
		EmptyMessage: "No school has a register for this year's sessions yet.",
	}
	for _, x := range pr.schools {
		r := seen[x.id]
		if r == nil {
			continue
		}
		rate := "—"
		if r.invited > 0 {
			rate = strconv.Itoa(int(percent(r.attended, r.invited))) + "%"
		}
		missed := &screensv1.PageCell{Text: intcomma(r.missed)}
		if r.missed >= alertAfter {
			missed = &screensv1.PageCell{Text: intcomma(r.missed), Tone: "danger", Strong: true}
		}
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: orDash(x.code)}, {Text: x.name, Href: "/schools/" + x.id},
			{Text: intcomma(r.invited)}, {Text: intcomma(r.attended)}, {Text: rate}, missed,
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}, nil
}

// ── The session and activity lists ──────────────────────────────────────

func clusterAttendanceBlocks(activities []clusterActivityRow, showMissing bool, base, fy string) []*screensv1.PageBlock {
	var rows []*screensv1.PageRow
	for _, a := range activities {
		if a.schoolName != "" {
			continue // cluster-level sessions only
		}
		missing := a.attendanceRows == 0 && a.teachers+a.leaders+a.other == 0
		if showMissing && !missing {
			continue
		}
		dateStr := "—"
		if a.plannedDate != nil {
			dateStr = a.plannedDate.Format("02 Jan 2006")
		}
		attText := fmt.Sprintf("%d/%d schools · %d participants", a.attended, a.invited, a.teachers+a.leaders+a.other)
		tone := "positive"
		if missing {
			attText = "Attendance missing"
			tone = "attention"
		}
		rows = append(rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: dateStr},
				{Text: a.title, Href: "/activities/" + a.id},
				{Text: clusterWords(a.activityType)},
				{Text: clusterWords(a.status)},
				{Text: attText, Tone: tone},
				{Text: orDash(a.ownerName)},
			},
		})
	}
	caption := "Cluster Session Attendance"
	if showMissing {
		caption = "Cluster Sessions Missing Attendance"
	}
	filterLink := &screensv1.PageLink{Text: "Show sessions missing attendance", Href: base + "?tab=attendance&show=missing&fy=" + fy}
	if showMissing {
		filterLink = &screensv1.PageLink{Text: "Show all cluster sessions", Href: base + "?tab=attendance&fy=" + fy}
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        caption,
			Subtitle:     fyLabel(fy),
			Columns:      makeCols("Date", "Session", "Type", "Status", "Attendance", "Lead Staff"),
			Rows:         rows,
			EmptyMessage: "No cluster sessions match this attendance filter for " + fyLabel(fy) + ".",
		}}},
		clusterLinksPanel("Attendance Filter", []*screensv1.PageLink{filterLink}, ""),
	}
}

func clusterActivitiesTable(title string, activities []clusterActivityRow, empty string) *screensv1.PageBlock {
	rows := make([]*screensv1.PageRow, 0, len(activities))
	for _, a := range activities {
		dateStr := "—"
		if a.plannedDate != nil {
			dateStr = a.plannedDate.Format("02 Jan 2006")
		}
		whereCell := &screensv1.PageCell{Text: "Cluster-wide"}
		if a.schoolName != "" {
			ref := a.schoolCode
			if ref == "" {
				ref = a.schoolName
			}
			whereCell = &screensv1.PageCell{Text: a.schoolName, Href: "/schools/" + url.PathEscape(ref)}
		}
		rows = append(rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: dateStr},
				{Text: a.title, Href: "/activities/" + a.id},
				{Text: clusterWords(a.activityType)},
				whereCell,
				{Text: clusterWords(a.status)},
				{Text: orDash(a.ownerName)},
			},
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:        title,
		Columns:      makeCols("Date", "Activity", "Type", "Location", "Status", "Owner"),
		Rows:         rows,
		EmptyMessage: empty,
	}}}
}
