package planningmonitor

import (
	"fmt"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The monitor as a Programme Lead's dashboard carries it
// (partials/oversight/planning_monitor_embed.html over monitor_workspace.html),
// as the feed reads it: the section's name and its two tabs, its filters,
// the figures, the three tables' tabs, then Planned and remaining, Schools
// by type, the ledger, the checks and Planning against target.

// The pages the counts open.
const (
	monitorPath  = "/planning-monitor/"
	plansPath    = "/team-planning-oversight/"
	partnersPath = "/partner-oversight/"
)

// The tables' "About these figures" (_monitor_readiness.html,
// _monitor_inventory.html and _monitor_about.html), the targets filled in.
var (
	readinessAbout = fmt.Sprintf("What counts as a staff visit is every Follow up, In-school Training and SSA Support visit staff schedule themselves; SSA Support assigned to a Partner does not count. The target is %d visits a year for a Programme Lead and %d for a CCEO, whatever they hold: two at each Core school and the rest at Client, Core Trained and Core Graduate schools. Once those are planned, the schools left are the Partner's. Somebody whose schools cannot take that many visits is marked “recruit N more schools”, and is sent a notice to recruit them. The Partner takes the other two visits and two trainings at each Core school and every school beyond the staff target. Schools scheduled by staff are the schools held where staff scheduled a visit themselves; Two columns flag visits planned on both sides, and each count opens its schools. Client: Staff and Partner counts the Client, Core Trained and Core Graduate schools staff scheduled a visit at that are also in a Partner's hands; such a school takes one visit, staff's or the Partner's, so it is booked twice. A Core school takes two visits by staff and two by a Partner, so both visiting is its package and is not flagged; Core: over 2 Staff or 2 Partner visits counts the Core schools with more than two staff visits or more than two Partner visits, dated or awaiting the Partner's date. Schools in training are the schools attached to an in-school training or a group training, of the schools that take one; a cluster meeting is not a training. Core partner trainings are the Partner's two at each Core school. A Partner visit is planned once the Partner has dated it. Schools added to projects are the schools the person added to a project, of the ceilings the Project Coordinator set them, put together; what is left is what remains to reach those ceilings, and somebody with no ceiling is asked nothing. Each percentage stops at 100, so planning past one target does not cover another, and a part that asks nothing is complete. Readiness is the average of staff visits, schools in training, schools with a Partner and schools added to projects. The target warns and never refuses, and no school is assigned to a Partner by this page: the Partner's share is a target.",
		plTarget(), cceoTarget())
	inventoryAbout = "A Core school is fully planned with two staff and two Partner visits and two staff and two Partner trainings; a Client, Core Trained or Core Graduate school with its one visit (staff's, or in a Partner's hands) and its one training. A Champion school takes donor and story visits only, so it has nothing left to plan and is counted for its project. Closed schools and deleted records are not operating and are not counted. The page checks these figures against the schools in scope before it shows them."
	detailAbout    = fmt.Sprintf("A Programme Lead plans %[1]d visits a year and a CCEO %[2]d, whatever they hold: two at each Core school, the rest at Client, Core Trained and Core Graduate schools. Somebody whose schools cannot take that many visits is marked “recruit N more schools” and is sent a notice to recruit them. Visits count the Follow up, In-school Training and SSA Support visits the person scheduled themselves, wherever the school is; SSA Support assigned to a Partner, and donor, story, social and invitation visits, are not counted. Partner schools are the client schools beyond what the person's own visits can reach — their client, Core Trained and Core Graduate schools less their client visits — showing how many are with a partner of how many should be. Core partner visits and trainings are the partner half of each Core package, two of each a school, counting hand-overs a partner has not dated yet; Core staff trainings are the staff half's two. The partner's target is that half plus the client schools beyond staff reach. The %[1]d and %[2]d are ceilings that warn and never refuse: a visit planned past one is saved, and the row says how many are over. Partner activities are those the partner itself has dated, with the work still awaiting the partner's date beside them. A person's visit count opens their planned visits, and their partner schools open on Partner Monitoring. Training counts a school attached to a group training or an in-school training (a cluster meeting is not a training), out of the Core, Client, Core Trained and Core Graduate schools. A school handed to a Partner is not counted under No visit or Neither, whether or not the Partner has dated it: Schools visited shows how many are with a Partner beside those with a visit planned. These are the figures Country Planning Oversight shows: the two pages count by one rulebook.",
		plTarget(), cceoTarget())
)

func plTarget() int   { return rules.VisitTargets[rules.RoleCodes[rules.ProgramLeadRole]] }
func cceoTarget() int { return rules.VisitTargets[rules.RoleCodes[rules.CCEORole]] }

// intcomma is Django's intcomma.
func intcomma(n int) string {
	s := strconv.Itoa(n)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	var b strings.Builder
	for i, r := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(r)
	}
	if neg {
		return "-" + b.String()
	}
	return b.String()
}

// pluralS is |pluralize.
func pluralS(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// cell is a table cell as the feed reads it: the words it says, the first
// link's address and the first tone.
type cell struct {
	text, href, tone string
}

func (c *cell) add(text string) { c.text += text }

// count is _monitor_count.html: a figure that opens the schools behind it,
// or a muted 0. The first link and the first tone are the cell's.
func (c *cell) count(n int, url, tone, suffix string) {
	if n == 0 {
		c.add("0" + suffix)
		return
	}
	c.link(intcomma(n)+suffix, url, tone)
}

// link adds words that open url, in tone.
func (c *cell) link(text, url, tone string) {
	c.add(text)
	if c.href == "" {
		c.href = url
	}
	c.toned(tone)
}

func (c *cell) toned(tone string) {
	if c.tone == "" && tone != "" {
		c.tone = tone
	}
}

func (c *cell) page() *screensv1.PageCell {
	return &screensv1.PageCell{Text: strings.Join(strings.Fields(c.text), " "), Href: c.href, Tone: c.tone}
}

// view is one draw of the monitor.
type view struct {
	m       *Monitor
	fy      string
	total   Readiness
	ledger  map[string]any
	monitor string
}

// gapURL is the address a count opens: the gap or list, whose schools, and
// a school type.
func (v view) gapURL(key, scope, schoolType string) string {
	url := v.monitor + "&gap=" + key + scope
	if schoolType != "" {
		url += "&school_type=" + schoolType
	}
	return url + "#monitor-list"
}

func officerScope(o *Officer) string { return "&officer=" + o.Key }

func leadScope(l *Lead) string {
	if l == nil || l.Key == "all" {
		return ""
	}
	return "&program_lead=" + l.Key
}

// Blocks are the embedded monitor's blocks.
func Blocks(m *Monitor, ledger map[string]any) []*screensv1.PageBlock {
	v := view{m: m, fy: m.FY, total: m.Readiness(), ledger: ledger, monitor: monitorPath + "?view=monitor&fy=" + m.FY}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Section{Section: "Planning Monitor"}},
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: []*screensv1.PageLinkTab{
			{Label: "Planning", Href: monitorPath + "?view=planning&fy=" + v.fy, Active: true},
			{Label: "Execution & Completion", Href: monitorPath + "?view=execution&fy=" + v.fy},
		}}}},
		v.filters(),
		v.strip(),
	}
	tabs := &screensv1.PagePanel{}
	for _, t := range rules.MonitorTabs {
		tabs.Items = append(tabs.Items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t[1]}})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: tabs}})
	return append(blocks, v.readinessTable(), v.inventoryTable(), v.ledgerTable(), v.checksTable(), v.detailTable())
}

func (v view) filters() *screensv1.PageBlock {
	var filters []*screensv1.PageFilter
	if len(v.m.Leads) > 1 {
		lead := &screensv1.PageFilter{Name: "program_lead", Label: "Programme Lead",
			Options: []*screensv1.PageFilterOption{{Value: "", Label: "All leads"}}}
		for _, l := range v.m.Leads {
			lead.Options = append(lead.Options, &screensv1.PageFilterOption{Value: l.Key,
				Label: fmt.Sprintf("%s (%d)", l.Name, l.schoolCount())})
		}
		filters = append(filters, lead)
	}
	gap := &screensv1.PageFilter{Name: "gap", Label: "Schools to list", Caption: "Schools",
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "Choose a gap to list"}}}
	for _, g := range rules.Gaps {
		gap.Options = append(gap.Options, &screensv1.PageFilterOption{Value: g[0], Label: g[1]})
	}
	filters = append(filters, gap)
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: filters, Hidden: map[string]string{"view": "monitor", "fy": v.fy}}}}
}

func (l *Lead) schoolCount() int {
	n := 0
	for _, o := range l.Officers {
		n += len(o.Schools)
	}
	return n
}

// ratio is MetricValue.ratio drawn by format_value: round(n / d * 100, 1)
// written as Python's "{:g}%".
func ratio(n, d int) string {
	value := schooldirectory.PyRound1(float64(n) / float64(d) * 100)
	return strconv.FormatFloat(value, 'g', 6, 64) + "%"
}

// strip is _monitor_kpis: the monitor's figures, each folded from the rows.
func (v view) strip() *screensv1.PageBlock {
	everyone := &Lead{Key: "all", Officers: v.m.Officers()}
	f := everyone.figures()
	get := func(name string) int { n, _ := f[name].(int); return n }
	r := v.total
	staff := r.StaffVisits()
	over := ""
	if staff.over() > 0 {
		over = fmt.Sprintf(" (%s past the planner's own target)", intcomma(staff.over()))
	}
	assign := r.PartnerAssignment()
	type tile struct{ key, value, helper, tone, href string }
	tiles := []tile{
		{"monitor_visits_planned_share", ratio(staff.Credited, staff.Target),
			fmt.Sprintf("%s of %s staff visits · %s remaining · %s planned in all: %s core, %s client%s", intcomma(staff.Credited),
				intcomma(staff.Target), intcomma(staff.remaining()), intcomma(staff.Planned), intcomma(get("core_visits")),
				intcomma(get("client_visits")), over), "neutral", ""},
		{"monitor_schools_with_visit", ratio(get("schools_covered"), get("school_count")),
			fmt.Sprintf("%s with a visit planned · %s with a Partner, awaiting its date · %s with neither, of %s",
				intcomma(get("schools_with_visit")), intcomma(get("schools_awaiting_partner")), intcomma(get("unplanned")),
				intcomma(get("school_count"))), "neutral", v.monitor + "&gap=no_visit"},
		{"monitor_schools_with_training", ratio(get("schools_with_training"), get("training_schools")),
			fmt.Sprintf("%s group training · %s in-school training · %s in a cluster meeting, not counted",
				intcomma(get("schools_group_training")), intcomma(get("schools_in_school_training")), intcomma(get("schools_meeting"))),
			"neutral", v.monitor + "&gap=no_training"},
		{"monitor_schools_unplanned", intcomma(get("no_both")), "No visit, no Partner and no training planned",
			ifTone(get("no_both") > 0, "danger"), v.monitor + "&gap=no_both"},
		{"monitor_schools_not_clustered", intcomma(get("not_clustered")), "Cannot join a group training yet",
			ifTone(get("not_clustered") > 0, "warning"), v.monitor + "&gap=not_clustered"},
		{"monitor_partner_share", intcomma(get("partner_assigned_schools")),
			fmt.Sprintf("%s dated · %s awaiting a date · %s of %s schools the Partner should hold are with a Partner now (%s Core, %s beyond staff capacity) · %s still to assign",
				intcomma(get("partner_scheduled")), intcomma(get("partner_awaiting")), intcomma(assign.Credited), intcomma(assign.Target),
				intcomma(r.PartnerCoreSchools), intcomma(r.PartnerBeyondStaff), intcomma(assign.remaining())),
			ifTone(assign.remaining() > 0, "warning"), v.monitor + "&gap=no_partner"},
		{"monitor_schools_in_projects", intcomma(get("in_projects")), "Enrolled in an open Special Project", "", "/projects/monitoring"},
	}
	strip := &screensv1.PageStrip{Title: "Team planning monitor"}
	for _, t := range tiles {
		m := &screensv1.PageMetric{Label: rules.KPILabels[t.key], Value: t.value, Href: t.href}
		if brief := schoolprofile.BriefHelper(t.helper); brief != t.helper {
			m.Note, m.Helper = t.helper, brief
		} else {
			m.Helper = t.helper
		}
		if m.Helper != "" {
			m.Tone = t.tone
		}
		strip.Metrics = append(strip.Metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

func ifTone(when bool, tone string) string {
	if when {
		return tone
	}
	return "neutral"
}

func columns(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, len(labels))
	for i, l := range labels {
		out[i] = &screensv1.PageColumn{Label: l, Numeric: i > 0}
	}
	return out
}

func plainRow(text string) *screensv1.PageRow {
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: text}}}
}

func rowOf(cells ...*cell) *screensv1.PageRow {
	row := &screensv1.PageRow{}
	for _, c := range cells {
		row.Cells = append(row.Cells, c.page())
	}
	return row
}

// personName is a row's Staff cell: the name and, beside it, PL or the role.
func personName(o *Officer) *cell {
	c := &cell{text: o.Name}
	if label := rules.RoleLabels[o.Role]; label != "" {
		if o.Role == rules.RoleCodes[rules.ProgramLeadRole] {
			label = "PL"
		}
		c.add(" " + label)
	}
	return c
}

// readinessCell is _readiness_cell.html: a part's planned, of its target, its
// share, what is left and what is over; or, for a part that asks nothing,
// what was planned anyway.
func (v view) readinessCell(l Line, scope, planned, target, left string, plainTarget bool, recruit, people int, subtotal bool) *cell {
	c := &cell{}
	switch {
	case l.required():
		c.count(l.Planned, v.gapURL(planned, scope, ""), l.tone(), "")
		c.add(" / ")
		if plainTarget {
			c.add(intcomma(l.Target))
		} else {
			c.count(l.Target, v.gapURL(target, scope, ""), "", "")
		}
		c.add(fmt.Sprintf(" · %d%%", l.percent()))
		if l.remaining() > 0 {
			c.add(" ")
			if plainTarget {
				c.add(intcomma(l.remaining()) + " left")
				c.toned("warning")
			} else {
				c.count(l.remaining(), v.gapURL(left, scope, ""), "warning", " left")
			}
		}
		if l.over() > 0 {
			c.add(" " + intcomma(l.over()) + " over")
		}
	case l.Planned > 0:
		c.count(l.Planned, v.gapURL(planned, scope, ""), "", "")
		c.add(" · none required")
	default:
		c.add("None required")
	}
	if recruit > 0 {
		if subtotal {
			c.add(fmt.Sprintf(" %s to recruit %s school%s", intcomma(people), intcomma(recruit), pluralS(recruit)))
		} else {
			c.add(fmt.Sprintf(" recruit %s more school%s", intcomma(recruit), pluralS(recruit)))
		}
		c.toned("danger")
	}
	return c
}

// readinessRow is _readiness_row.html for a person or a subtotal.
func (v view) readinessRow(name *cell, r Readiness, schools int, scope string, subtotal bool) *screensv1.PageRow {
	score := &cell{}
	if r.applicable() {
		tone := "warning"
		switch {
		case r.score() >= 100:
			tone = "success"
		case r.score() >= 50:
			tone = "info"
		}
		score.add(fmt.Sprintf("%d%%", r.score()))
		score.toned(tone)
	} else {
		score.add("Holds no school")
	}
	scheduled := &cell{}
	scheduled.count(r.SchoolsStaffScheduled, v.gapURL("staff_scheduled", scope, ""), "", "")
	scheduled.add(" / ")
	scheduled.count(schools, v.gapURL("all", scope, ""), "", "")
	over := &cell{}
	over.count(r.CoreVisitsOver, v.gapURL("core_visits_over", scope, ""), "danger", "")
	both := &cell{}
	both.count(r.ClientStaffAndPartner, v.gapURL("client_staff_and_partner", scope, ""), "danger", "")
	return rowOf(name, score,
		v.readinessCell(r.StaffVisits(), scope, "staff_scheduled", "staff_queue", "staff_visits_left", false, r.SchoolsToRecruit, r.ShortPeople, subtotal),
		scheduled, over, both,
		v.readinessCell(r.StaffTrainings(), scope, "training", "training_due", "no_training", false, 0, 0, subtotal),
		v.readinessCell(r.PartnerVisits(), scope, "partner_dated", "partner_queue", "partner_visits_left", false, 0, 0, subtotal),
		v.readinessCell(r.PartnerTrainings(), scope, "core_partner_trainings", "core", "core_partner_trainings_left", false, 0, 0, subtotal),
		v.readinessCell(r.PartnerAssignment(), scope, "with_partner", "partner_queue", "partner_left", false, 0, 0, subtotal),
		v.readinessCell(r.ProjectAssignment(), scope, "project_added", "", "", true, 0, 0, subtotal),
	)
}

func (v view) readinessTable() *screensv1.PageBlock {
	t := &screensv1.PageTable{
		Title: "Planned and remaining · FY " + v.fy,
		Subtitle: fmt.Sprintf("%s schools · %s visits not yet planned · readiness %d%%",
			intcomma(v.total.schools(func(t *TypeInventory) int { return t.Total })),
			intcomma(v.total.StaffVisits().remaining()+v.total.PartnerVisits().remaining()), v.total.score()),
		Footnote: readinessAbout,
	}
	if len(v.m.Leads) == 0 {
		t.EmptyMessage = "No Programme Lead or CCEO in your scope."
		return tableBlock(t)
	}
	t.Columns = columns("Staff", "Readiness", "Staff visits", "Schools scheduled by staff", "Core: over 2 Staff or 2 Partner visits",
		"Client: Staff and Partner", "Schools in training", "Partner visits", "Core partner trainings", "Schools with a Partner",
		"Schools added to projects")
	for _, l := range v.m.Leads {
		r := l.Readiness()
		t.Rows = append(t.Rows, plainRow(fmt.Sprintf("%s %d staff · %s schools · readiness %d%%", l.Name, len(l.Officers),
			intcomma(r.schools(func(t *TypeInventory) int { return t.Total })), r.score())))
		for _, o := range l.Officers {
			t.Rows = append(t.Rows, v.readinessRow(personName(o), o.Readiness(), len(o.Schools), officerScope(o), false))
		}
		if len(l.Officers) > 1 {
			t.Rows = append(t.Rows, v.readinessRow(&cell{text: l.Name + " total"}, r, l.schoolCount(), leadScope(l), true))
		}
	}
	return tableBlock(t)
}

func tableBlock(t *screensv1.PageTable) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func (v view) inventoryTable() *screensv1.PageBlock {
	r := v.total
	t := &screensv1.PageTable{
		Title: "Schools by type · FY " + v.fy,
		Subtitle: fmt.Sprintf("%s schools = %s fully planned + %s partly planned + %s not yet planned",
			intcomma(r.schools(func(t *TypeInventory) int { return t.Total })), intcomma(r.schools(func(t *TypeInventory) int { return t.Fully })),
			intcomma(r.schools(func(t *TypeInventory) int { return t.Partly })), intcomma(r.schools(func(t *TypeInventory) int { return t.NotYet }))),
		Footnote: inventoryAbout,
	}
	types := r.types()
	if len(types) == 0 {
		t.EmptyMessage = "No school in your scope."
		return tableBlock(t)
	}
	t.Columns = columns("School type", "Schools", "Fully planned", "Partly planned", "Not yet planned", "In a project")
	for _, row := range types {
		name := &cell{text: row.Label}
		if need(row.Key).visits() == 0 {
			name.add(" outreach only")
		}
		schools, fully, partly, notYet, project := &cell{}, &cell{}, &cell{}, &cell{}, &cell{}
		schools.count(row.Total, v.gapURL("all", "", row.Key), "", "")
		fully.count(row.Fully, v.gapURL("fully_planned", "", row.Key), "", "")
		partly.count(row.Partly, v.gapURL("partly_planned", "", row.Key), "", "")
		notYet.count(row.NotYet, v.gapURL("not_yet_planned", "", row.Key), "danger", "")
		project.count(row.InPj, v.gapURL("in_project", "", row.Key), "", "")
		project.add(" / ")
		project.count(row.Total, v.gapURL("all", "", row.Key), "", "")
		t.Rows = append(t.Rows, rowOf(name, schools, fully, partly, notYet, project))
	}
	return tableBlock(t)
}

func (v view) ledgerTable() *screensv1.PageBlock {
	total, _ := v.ledger["total"].(int)
	unaccounted, _ := v.ledger["unaccounted"].(int)
	summary := "every one on a row or left out by a rule"
	if unaccounted > 0 {
		summary = intcomma(unaccounted) + " on no row"
	}
	t := &screensv1.PageTable{Title: "Planned activities accounted for · FY " + v.fy,
		Subtitle: intcomma(total) + " planned · " + summary}
	if total == 0 {
		t.EmptyMessage = "No activity is planned for this year yet."
		return tableBlock(t)
	}
	t.Columns = columns("Where it is counted", "Planned activities")
	lines, _ := v.ledger["lines"].([]any)
	for _, l := range lines {
		line := l.(map[string]any)
		n, _ := line["count"].(int)
		flagged, _ := line["flagged"].(bool)
		c := &cell{}
		switch {
		case flagged && n > 0:
			c.add(intcomma(n))
			c.toned("danger")
		default:
			c.add(intcomma(n))
		}
		t.Rows = append(t.Rows, rowOf(&cell{text: fmt.Sprint(line["label"])}, c))
	}
	return tableBlock(t)
}

func (v view) checksTable() *screensv1.PageBlock {
	r := v.total
	t := &screensv1.PageTable{Title: "Checks · FY " + v.fy,
		Subtitle: fmt.Sprintf("%s booked more than once · %s past the ceiling · %s Core schools without their Partner half",
			intcomma(r.Duplicates), intcomma(r.OverCeilingPeople), intcomma(r.CoreMissingPartnerHalf))}
	if r.Duplicates+r.OverCeilingPeople+r.CoreMissingPartnerHalf == 0 {
		t.EmptyMessage = "Nothing to look into: no school is booked more than once, nobody is past their ceiling and every Core school's Partner half is handed over."
		return tableBlock(t)
	}
	t.Columns = columns("Staff", "Booked more than once", "Visits past the ceiling", "Core without the Partner half")
	for _, o := range v.m.Officers() {
		or := o.Readiness()
		if or.Duplicates+or.OverCeilingPeople+or.CoreMissingPartnerHalf == 0 {
			continue
		}
		dup, ceiling, half := &cell{}, &cell{}, &cell{}
		dup.count(or.Duplicates, v.gapURL("duplicates", officerScope(o), ""), "danger", "")
		ceiling.add(intcomma(or.OverCeilingVisits))
		if or.OverCeilingVisits > 0 {
			ceiling.toned("danger")
		}
		half.count(or.CoreMissingPartnerHalf, v.gapURL("core_no_partner_half", officerScope(o), ""), "warning", "")
		half.add(" / ")
		half.count(o.coreSchools(), v.gapURL("core", officerScope(o), ""), "", "")
		t.Rows = append(t.Rows, rowOf(personName(o), dup, ceiling, half))
	}
	return tableBlock(t)
}

// detailRow is _monitor_row.html for a person or a subtotal.
func (v view) detailRow(name *cell, f map[string]any, staff Line, scope string, person *Officer) *screensv1.PageRow {
	get := func(key string) int { n, _ := f[key].(int); return n }
	subtotal := person == nil
	count := func(n int, key, tone string) *cell {
		c := &cell{}
		c.count(n, v.gapURL(key, scope, ""), tone, "")
		return c
	}
	of := func(n int, key, tone string, target int, targetKey string) *cell {
		c := count(n, key, tone)
		c.add(" / ")
		c.count(target, v.gapURL(targetKey, scope, ""), "", "")
		return c
	}
	visits := &cell{}
	planTone := staff.tone()
	if get("over_ceiling") > 0 {
		planTone = "danger"
	}
	if person != nil && rules.RoleLabels[person.Role] != "" {
		owner := "owner=" + person.Key
		if person.Role == rules.RoleCodes[rules.ProgramLeadRole] {
			owner = "owner=mine"
		}
		visits.link(intcomma(get("staff_visits")), plansPath+"?period=fy&fy="+v.fy+"&"+owner+"&activity=visits", planTone)
	} else {
		visits.count(get("staff_visits"), v.gapURL("staff_scheduled", scope, ""), staff.tone(), "")
	}
	visits.add(" / " + intcomma(staff.Target))
	if staff.required() {
		visits.add(fmt.Sprintf(" · %d%%", staff.percent()))
	}
	if n := get("schools_to_recruit"); n > 0 {
		if subtotal {
			visits.add(fmt.Sprintf(" %s to recruit %s school%s", intcomma(get("short_people")), intcomma(n), pluralS(n)))
		} else {
			visits.add(fmt.Sprintf(" recruit %s more school%s", intcomma(n), pluralS(n)))
		}
		visits.toned("danger")
	}
	if n := get("over_ceiling"); n > 0 {
		if subtotal {
			visits.add(fmt.Sprintf(" %d past the ceiling by %s", get("over_ceiling_people"), intcomma(n)))
		} else {
			visits.add(" " + intcomma(n) + " over")
		}
		visits.toned("danger")
	}
	if n := get("core_only_people"); n > 0 {
		if subtotal {
			visits.add(fmt.Sprintf(" %d Core-only", n))
		} else {
			visits.add(" Core takes the ceiling")
		}
		visits.toned("danger")
	}
	partner := &cell{}
	partnerTone := fmt.Sprint(f["partner_tone"])
	if person != nil && rules.RoleLabels[person.Role] != "" {
		partner.link(intcomma(get("partner_schools")), partnersPath+"?period=fy&fy="+v.fy+"&member="+person.Key, partnerTone)
	} else {
		partner.count(get("partner_schools"), v.gapURL("with_partner", scope, ""), partnerTone, "")
	}
	partner.add(" / ")
	partner.count(get("partner_needed"), v.gapURL("partner_queue", scope, ""), "", "")
	activities := count(get("partner_scheduled"), "partner_dated", "")
	if n := get("partner_awaiting"); n > 0 {
		activities.add(" + ")
		activities.count(n, v.gapURL("partner_waiting", scope, ""), "", " waiting")
	}
	visited := of(get("schools_with_visit"), "visited", "", get("school_count"), "all")
	if n := get("schools_awaiting_partner"); n > 0 {
		visited.add(" · ")
		visited.count(n, v.gapURL("partner_waiting", scope, ""), "", " with a Partner")
	}
	cells := []*cell{
		name, count(get("school_count"), "all", ""), visits,
		of(get("core_visits"), "core_staff_visits", "", get("core_visit_target"), "core"),
		of(get("client_visits"), "client_staff_visits", "", get("client_visit_target"), "client"),
		of(get("core_staff_trainings"), "core_staff_trainings", fmt.Sprint(f["core_staff_trainings_tone"]), get("core_staff_training_target"), "core"),
		partner,
		of(get("core_partner_visits"), "core_partner_visits", fmt.Sprint(f["core_partner_visits_tone"]), get("core_partner_target"), "core"),
		of(get("core_partner_trainings"), "core_partner_trainings", fmt.Sprint(f["core_partner_trainings_tone"]), get("core_partner_target"), "core"),
		activities, visited,
		of(get("schools_with_training"), "training", "", get("training_schools"), "training_due"),
	}
	for _, g := range rules.GapColumns {
		figure := g[0]
		if alias, ok := rules.GapFigures[g[0]]; ok {
			figure = alias
		}
		cells = append(cells, count(get(figure), g[0], g[2]))
	}
	cells = append(cells, count(get("in_projects"), "in_project", ""))
	return rowOf(cells...)
}

func (v view) detailTable() *screensv1.PageBlock {
	everyone := &Lead{Key: "all", Officers: v.m.Officers()}
	r := v.total
	t := &screensv1.PageTable{
		Title: "Planning against target · FY " + v.fy,
		Subtitle: fmt.Sprintf("%d staff · %s schools · %s of %s staff visits planned", len(everyone.Officers),
			intcomma(everyone.schoolCount()), intcomma(r.StaffVisits().Credited), intcomma(r.StaffVisits().Target)),
		Footnote: detailAbout,
	}
	if len(v.m.Leads) == 0 {
		t.EmptyMessage = "No Programme Lead or CCEO in your scope."
		return tableBlock(t)
	}
	t.Columns = columns("Staff", "Schools", "Visits planned", "Core visits", "Client visits", "Core staff trainings", "Partner schools",
		"Core partner visits", "Core partner trainings", "Partner activities", "Schools visited", "Training planned", "Not clustered",
		"No visit", "No training", "Neither", "In projects")
	for _, l := range v.m.Leads {
		lr := l.Readiness()
		t.Rows = append(t.Rows, plainRow(fmt.Sprintf("%s %d staff · %s schools · %s of %s staff visits planned", l.Name, len(l.Officers),
			intcomma(l.schoolCount()), intcomma(lr.StaffVisits().Credited), intcomma(lr.StaffVisits().Target))))
		for _, o := range l.Officers {
			t.Rows = append(t.Rows, v.detailRow(personName(o), o.figures(), o.Readiness().StaffVisits(), officerScope(o), o))
		}
		if len(l.Officers) > 1 {
			t.Rows = append(t.Rows, v.detailRow(&cell{text: l.Name + " total"}, l.figures(), lr.StaffVisits(), leadScope(l), nil))
		}
	}
	return tableBlock(t)
}
