package teamperformance

import (
	"net/url"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The page's words, as templates/pages/team_performance/index.html and its
// partials write them.
const (
	eyebrow       = "Performance & Coaching"
	stripTitle    = "Performance overview"
	noOfficers    = "No officer holds schools in your scope yet."
	notTracked    = "Not tracked in the system"
	scoreLine     = "Average SSA score this year (latest per school)"
	weeklyNote    = "Achieved counts distinct schools unless the row says otherwise: work once the officer completes and submits it, and records once uploaded, read each time the page opens. Planned is the work in the training and visit plans for the same window (the annual band: the whole year); a row nobody plans, such as an SSA or an upload, has none. A quarter is cumulative from October to its end; the annual figure is the year to date. Targets are the approved Uganda Master Priority Plan allocations and their monthly phasing; a coverage row with no milestone takes its eligible schools. A dash is a figure with no target or no record, never a zero."
	chartsNote    = `Each region's and district's figure counts where the school is; a session counts where most of the schools it reached are, and participants are summed. A region's (or district's) target is each CCEO's target shared across the places their eligible schools are in (client schools for a client area and for recruitment, Core schools for a Core one, else all their schools); a target nobody there holds is "Not placed", so the places add up to the total's target. A Programme Lead's and a CCEO's figures are their own.`
	milestoneNote = `The live sheet's milestones. Achieved is read from the platform's records; the target is the matching Uganda Master Priority Plan milestone, its monthly figures the approved phasing. "Not tracked" is a milestone the platform keeps no record for.`
	gridNote      = "Core (1–4) adds the Core schools at each package step, as the summary's visit columns do; Client/Other trainings add client schools trained, schools trained online, TAM / Biblical Integration online and Early Childhood Education."
	monthNote     = "Targets are the approved allocations; a coverage group with no milestone takes the schools it covers (the Core schools for the Core visit and training groups, the non-core schools for non-core visits)."
	coreNote      = "Expected is four of each a Core school a year; achieved counts each school's package visits or trainings done, up to four. A Core school counts under the number it has reached."
)

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

func th(children ...any) *node { return el("th", "", children...) }
func td(children ...any) *node { return el("td", "", children...) }
func span(class string, children ...any) *node {
	return el("span", class, children...)
}
func link(href string, children ...any) *node  { return el("a", "", children...).attr("href", href) }
func para(class string, children ...any) *node { return el("p", class, children...) }

func tr(cells ...*node) *node { return el("tr", "", cells) }

func headCells(labels ...string) []*node {
	out := []*node{}
	for _, l := range labels {
		out = append(out, th(l))
	}
	return out
}

// groupHead is a table's group heading row (the edify-group-head row).
func groupHead(label, count string) *node {
	inner := span("tp-freeze", span("edify-group-head__label", label))
	if count != "" {
		inner.add(span("edify-group-head__count", count))
	}
	return tr(th(inner))
}

func table(head []*node, body []*node) *node {
	return el("div", "tp-scroll", el("table", "tp-table", el("thead", "", head), el("tbody", "", body)))
}

// cardHead is a tp-card's header: its title and the line beside it.
func cardHead(title, meta string) *node {
	return el("header", "tp-card__head", el("h2", "", title), span("tp-card__meta", meta))
}

// query is QueryDict.urlencode() of (key, value) pairs, in order.
func query(pairs [][2]string) string {
	parts := []string{}
	for _, kv := range pairs {
		parts = append(parts, url.QueryEscape(kv[0])+"="+url.QueryEscape(kv[1]))
	}
	return strings.Join(parts, "&")
}

// pageView is what the request asks for, read as the view reads it.
type pageView struct {
	get    func(string) string
	tab    string
	reads  string
	per    period
	years  []string
	r      *report
	setter bool
	kept   [][2]string // _query(params): the filters a tab link carries
}

func (v *pageView) keptQuery() string { return query(v.kept) }

func (v *pageView) header() *screensv1.PageHeader {
	title := "Team Performance"
	if v.r.roster.own() {
		title = "My Performance"
	}
	desc := "The FY " + v.per.fy + " Weekly Report, read from the platform's records: completed work, school-profile entries and uploads."
	switch {
	case v.r.roster.own():
		desc += " Your own portfolio."
	case v.r.roster.narrowed():
		desc += " Your team: you and the CCEOs you supervise."
	}
	h := &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: strings.Join(strings.Fields(desc), " ")}
	if v.setter {
		// can_set_targets: the year's country targets, on their own page.
		h.Actions = []*screensv1.PageAction{pageheader.Link("Set Country Targets", "/team-performance/country-targets/?fy="+v.per.fy)}
	}
	return h
}

type option struct{ value, label string }

func selectFilter(name, label, chosen string, options []option) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: strings.Join(strings.Fields(o.label), " ")})
	}
	f.Value = ""
	found := false
	for _, o := range options {
		if o.value == chosen && !found {
			f.Value, found = o.value, true
		}
	}
	if !found && len(options) > 0 {
		f.Value = options[0].value
	}
	return f
}

func pairsToOptions(pairs [][2]string) []option {
	out := []option{}
	for _, p := range pairs {
		out = append(out, option{p[0], p[1]})
	}
	return out
}

func (v *pageView) filters(scopes []scopeOption, scopeKey string, dashOfficer *officer) *screensv1.PageBlock {
	per := v.per
	years := []option{}
	for _, y := range v.years {
		years = append(years, option{y, "FY " + y})
	}
	fs := []*screensv1.PageFilter{selectFilter("fy", "Fiscal year", per.fy, years)}
	month := selectFilter("month", "Month", strconv.Itoa(per.month), pairsToOptions(per.monthOptions()))
	switch v.reads {
	case "period":
		kinds := []option{}
		for _, k := range rules.Kinds {
			kinds = append(kinds, option{k[0], k[1]})
		}
		fs = append(fs, selectFilter("period", "Period", per.kind, kinds))
		switch per.kind {
		case kindWeek:
			fs = append(fs, selectFilter("week", "Week", per.week.Format("2006-01-02"), pairsToOptions(per.weekOptions())))
		case kindQuarter:
			fs = append(fs, selectFilter("quarter", "Quarter", strconv.Itoa(per.quarter), pairsToOptions(per.quarterOptions())))
		case kindMonth:
			fs = append(fs, month)
		}
	case "month":
		fs = append(fs, month)
	}
	if v.tab == "weekly" && len(scopes) > 1 {
		opts := []option{}
		for _, s := range scopes {
			opts = append(opts, option{s.key, s.label})
		}
		fs = append(fs, selectFilter("scope", "Report for", scopeKey, opts))
	} else if v.tab == "dashboard" && !v.r.roster.own() {
		opts := []option{{"", "All CCEOs, ranked"}}
		for _, o := range v.r.roster.officers() {
			opts = append(opts, option{o.staffID, o.name})
		}
		chosen := "\x00none"
		if dashOfficer != nil {
			chosen = dashOfficer.staffID
		}
		fs = append(fs, selectFilter("officer", "CCEO", chosen, opts))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: fs, Hidden: map[string]string{"tab": v.tab}}}}
}

func (v *pageView) tabsBlock() *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Scrolls: true}
	base := v.keptQuery()
	for _, t := range rules.Tabs {
		href := "?" + base
		if base != "" {
			href += "&"
		}
		href += "tab=" + t[0]
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{
			Label: strings.ReplaceAll(t[1], "{month}", v.per.monthLabel()), Href: href, Active: t[0] == v.tab})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

func strip(figs ...schoolprofile.StripFigure) *node {
	return preBlock(schoolprofile.Strip(stripTitle, figs))
}

func fig(label, value, helper string) schoolprofile.StripFigure {
	return schoolprofile.StripFigure{Label: label, Value: value, Helper: helper}
}

// ── Executive Summary (partials/team_performance/summary.html) ──────────────

func (v *pageView) summaryTab() []*node {
	r := v.r
	sum := r.executiveSummary(v.get("by"), v.get("in_region"), v.get("in_lead"))
	now := sum.now
	bd := sum.bd
	link := func(picked [][2]string) string {
		pairs := append([][2]string{}, v.kept...)
		pairs = append(pairs, [2]string{"tab", "summary"})
		values := map[string]string{}
		for _, kv := range picked {
			values[kv[0]] = kv[1]
		}
		for _, key := range rules.SummaryKept {
			if values[key] != "" {
				pairs = append(pairs, [2]string{key, values[key]})
			}
		}
		return query(pairs)
	}
	out := []*node{strip(
		fig("Total Portfolio", num(now["portfolio"]), "Active "+num(now["active"])+" · Inactive "+num(now["inactive"])),
		fig("Active School Rate", pct(now["active_pct"]), num(now["active"])+" of "+num(now["portfolio"])+" schools operating"),
		fig("Core Recruitment", pct(now["core_recruitment_pct"]), "Achieved "+num(now["core_recruitment"])+" / "+num(now["core_recruitment_target"])),
		fig("Client SSA Completion", pct(now["ssa_client_pct"]), "Achieved "+num(now["ssa_client"])+" / "+num(now["ssa_client_target"])),
		fig("Discipleship Clubs", pct(now["dc_pct"]), "Active DC "+num(now["dc"])+" / "+num(now["dc_data"])+" with DC data"),
	)}

	regions := el("section", "tp-card", cardHead("Performance Against Target · By "+bd.label(),
		"Year to the end of "+v.per.label()+" · change since the end of "+v.per.previousLabel()))
	if len(bd.levels) > 1 {
		nav := el("nav", "tp-subnav")
		for _, level := range bd.levels {
			nav.add(link2("?"+link([][2]string{{"by", level}}), "By "+rules.BreakdownLabels[level]))
		}
		by := el("div", "tp-by", nav)
		if bd.narrowedTo() != "" {
			var what *node
			if bd.inLead != "" {
				what = span("", bd.inLeadLabel+"’s CCEOs")
			} else {
				noun := "CCEOs"
				if bd.level == levelLead {
					noun = "Programme Leads"
				}
				what = span("", bd.inRegion+" · "+noun)
			}
			by.add(para("tp-trail", link2("?"+link([][2]string{{"by", bd.levels[0]}}), "All regions"), span("", "›"), what))
		} else if bd.below() != "" {
			noun := "CCEOs"
			if bd.level == levelRegion {
				noun = "Programme Leads"
			}
			by.add(para("tp-note", "Open a "+pyLower(bd.label())+" to see its "+noun+"."))
		}
		regions.add(by)
	}
	if len(bd.columns) == 0 {
		var msg string
		switch {
		case bd.inRegion != "":
			what := "CCEO"
			if bd.level == levelLead {
				what = "Programme Lead team"
			}
			msg = "No " + what + " works in " + bd.inRegion + " yet."
		case bd.inLead != "":
			msg = bd.inLeadLabel + " has no CCEOs listed yet."
		default:
			msg = "Nothing to break down by " + pyLower(bd.label()) + " yet."
		}
		regions.add(para("tp-note", msg))
	}
	band := []*node{th(""), th(r.roster.homeLabel())}
	for _, c := range bd.columns {
		h := th()
		if len(c.drill) > 0 {
			h.add(link2("?"+link(c.drill), c.label))
		} else {
			h.add(c.label)
		}
		if c.sub != "" {
			h.add(" ", span("tp-muted", "· "+c.sub))
		}
		band = append(band, h)
	}
	labels := []string{"Target Area", "Target", "Achieved", "%", "Change"}
	for range bd.columns {
		labels = append(labels, "Target", "Achieved", "%")
	}
	body := []*node{}
	for _, sec := range sum.sections {
		body = append(body, groupHead(sec.section, strconv.Itoa(len(sec.areas))+" target"+plural(len(sec.areas))))
		for _, a := range sec.areas {
			row := tr(th(unitLabel(a.label, a.m.Unit)), td(num(a.target)), td(num(a.achieved)), td(span("tp-pct", pct(a.pct))), td(signed(a.change)))
			for _, t := range a.teams {
				row.add(td(num(t.target)), td(num(t.achieved)), td(span("tp-pct", pct(t.pct))))
			}
			body = append(body, row)
		}
	}
	regions.add(table([]*node{tr(band...), tr(headCells(labels...)...)}, body))
	out = append(out, regions)

	for _, sec := range sum.sections {
		section := sec.section
		out = append(out, el("h2", "tp-section-title", section))
		pending := el("div", "tp-card", para("tp-note", "Loading the "+section+" charts…"))
		pending.later = func() *node {
			charts := r.sectionCharts(section, bd.level, bd.inRegion, bd.inLead)
			if charts == nil {
				return nil
			}
			return chartsPart(charts)
		}
		out = append(out, pending)
	}
	out = append(out, para("tp-note", chartsNote))

	delivery := el("section", "tp-card", cardHead("Program Delivery & Operational Milestones", "Year to the end of "+v.per.label()))
	rows := []*node{}
	for _, d := range sum.milestones {
		status := span("tp-muted", "No target")
		if d.status != "" {
			status = span("tp-chip", d.status)
		}
		rows = append(rows, tr(th(d.label), td(num(d.cell.target)), td(num(d.cell.achieved)), td(signed(d.cell.variance())),
			td(span("tp-pct", pct(d.cell.pct()))), td(status), td(d.target.source)))
	}
	delivery.add(table([]*node{tr(headCells("Milestone / Workstream", "Target", "Achieved", "Variance", "% Attained", "Status", "Target Source")...)}, rows))
	out = append(out, delivery)
	return []*node{el("div", "tp-stack", out)}
}

func link2(href, text string) *node { return link(href, text) }

func unitLabel(label, unit string) []any {
	if unit != unitSchools {
		return []any{label, " ", span("tp-muted", "("+unit+")")}
	}
	return []any{label}
}

// chartsPart is partials/team_performance/area_charts.html.
func chartsPart(areas []*area) *node {
	stack := el("div", "tp-stack")
	for _, a := range areas {
		meta := num(a.achieved) + " of " + num(a.target)
		if a.pct != nil {
			meta += " · " + pct(a.pct)
		}
		if a.status != "" {
			meta += " · " + a.status
		}
		if a.m.Unit != unitSchools {
			meta += " · " + a.m.Unit
		}
		row := el("div", "tp-area-row")
		for _, c := range a.charts {
			holder := el("div", "").attr("data-tp-chart", c.level)
			holder.add(el("h3", "tp-chart-title", a.label+" by "+c.label))
			holder.add(targetChart(c.bars, c.label)...)
			row.add(holder)
		}
		stack.add(el("section", "tp-card", cardHead(a.label+": Target vs. Achieved", meta), row))
	}
	root := el("#root", "", stack)
	return root
}

// targetChart is partials/team_performance/target_chart.html.
func targetChart(bs []bar, heading string) []any {
	chart := el("div", "tp-chart")
	for _, b := range bs {
		label := span("tp-chart__label", b.label)
		if b.place != "" {
			label.add(el("br", ""), span("tp-muted", b.place))
		}
		label.add(el("br", ""), num(b.achieved)+" / "+num(b.target))
		chart.add(el("div", "tp-chart__group",
			el("div", "tp-chart__bars",
				span("tp-chart__bar tp-chart__bar--target").attr("title", b.label+" target: "+num(b.target)),
				span("tp-chart__bar").attr("title", b.label+" achieved: "+num(b.achieved))),
			label).attr("data-tp-bar", b.label))
	}
	legend := el("div", "tp-chart-legend", span("is-target", "Target"), span("", "Achieved"))
	rows := []*node{}
	for _, b := range bs {
		name := th(b.label)
		if b.place != "" {
			name.add(" ", span("tp-muted", "· "+b.place))
		}
		rows = append(rows, tr(name, td(num(b.target)), td(num(b.achieved)), td(signed(b.variance)), td(span("tp-pct", pct(b.pct)))))
	}
	return []any{chart, legend, table([]*node{tr(headCells(heading, "Target", "Achieved", "Variance", "%")...)}, rows)}
}

// ── Detailed Country Report (weekly.html) ───────────────────────────────────

func (v *pageView) weeklyTab(opt scopeOption) []*node {
	r := v.r
	per := v.per
	card := el("section", "tp-card", cardHead("Detailed Country Report – "+opt.label, "FY "+per.fy+" · monthly performance for "+per.monthLabel()))
	band := []*node{th(""), th("Monthly Performance · " + per.monthLabel())}
	for q := 1; q <= 4; q++ {
		band = append(band, th("Q"+strconv.Itoa(q)+" Cumulative Performance"))
	}
	band = append(band, th("Annual Performance against Annual Target"), th(""))
	labels := []string{"Category", "Target", "Planned", "Achieved", "Variance", "%"}
	for q := 1; q <= 4; q++ {
		labels = append(labels, "Target", "Planned", "Achieved", "Variance", "%")
	}
	labels = append(labels, "Annual Target", "Planned", "Cumulative Achieved", "Variance", "% of Annual", "Status")
	body := []*node{}
	for _, sec := range weeklySections() {
		body = append(body, groupHead(sec.section, ""))
		for _, m := range sec.measures {
			row := r.row(m, opt.scope)
			line := tr(th(unitLabel(m.Label, m.Unit)))
			if !m.Tracked {
				line.add(td(notTracked), td(num(row.year.target)), td(), td(), td(), td(), td())
				body = append(body, line)
				continue
			}
			line.add(cellTDs(row.month))
			for _, q := range row.quarters {
				if q.future {
					line.add(td(dash), td(num(q.planned)), td(dash), td(dash), td(dash))
					continue
				}
				line.add(cellTDs(q.cell))
			}
			line.add(cellTDs(row.year))
			status := td()
			if row.status != "" {
				status.add(span("tp-chip", row.status))
			}
			line.add(status)
			body = append(body, line)
		}
	}
	card.add(table([]*node{tr(band...), tr(headCells(labels...)...)}, body), para("tp-note", weeklyNote))
	return []*node{card}
}

func cellTDs(c cell) []*node {
	return []*node{td(num(c.target)), td(num(c.planned)), td(num(c.achieved)), td(signed(c.variance())), td(span("tp-pct", pct(c.pct())))}
}

type weeklySection struct {
	section  string
	measures []*measure
}

func weeklySections() []weeklySection {
	out := []weeklySection{}
	for _, section := range rules.Sections {
		ws := weeklySection{section: section}
		for i := range rules.Measures {
			if m := &rules.Measures[i]; m.Section == section && m.Weekly {
				ws.measures = append(ws.measures, m)
			}
		}
		out = append(out, ws)
	}
	return out
}

// ── Strategic Milestones (milestones.html) ──────────────────────────────────

func (v *pageView) milestonesPart(embedded bool) []*node {
	sheet := v.r.milestones()
	per := v.per
	stack := el("div", "tp-stack")
	if !embedded {
		stack.add(strip(
			fig("Total Milestones", num(ptr(float64(sheet.count))), "Strategic targets tracked"),
			fig("Priority Areas", num(ptr(float64(sheet.domainCount))), "Edify program domains"),
			fig("Cumulative Target", num(ptr(sheet.toDateTarget)), "Planned targets to the end of "+per.label()),
			fig("Cumulative Pacing", pct(sheet.pacing), "Overall completion rate"),
			fig("Trackers Provisioned", num(ptr(float64(sheet.tracked)))+" of "+num(ptr(float64(sheet.count))), "Milestones the records measure"),
		))
	}
	card := el("section", "tp-card", cardHead("Strategic Milestones & Operational Trackers", per.label()+" · cumulative to its end · the year"))
	band := []*node{th(""), th(per.label()), th("Cumulative"), th("Country Target"), th("")}
	labels := headCells("Strategic Milestone & Mode", "Target", "Achieved", "%", "Target", "Achieved", "%", "Target", "Achieved", "% Goal", "Status", "Responsible Lead", "Tracker")
	body := []*node{}
	kinds := rules.StrategicKinds
	for _, d := range sheet.domains {
		body = append(body, groupHead(d.domain, strconv.Itoa(len(d.rows))+" milestone"+plural(len(d.rows))))
		for _, row := range d.rows {
			line := tr(th(row.spec.Title, " ", span("tp-muted", "· "+row.spec.Mode)))
			switch row.spec.Kind {
			case kinds.Untracked:
				line.add(td(notTracked), td(num(row.year.target)), td(), td())
			case kinds.Score:
				line.add(td(scoreLine), td(dash), td(num(row.year.achieved)), td())
			case kinds.Rate:
				line.add(td(dash), td(dash), td(),
					td(pct(row.toDate.target)), td(pct(row.toDate.achieved)), td(span("tp-pct", pct(row.toDate.pct()))),
					td(pct(row.year.target)), td(pct(row.year.achieved)), td(span("tp-pct", pct(row.year.pct()))))
			default:
				for _, c := range []cell{row.inPeriod, row.toDate, row.year} {
					line.add(td(num(c.target)), td(num(c.achieved)), td(span("tp-pct", pct(c.pct()))))
				}
			}
			line.add(td(span("tp-chip", row.status)), td(row.spec.Lead))
			if row.tracker[0] != "" {
				line.add(td(link(row.tracker[0], "↗ "+row.tracker[1])))
			} else {
				line.add(td(span("tp-muted", dash)))
			}
			body = append(body, line)
		}
	}
	card.add(table([]*node{tr(band...), tr(labels...)}, body), para("tp-note", milestoneNote))
	stack.add(card)
	return []*node{stack}
}

// ── CCEO Officer Performance & Milestones (dashboard.html) ──────────────────

func (v *pageView) dashboardTab(view, lead, leadLabel, sortKey string, officer *officer, dashQuery string) []*node {
	r := v.r
	per := v.per
	b := r.cceoBoard(lead, sortKey)
	t := b.total
	stack := el("div", "tp-stack")
	nav := el("nav", "tp-subnav")
	for _, dv := range rules.DashboardViews {
		label := dv[1]
		switch dv[0] {
		case "cceos":
			label += " (" + strconv.Itoa(b.officers) + ")"
		case "milestones":
			label += " (54)"
		}
		href := "?" + dashQuery
		if dashQuery != "" {
			href += "&"
		}
		nav.add(link(href+"tab=dashboard&view="+dv[0], label))
	}
	stack.add(el("section", "tp-card",
		el("div", "", el("h2", "tp-dash-title", "CCEO Officer Performance & Strategic Milestones"),
			para("tp-card__meta", "Regional Field Tracking · School Visits & Trainings · Recruitment · SSA Reviews · year to the end of "+per.monthLabel())),
		nav))
	base := "?fy=" + per.fy + "&month=" + strconv.Itoa(per.month) + "&tab=dashboard&view=" + view + "&sort=" + sortKey
	if !r.roster.own() {
		chips := el("nav", "tp-chips", span("tp-chips__label", "Programme Lead"),
			link(base, "All ", span("", strconv.Itoa(len(r.roster.officers())))))
		for _, tm := range r.roster.teams {
			chips.add(link(base+"&lead="+urlencodeFilter(tm.key), tm.label+" ", span("", strconv.Itoa(len(tm.officers)))))
		}
		stack.add(chips)
	}
	stack.add(strip(
		fig("Active CCEOs", num(ptr(float64(b.officers))), "Across "+strconv.Itoa(len(b.rollups))+" Programme Lead team"+plural(len(b.rollups))),
		fig("Portfolio Schools", num(t["portfolio"]), pct(t["active_pct"])+" active"),
		fig("Core Recruited", num(t["recruit"]), "New Core schools"),
		fig("School Visits", num(t["visits"]), "Core ("+num(t["visits_core"])+") + Non-Core ("+num(t["visits_noncore"])+")"),
		fig("Trainings Logged", num(t["trainings"]), "Core ("+num(t["trainings_core"])+") + Client/Other ("+num(t["trainings_other"])+")"),
		fig("SSA Reviews", num(t["ssa"]), "Cohort "+num(t["ssa_cohort"])+" · Client "+num(t["ssa_client"])),
	))
	deepLink := func(id string) string {
		return "?fy=" + per.fy + "&month=" + strconv.Itoa(per.month) + "&tab=dashboard&view=deep&officer=" + id
	}
	switch view {
	case "cceos":
		sorts := el("nav", "tp-chips", span("tp-chips__label", "Sort officers by"))
		for _, s := range rules.Sorts {
			href := "?fy=" + per.fy + "&month=" + strconv.Itoa(per.month) + "&tab=dashboard&view=cceos&sort=" + s[0]
			if lead != "" {
				href += "&lead=" + urlencodeFilter(lead)
			}
			sorts.add(link(href, s[1]))
		}
		sorts.add(span("tp-chips__count", "Showing "+strconv.Itoa(b.officers)+" officer"+plural(b.officers)))
		stack.add(sorts)
		cards := el("div", "tp-cards")
		for _, c := range b.cards {
			f := c.f
			target := "Not set"
			if f["recruit_target"] != nil {
				target = num(f["recruit_target"])
			}
			cards.add(el("article", "tp-card tp-officer",
				el("header", "tp-officer__head", el("h3", "", c.o.name), span("tp-badge", orDash(c.region))),
				para("tp-officer__meta", "Portfolio: ", el("strong", "", num(f["portfolio"])), " schools ("+pct(f["active_pct"])+" active)"),
				el("div", "tp-stats",
					stat("Visits", num(f["visits"]), "Core (1–4): "+num(f["visits_core"])+" · Non-Core: "+num(f["visits_noncore"])),
					stat("Trainings", num(f["trainings"]), "Core: "+num(f["trainings_core"])+" · Client/Other: "+num(f["trainings_other"])),
					stat("Recruitment", num(f["recruit"]), "Target: "+target),
					stat("SSA Reviews", num(f["ssa"]), "Cohort: "+num(f["ssa_cohort"])+" · Client: "+num(f["ssa_client"]))),
				el("footer", "tp-officer__foot", span("", "Enrollment: ", el("strong", "", pct(f["enrol_pct"]))),
					link(deepLink(c.o.staffID), "Deep-Dive Scorecard →"))))
		}
		if len(b.cards) == 0 {
			cards.add(emptyState("No officer in this team."))
		}
		stack.add(cards)
	case "deep":
		if officer != nil {
			stack.add(v.deepDive(officer))
		}
	case "milestones":
		stack.add(v.milestonesPart(true))
	case "leads":
		cards := el("div", "tp-cards")
		for _, roll := range b.rollups {
			f := roll.f
			cards.add(el("article", "tp-card tp-officer",
				el("header", "tp-officer__head", el("h3", "", roll.t.label), span("tp-badge", strconv.Itoa(roll.officers)+" officer"+plural(roll.officers))),
				para("tp-officer__meta", "Total portfolio: ", el("strong", "", num(f["portfolio"])), " schools · "+pct(f["active_pct"])+" active"),
				el("div", "tp-stats",
					stat("Total Visits", num(f["visits"]), ""),
					stat("Total Trainings", num(f["trainings"]), ""),
					stat("Recruitment", num(f["recruit"]), ""),
					stat("SSA Reviews", num(f["ssa"]), ""))))
		}
		stack.add(cards)
	default:
		card := el("section", "tp-card", cardHead("Officer Performance Master Ledger",
			"Year to the end of "+per.monthLabel()+" · the "+per.monthLabel()+" Summary's figures · "+strconv.Itoa(b.officers)+" officer"+plural(b.officers)))
		head := headCells("Region", "Programme Lead", "CCEO", "Portfolio", "Active", "Active %", "Core Recruited", "Baseline SSA", "Cohort SSA", "Client SSA",
			"Core (1–4)", "Non-Core (FY)", "Total Visits", "Core Trainings", "Client/Other", "Total Trainings")
		rows := []*node{}
		for _, c := range b.grid {
			f := c.f
			rows = append(rows, tr(td(orDash(c.region)), td(c.team), th(c.o.name),
				td(num(f["portfolio"])), td(num(f["active"])), td(span("tp-pct", pct(f["active_pct"]))),
				td(num(f["recruit"])), td(num(f["baseline_ssa"])), td(num(f["ssa_cohort"])), td(num(f["ssa_client"])),
				td(num(f["visits_core"])), td(num(f["visits_noncore"])), td(el("strong", "", num(f["visits"]))),
				td(num(f["trainings_core"])), td(num(f["trainings_other"])), td(el("strong", "", num(f["trainings"])))))
		}
		total := r.roster.homeLabel()
		if lead != "" {
			total = leadLabel + " Total"
		}
		rows = append(rows, tr(td(), td(), th(total),
			td(num(t["portfolio"])), td(num(t["active"])), td(pct(t["active_pct"])),
			td(num(t["recruit"])), td(num(t["baseline_ssa"])), td(num(t["ssa_cohort"])), td(num(t["ssa_client"])),
			td(num(t["visits_core"])), td(num(t["visits_noncore"])), td(num(t["visits"])),
			td(num(t["trainings_core"])), td(num(t["trainings_other"])), td(num(t["trainings"]))))
		card.add(table([]*node{tr(head...)}, rows), para("tp-note", gridNote))
		stack.add(card)
	}
	return []*node{stack}
}

func stat(label, value, small string) *node {
	n := el("div", "tp-stat", span("tp-stat__label", label), el("strong", "", value))
	if small != "" {
		n.add(el("small", "", small))
	}
	return n
}

func box(label, value string) *node {
	return el("div", "tp-box", span("", label), el("strong", "", value))
}

func boxSmall(label, value, small string) *node {
	return el("div", "tp-box", span("", label), el("strong", "", value), el("small", "", small))
}

func orDash(s string) string {
	if s == "" {
		return dash
	}
	return s
}

func emptyState(message string) *node {
	return el("div", "edify-empty-state", para("edify-empty-state__message", message))
}

// urlencodeFilter is Django's |urlencode: quote(value, safe="/").
func urlencodeFilter(s string) string {
	return strings.ReplaceAll(url.PathEscape(s), "%2F", "/")
}

func (v *pageView) deepDive(o *officer) []*node {
	r := v.r
	t := r.roster.teamOf(o.staffID)
	teamLabel := ""
	if t != nil {
		teamLabel = t.label
	}
	f := r.officerFigures(officerScope(o.staffID))
	head := el("header", "tp-officer__head", el("h3", "", o.name), span("tp-badge", orDash(o.region)))
	if teamLabel != "" {
		head.add(span("tp-badge", teamLabel))
	}
	recruitTarget := "Not set"
	if f["recruit_target"] != nil {
		recruitTarget = num(f["recruit_target"]) + " (Var: " + signed(f["recruit_var"]) + ")"
	}
	deep := el("section", "tp-card tp-deep", head,
		para("tp-officer__meta", "Total assigned portfolio: ", el("strong", "", num(f["portfolio"])), " schools · Active: ",
			el("strong", "", num(f["active"])), " · Inactive: "+num(f["inactive"])+" ("+pct(f["active_pct"])+" active rate)"),
		el("div", "tp-stats tp-stats--four",
			stat("Total School Visits", num(f["visits"]), "Core: "+num(f["visits_core"])+" · Non-Core (FY): "+num(f["visits_noncore"])),
			stat("Trainings Delivered", num(f["trainings"]), "Core: "+num(f["trainings_core"])+" · Client: "+num(f["trainings_other"])),
			stat("Core Recruitment", num(f["recruit"]), "Target: "+recruitTarget),
			stat("SSA & Data Reviews", num(f["ssa"]), "Cohort: "+num(f["ssa_cohort"])+" · Client: "+num(f["ssa_client"]))))
	panelHead := func(title, badge string) *node {
		return el("header", "tp-panel__head", el("h3", "", title), span("tp-badge", badge))
	}
	sub := func(title, aside string) *node {
		n := el("h4", "tp-panel__sub", title)
		if aside != "" {
			n.add(" ", span("", aside))
		}
		return n
	}
	visitBoxes := el("div", "tp-boxes")
	for n := 1; n <= 4; n++ {
		label := strconv.Itoa(n) + " Visit" + plural(n)
		if n == 4 {
			label = "4+ Visits"
		}
		visitBoxes.add(box(label, num(f["core_visit_step_"+itoa(n)])))
	}
	trainingBoxes := el("div", "tp-boxes")
	for n := 1; n <= 4; n++ {
		trainingBoxes.add(box("Training "+itoa(n), num(f["core_training_step_"+itoa(n)])))
	}
	grid := el("div", "tp-deep-grid",
		el("section", "tp-card tp-panel", panelHead("School Visits Breakdown", "Total: "+num(f["visits"])),
			sub("Core School Visits (Staff & Partner)", "Subtotal: "+num(f["visits_core"])), visitBoxes,
			sub("Non-Core / Client School Visits", "FY Total: "+num(f["visits_noncore"])),
			el("div", "tp-boxes", box("FY Visited (Staff/Partner)", num(f["visits_noncore"])),
				box("This Month (Staff)", num(f["visits_noncore_month_staff"])), box("FY Visited (Partner)", num(f["visits_noncore_partner"])))),
		el("section", "tp-card tp-panel", panelHead("Trainings Delivery Matrix", "Total: "+num(f["trainings"])),
			sub("Core School Trainings (Modules 1–4)", "Subtotal: "+num(f["trainings_core"])), trainingBoxes,
			sub("Client & Specialized Domains", "Subtotal: "+num(f["trainings_other"])),
			el("div", "tp-boxes", box("Client Trainings", num(f["trainings_client"])), box("Online Modules", num(f["trainings_online"])),
				box("TAM / Biblical", num(f["trainings_tam"])), box("Early Childhood", num(f["trainings_ece"])))),
		el("section", "tp-card tp-panel", panelHead("Core Recruitment & Portfolio Health", "Achieved: "+num(f["recruit"])),
			el("div", "tp-boxes", box("Annual Target", num(f["recruit_target"])), box("Recruited FY", num(f["recruit"])),
				box("Baseline SSA", num(f["baseline_ssa"])), box("Variance", signed(f["recruit_var"]))),
			sub("Discipleship Club (DC) Rollout", ""),
			el("div", "tp-boxes", box("DC Data Collected", num(f["dc_data"])), box("With a Club", num(f["dc"])), box("% With DC", pct(f["dc_pct"])))),
		el("section", "tp-card tp-panel", panelHead("Data & SSA Reviews", "Reviews: "+num(f["ssa"])),
			el("div", "tp-boxes",
				boxSmall("Cohort SSA (Core, Yr 1–3)", num(f["ssa_cohort"]), "Target: "+num(f["ssa_cohort_target"])+" (Var: "+signed(f["ssa_cohort_var"])+")"),
				boxSmall("Client SSA to Date", num(f["ssa_client"]), "Of "+num(f["ssa_client_target"])+" client schools")),
			sub("School Demographics Coverage", ""),
			el("div", "tp-boxes", box("Enrollment Completion", pct(f["enrol_pct"])), box("Metrics Tracking Rate", pct(f["metrics_pct"])))))
	return []*node{deep, grid}
}

// ── {Month} {Year} Summary (month.html) ─────────────────────────────────────

func columnText(cols figures, key string) string {
	if strings.HasSuffix(key, "_p") {
		return pct(cols[key])
	}
	return num(cols[key])
}

func (v *pageView) monthTab() []*node {
	r := v.r
	s := r.monthSummary()
	label := v.per.monthLabel()
	card := el("section", "tp-card", cardHead(label+" Summary Performance", `Year to the end of `+label+`; "this month" columns read `+label+` alone`))
	band := []*node{th("")}
	labels := []*node{th("CCEO")}
	for _, g := range rules.SummaryGroups {
		band = append(band, th(g.Heading))
		for _, c := range g.Columns {
			labels = append(labels, th(c[1]))
		}
	}
	values := func(cols figures, wrapped bool) []*node {
		out := []*node{}
		for _, g := range rules.SummaryGroups {
			for _, c := range g.Columns {
				if wrapped {
					out = append(out, td(span("tp-pct", columnText(cols, c[0]))))
				} else {
					out = append(out, td(columnText(cols, c[0])))
				}
			}
		}
		return out
	}
	body := []*node{}
	for _, g := range s.groups {
		count := ""
		if g.t.leadName != "" {
			count = "Programme Lead · "
		}
		count += strconv.Itoa(len(g.lines)) + " officer" + plural(len(g.lines))
		body = append(body, tr(th(span("tp-freeze", span("edify-group-head__label", g.t.label), " ", span("edify-group-head__count", count)))))
		for _, line := range g.lines {
			body = append(body, tr(append([]*node{th(line.o.name)}, values(line.cols, true)...)...))
		}
		if !r.roster.narrowed() {
			body = append(body, tr(append([]*node{th(g.t.label + " Total")}, values(g.total, false)...)...))
		}
	}
	body = append(body, tr(append([]*node{th(r.roster.homeLabel())}, values(s.national, false)...)...))
	body = append(body, tr(append([]*node{th("End of the month before")}, values(s.lastMonth, false)...)...))
	note := monthNote
	if s.unlisted != 0 {
		note += " The national total also holds " + num(ptr(float64(s.unlisted))) + " school" + plural(s.unlisted) + " whose account owner is not an active CCEO or Programme Lead."
	}
	card.add(table([]*node{tr(band...), tr(labels...)}, body), para("tp-note", note))
	return []*node{card}
}

// ── Core Visits & Training (core.html) ──────────────────────────────────────

func (v *pageView) coreTab() []*node {
	r := v.r
	lines, total := r.corePackage()
	kinds := [][2]string{{"visit", "Visits"}, {"training", "Trainings"}}
	card := el("section", "tp-card", cardHead("Core School Visits & Trainings", "FY "+v.per.fy+" to date · each Core school's package visits and trainings done, as on Core School Oversight"))
	row1 := []*node{th(""), th(""), th(""), th("")}
	row2 := []*node{th(""), th(""), th(""), th("")}
	row3 := headCells("CCEO", "Region", "Programme Lead", "Core Schools")
	for _, k := range kinds {
		row1 = append(row1, th("Core School "+k[1]))
		row2 = append(row2, th("Schools by "+k[1]+" Done"), th("All Four"), th("Three or More"))
		row3 = append(row3, headCells("1", "2", "3", "4", "Expected", "Achieved", "Achieved %", "Schools", "% of Core")...)
	}
	kindCells := func(f figures, wrapped bool) []*node {
		wrap := func(text string) *node {
			if wrapped {
				return td(span("tp-pct", text))
			}
			return td(text)
		}
		return []*node{td(num(f["one"])), td(num(f["two"])), td(num(f["three"])), td(num(f["four"])),
			td(num(f["expected"])), td(num(f["done"])), wrap(pct(f["pct"])), td(num(f["three_plus"])), wrap(pct(f["three_pct"]))}
	}
	body := []*node{}
	for _, line := range lines {
		row := tr(th(line.o.name), td(orDash(line.region)), td(line.team), td(num(ptr(line.f.core))))
		for _, k := range kinds {
			row.add(kindCells(line.f.kinds[k[0]], true))
		}
		body = append(body, row)
	}
	grand := tr(th(r.roster.homeLabel()), td(), td(), td(num(ptr(total.core))))
	for _, k := range kinds {
		grand.add(kindCells(total.kinds[k[0]], false))
	}
	body = append(body, grand)
	card.add(table([]*node{tr(row1...), tr(row2...), tr(row3...)}, body))
	return []*node{el("div", "tp-stack", card, para("tp-muted", coreNote))}
}
