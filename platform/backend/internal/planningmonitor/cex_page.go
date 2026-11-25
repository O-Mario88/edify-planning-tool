package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// The Execution & Completion tab (country_execution_views.execution_page,
// partials/country_execution/page.html and workspace.html, as the feed
// reads them).

type node = feeddom.Node

var el = feeddom.El

// walk reads markup as the feed reads it.
func walk(nodes ...any) []*screensv1.PageBlock { return feeddom.Walk(el("div", "", nodes...), nil) }

func itoaP(p *int) string {
	if p == nil {
		return ""
	}
	return strconv.Itoa(*p)
}

func pctOrDash(p *int) string {
	if p == nil {
		return "(—)"
	}
	return "(" + strconv.Itoa(*p) + "%)"
}

// CountryExecutionPage is execution_page for the reader.
func CountryExecutionPage(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (*screensv1.GetPageResponse, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f := cexReadFilters(q, today)
	s, err := buildCEXSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return nil, err
	}
	country, err := cpoCountry(ctx, db, scope)
	if err != nil {
		return nil, err
	}
	reader := cpoReaderFor(p.ActiveRole, slices.Contains(rules.CountryExecution.Page.ExportRoles, p.ActiveRole))
	table := q["table"]
	if !slices.ContainsFunc(rules.CountryExecution.Page.ViewBy, func(v [2]string) bool { return v[0] == table }) {
		table = "lead"
	}
	reader.seesSchools = !scope.SummaryOnly
	asked := 1
	if n, ok := clusterpage.PyInt(q["page"]); ok {
		asked = n
	}
	position, err := s.targetPosition(ctx, db)
	if err != nil {
		if errors.Is(err, targets.ErrHandOn) {
			err = errCEXHandOn
		}
		return nil, err
	}
	blocks := []*screensv1.PageBlock{lensTabsAt("execution"), s.filterBlock(table)}
	notice, err := s.notice(ctx, db, country)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, walk(notice)...)
	blocks = append(blocks, walk(s.cardNodes())...)
	blocks = append(blocks, walk(s.targetNote(position))...)
	blocks = append(blocks, s.chartBlocks()...)
	blocks = append(blocks, walk(s.readingNodes(reader))...)
	blocks = append(blocks, s.requirementBlocks()...)
	reminders, err := cexOpenCounts(ctx, db, f.fy)
	if err != nil {
		return nil, err
	}
	var body *node
	switch table {
	case "cceo":
		body = s.ownerTableNodes(reader, reminders)
	case "partner":
		rows, err := s.partnerRows(ctx, db)
		if err != nil {
			return nil, err
		}
		body = s.partnerTableNodes(rows)
	case "school":
		body = el("div", "", s.schoolTableNodes(reader, asked)...)
	case "activity":
		nodes, err := s.activityTableNodes(ctx, db, reader, asked)
		if err != nil {
			return nil, err
		}
		body = el("div", "", nodes...)
	default:
		body = s.leadTableNodes(reader, reminders, country)
	}
	label := ""
	for _, v := range rules.CountryExecution.Page.ViewBy {
		if v[0] == table {
			label = v[1]
		}
	}
	blocks = append(blocks, walk(s.timelinessNodes(table, label, body))...)
	recent, err := s.recent(ctx, db)
	if err != nil {
		return nil, err
	}
	count, followups, err := cpoFollowUps(ctx, db, f.fy, "execution", cpoLocation)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, walk(s.lowerNodes(recent, count, followups, reader))...)
	blocks = append(blocks, walk(el("p", "cpo-info", "Stages are the platform's own: a CCEO's staff work is verified when its "+
		"Programme Lead approves it; Partner work and a Lead's own work are verified by Impact Assessment. Overdue is read against "+
		"the approved scheduled date and names the stage and who holds the next action. Values are for oversight only; verified "+
		"achievement and performance are credited in the canonical target ledger."))...)
	header := &screensv1.PageHeader{Title: "Execution & Completion",
		Description: "Track the implementation and completion of planned visits, trainings and activities across " + country + ".",
		Actions: []*screensv1.PageAction{{Key: "period_snapshots", Label: "Period Snapshots", Enabled: true,
			Href: cexBase + "/snapshots", Drawer: true}}}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: cpoPath}, nil
}

// errCEXHandOn is a view of the tab Go does not draw yet.
var errCEXHandOn = errors.New("planningmonitor: the execution view is handed on")

// ErrCountryExecutionHandOn is errCEXHandOn for the gateway.
var ErrCountryExecutionHandOn = errCEXHandOn

// cexOpenCounts is followups.open_counts for the execution stage.
func cexOpenCounts(ctx context.Context, db schooldirectory.Querier, fy string) (map[[2]string]int, error) {
	out := map[[2]string]int{}
	rows, err := db.Query(ctx, `SELECT program_lead_staff_id, COALESCE(cceo_staff_id, '') FROM planning_oversight_follow_up
		WHERE fy = $1 AND status = ANY($2) AND module = 'execution'`, fy, rules.CountryOversight.Page.FollowUpOpenStates)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the open execution follow-ups: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var lead, cceo string
		if err := rows.Scan(&lead, &cceo); err != nil {
			return nil, err
		}
		out[[2]string{"lead", lead}]++
		out[[2]string{"country", ""}]++
		if cceo != "" {
			out[[2]string{"owner", cceo}]++
		} else {
			out[[2]string{"owner", lead}]++
		}
	}
	return out, rows.Err()
}

// filterBlock is page.html's filter form as the feed reads it.
func (s *cexSnapshot) filterBlock(table string) *screensv1.PageBlock {
	f := s.filters
	page := rules.CountryExecution.Page
	opt := func(pairs [][2]string) []*screensv1.PageFilterOption {
		out := []*screensv1.PageFilterOption{}
		for _, p := range pairs {
			out = append(out, &screensv1.PageFilterOption{Value: p[0], Label: p[1]})
		}
		return out
	}
	selected := func(value string, pairs [][2]string) string {
		if slices.ContainsFunc(pairs, func(p [2]string) bool { return p[0] == value }) {
			return value
		}
		if len(pairs) > 0 {
			return pairs[0][0]
		}
		return ""
	}
	periods := [][2]string{}
	for _, k := range []string{"week", "month", "quarter", "fy"} {
		periods = append(periods, [2]string{k, page.PeriodLabels[k]})
	}
	quarters := [][2]string{{"Q1", "Q1 · Oct–Dec"}, {"Q2", "Q2 · Jan–Mar"}, {"Q3", "Q3 · Apr–Jun"}, {"Q4", "Q4 · Jul–Sep"}}
	months := [][2]string{}
	for _, m := range []int{10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9} {
		months = append(months, [2]string{strconv.Itoa(m), cpoMonths[m]})
	}
	years := [][2]string{}
	for y := 2025; y <= max(cpoOperationalFY(s.data.today)+1, 2027); y++ {
		years = append(years, [2]string{strconv.Itoa(y), cpoFYLabel(strconv.Itoa(y))})
	}
	types := map[string]bool{}
	for _, r := range s.data.records {
		types[r.activityType] = true
	}
	typeOpts := [][2]string{{"", "All"}}
	keys := []string{}
	for t := range types {
		keys = append(keys, t)
	}
	label := func(t string) string {
		if l := rules.CountryOversight.Page.TableWords.Types[t]; l != "" {
			return l
		}
		return t
	}
	sort.SliceStable(keys, func(i, j int) bool { return strings.ToLower(label(keys[i])) < strings.ToLower(label(keys[j])) })
	for _, t := range keys {
		l := rules.CountryOversight.Page.TableWords.Types[t]
		if l == "" {
			l = pyTitleWords(strings.ReplaceAll(t, "_", " "))
		}
		typeOpts = append(typeOpts, [2]string{t, l})
	}
	regionOpts := [][2]string{{"", "All"}}
	for _, r := range sortedOptions(s.data.regionName) {
		regionOpts = append(regionOpts, [2]string{r.value, r.label})
	}
	month := ""
	if f.month > 0 {
		month = strconv.Itoa(f.month)
	}
	filter := func(name, lbl, caption, value string, pairs [][2]string) *screensv1.PageFilter {
		return &screensv1.PageFilter{Name: name, Label: lbl, Caption: caption, Value: selected(value, pairs), Options: opt(pairs)}
	}
	channels := [][2]string{{"", "All"}, {"staff", "Staff"}, {"partner", "Partner"}}
	hidden := map[string]string{"view": "execution"}
	for _, kv := range [][2]string{{"program_lead", f.programLead}, {"cceo", f.cceo}, {"partner", f.partner}} {
		if kv[1] != "" {
			hidden[kv[0]] = kv[1]
		}
	}
	filters := []*screensv1.PageFilter{
		filter("period", "", "", f.period, periods),
		filter("quarter", "Quarter", "", f.quarter, quarters),
		filter("month", "Month", "", month, months),
		filter("fy", "Financial year", "", f.fy, years),
		filter("table", "", "View by", table, page.ViewBy),
		filter("channel", "", "Delivery Channel", f.channel, channels),
		filter("activity_type", "", "Activity Type", f.activType, typeOpts),
		filter("region", "", "Region", f.region, regionOpts),
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters, Hidden: hidden}}}
}

// notice is workspace.html's first note: the window and the plan's integrity.
func (s *cexSnapshot) notice(ctx context.Context, db schooldirectory.Querier, country string) (*node, error) {
	w := s.data.window
	in := s.data.integrity
	p := el("p", "cpo-notice", el("strong", "", w.label()), " · work whose approved scheduled date falls in the period. ")
	switch {
	case in.tracked:
		p.Add(fmt.Sprintf("Plan at the start of the period: %d · added since %d · moved in %d · moved out %d · cancelled %d · executable now %d. ",
			in.original, in.added, in.movedIn, in.movedOut, in.cancelled, in.live))
	case in.trackingSince != nil:
		t := in.trackingSince.In(cpoLocation)
		p.Add(fmt.Sprintf("The original plan of a period is recorded from %d %s; this period began earlier, so its figures are the current plan. ",
			t.Day(), t.Format("Jan 2006")))
	}
	var id string
	var taken time.Time
	var versions int
	err := db.QueryRow(ctx, `SELECT id, taken_at, count(*) OVER () FROM execution_period_snapshot
		WHERE country = $1 AND period_type = $2 AND period_start = $3::date ORDER BY version LIMIT 1`, country, w.period, w.start).
		Scan(&id, &taken, &versions)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
	case err != nil:
		return nil, fmt.Errorf("planningmonitor: the period's locked figures: %w", err)
	default:
		t := taken.In(cpoLocation)
		text := fmt.Sprintf("This period ended and was locked on %d %s", t.Day(), t.Format("Jan 2006"))
		if versions > 1 {
			text += fmt.Sprintf(" (revised %d×)", versions-1)
		}
		p.Add(el("span", "cxo-locked", text+"; the figures below are live. ",
			el("button", "cpo-link", "View the locked figures").Attr("type", "button", "hx-get", cexBase+"/snapshots/"+id,
				"hx-target", "#drawer-container", "hx-swap", "innerHTML")))
	}
	return p, nil
}

// cardNodes is the six figures, each a link to the table of its records.
func (s *cexSnapshot) cardNodes() *node {
	sec := el("section", "cpo-metrics cxo-metrics")
	for _, c := range s.kpis() {
		sec.Add(el("a", "cpo-metric cxo-metric", " ", el("span", "cxo-label", c.label), " ", el("span", "cxo-figure", c.value), " ",
			el("span", "cxo-metric-note", c.note), " ").Attr("href", c.href))
	}
	return sec
}

// chartBlocks is the funnel, the trend and the two charts by Programme Lead,
// each its name, "Chart data" and the open table under it.
func (s *cexSnapshot) chartBlocks() []*screensv1.PageBlock {
	tree, w := s.tree, s.data.window
	c, staff, partner := tree.country, tree.staff, tree.partner
	out := []*screensv1.PageBlock{}
	chart := func(title string, columns []string, rows [][]string) {
		cols := []*screensv1.PageColumn{}
		for _, h := range columns {
			cols = append(cols, &screensv1.PageColumn{Label: h})
		}
		t := &screensv1.PageTable{Columns: cols}
		for _, r := range rows {
			row := &screensv1.PageRow{}
			for _, v := range r {
				row.Cells = append(row.Cells, plain(v))
			}
			t.Rows = append(t.Rows, row)
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: title}}, textPanel("Chart data"),
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	}
	funnel := [][]string{}
	for _, st := range [][2]string{{"Planned", "due"}, {"Started", "started"}, {"Evidence Submitted", "executed"},
		{"PL Reviewed (Staff only)", "pl_reviewed"}, {"Verified", "verified"}, {"Fully Closed", "closed"}} {
		p := strconv.Itoa(partner.n(st[1]))
		if st[1] == "pl_reviewed" {
			p = "N/A"
		}
		funnel = append(funnel, []string{st[0], strconv.Itoa(c.n(st[1])), strconv.Itoa(staff.n(st[1])), p})
	}
	chart("Execution Funnel Staff and Partner", []string{"Stage", "Total", "Staff", "Partner"}, funnel)
	buckets := s.data.buckets
	count := len(buckets)
	current := -1
	for i, b := range buckets {
		if !s.data.today.Before(b.start) && s.data.today.Before(b.end) {
			current = i
		}
	}
	if current == -1 && !s.data.today.Before(buckets[count-1].end) {
		current = count - 1
	}
	// cumulate is charts.cumulate: running totals, none past upto (nil: all).
	cumulate := func(values []int, upto *int) []string {
		out, running := []string{}, 0
		for i, v := range values {
			running += v
			if upto != nil && i > *upto {
				out = append(out, "—")
			} else {
				out = append(out, strconv.Itoa(running))
			}
		}
		return out
	}
	plan := cumulate(c.trend("plan", count), nil)
	exec, ver, closed := cumulate(c.trend("exec", count), &current), cumulate(c.trend("ver", count), &current),
		cumulate(c.trend("closed", count), &current)
	trend := [][]string{}
	for i, b := range buckets {
		trend = append(trend, []string{b.label + " · " + b.caption, plan[i], exec[i], ver[i], closed[i]})
	}
	every := map[string]string{"week": "Daily", "month": "Weekly", "quarter": "Monthly"}[w.period]
	if every == "" {
		every = "Quarterly"
	}
	chart("Planned vs Executed vs Verified "+every+", cumulative", []string{"Period", "Planned", "Execution Completed", "Verified", "Fully Closed"}, trend)
	leads := []*cexLeadRow{}
	for _, l := range tree.leads {
		if l.tally.n("due") > 0 || !l.noLead {
			leads = append(leads, l)
		}
	}
	delivery := [][]string{}
	for _, l := range leads {
		t := l.tally
		delivery = append(delivery, []string{l.name, strconv.Itoa(t.n("due")), strconv.Itoa(t.n("verified")),
			strconv.Itoa(t.n("executed") - t.n("verified")), strconv.Itoa(t.n("started") - t.n("executed")),
			strconv.Itoa(t.n("not_started")), strconv.Itoa(t.n("upcoming"))})
	}
	chart("Delivery by Program Lead Work dated in the period", []string{"Programme Lead", "Planned", "IA verified", "In review",
		"Started, not submitted", "Past date, not started", "Not yet due"}, delivery)
	targeted := len(s.targets) > 0 && s.filters.activType == "" && s.filters.channel == ""
	visits := [][]string{}
	for _, l := range leads {
		t := l.tally
		target, left := "—", "—"
		if targeted {
			tv := s.targets[[2]string{"lead", l.key}]
			target, left = strconv.Itoa(tv), strconv.Itoa(max(0, tv-t.n("v_delivered")))
		}
		visits = append(visits, []string{l.name, target, strconv.Itoa(t.n("v_planned")), strconv.Itoa(t.n("v_delivered")),
			strconv.Itoa(t.n("v_verified")), left, strconv.Itoa(t.n("v_outreach"))})
	}
	chart("Visits Delivered Against Target by Program Lead Follow up and In-school Training", []string{"Programme Lead", "Visit target",
		"Visits planned", "Visits delivered", "Visits verified", "Still to deliver", "Donor, story, social (not counted)"}, visits)
	out = append(out, walk(el("p", "cxo-foot", el("a", "cpo-link", "Open the table of these visits").Attr("href",
		cexBase+"/records/visits?"+s.filters.query())))...)
	return out
}

// readingNodes is the on-time, backlog, age and forecast readings and the
// Quick Actions.
func (s *cexSnapshot) readingNodes(reader cpoReader) *node {
	c := s.tree.country
	q := s.filters.query()
	onTime := el("ul", "cxo-legend")
	for _, part := range [][2]any{{"On time", c.n("on_time")}, {"Late", c.n("late")}, {"Date not recorded", c.n("start_unknown")},
		{"Not started", c.n("not_started")}, {"Not yet due", c.n("upcoming")}, {"Canceled", c.n("cancelled")}} {
		if part[1].(int) != 0 || part[0] == "On time" || part[0] == "Not started" {
			onTime.Add(el("li", "", el("span", "cxo-swatch"), part[0].(string), el("strong", "", strconv.Itoa(part[1].(int)))))
		}
	}
	backlog := el("ul", "cxo-legend")
	for _, o := range rules.CountryExecution.Stages.OwnerLabels {
		backlog.Add(el("li", "", el("button", "cxo-legend-link", el("span", "cxo-swatch"), o[1], el("strong", "", strconv.Itoa(c.n("own_"+o[0])))).
			Attr("type", "button", "hx-get", cexBase+"/drawer?kind=activities&blocker="+o[0]+"&"+q, "hx-target", "#drawer-container", "hx-swap", "innerHTML")))
	}
	outlook := cexForecastOf(c, s.data.window, s.data.today)
	shortcuts := el("section", "cpo-chart cxo-reading cxo-shortcuts", el("h2", "cpo-chart-name", "Quick Actions"))
	if reader.followUp {
		shortcuts.Add(el("button", "cxo-shortcut cxo-shortcut--primary", el("span", "cxo-shortcut-label", "Send Reminder to PL")).
			Attr("type", "button", "hx-get", cexBase+"/follow-up?"+q, "hx-target", "#drawer-container", "hx-swap", "innerHTML"))
	}
	shortcuts.Add(el("button", "cxo-shortcut", el("span", "cxo-shortcut-label", "View Overdue Activities")).
		Attr("type", "button", "hx-get", cexBase+"/drawer?kind=activities&stage=overdue&"+q, "hx-target", "#drawer-container", "hx-swap", "innerHTML"),
		el("a", "cxo-shortcut", el("span", "cxo-shortcut-label", "View Partner Execution")).
			Attr("href", cpoPath+"?"+q+"&table=partner#cxo-table", "hx-get", cexBase+"/table?table=partner&"+q, "hx-target", "#cxo-table", "hx-swap", "outerHTML"))
	if reader.export {
		shortcuts.Add(el("a", "cxo-shortcut", el("span", "cxo-shortcut-label", "Download Report")).Attr("href", cexBase+"/export?"+q, "download", ""))
	}
	return el("section", "cxo-readings",
		el("figure", "cpo-chart cxo-reading", el("h2", "cpo-chart-name", "On-Time Execution"), onTime),
		el("figure", "cpo-chart cxo-reading", el("h2", "cpo-chart-name", "Backlog by Owner"), backlog),
		el("figure", "cpo-chart cxo-reading", el("h2", "cpo-chart-name", "Overdue by Age"), el("p", "cxo-foot", "Days past the approved scheduled date.")),
		el("figure", "cpo-chart cxo-reading", el("h2", "cpo-chart-name", "Completion Forecast ", el("span", "cxo-hint", "Decision support")),
			el("p", "cxo-verdict", outlook.label), el("p", "cxo-foot", outlook.text(s.data.window))),
		shortcuts)
}

// requirementCells is _requirement_cells.html.
func requirementCells(r cexRequirement) []*node {
	figure := func(v [2]any) *node {
		if v[1] == nil {
			return el("td", "", strconv.Itoa(v[0].(int)))
		}
		return el("td", "cpo-cover", el("span", "", strconv.Itoa(v[0].(int))), " ", el("span", "cpo-pct", pctOrDash(v[1].(*int))))
	}
	left := func(n int, sh *int) *node {
		mark := el("span", "cpo-zero", "0")
		if n != 0 {
			mark = el("span", "cpo-alert", strconv.Itoa(n))
		}
		return el("td", "cpo-cover", mark, " ", el("span", "cpo-pct", pctOrDash(sh)))
	}
	dash := func() *node { return el("td", "", el("span", "cpo-none", "—")) }
	out := []*node{el("td", "", strconv.Itoa(r.cells[0][0].(int)))}
	if r.needsVisits {
		for _, v := range r.cells[1:] {
			out = append(out, figure(v))
		}
		out = append(out, left(r.visitsLeft, r.visitsLeftShare))
	} else {
		for i := 0; i < 8; i++ {
			out = append(out, dash())
		}
	}
	if r.needsTrainings {
		for _, v := range r.trainingCells {
			out = append(out, figure(v))
		}
		out = append(out, left(r.trainingsLeft, r.trainingsLeft2))
	} else {
		for i := 0; i < 5; i++ {
			out = append(out, dash())
		}
	}
	return out
}

var requirementHeads = []string{"Schools", "Total Visits Expected", "Visits Planned", "Staff Target", "Staff Verified", "Partner Target",
	"Partner Verified", "Total Visits Verified", "Visits Remaining", "Total Expected", "Total Planned", "Planned by Partners",
	"Completed & Verified", "Trainings Remaining"}

func headRow(first string, rest []string, tail ...string) *node {
	tr := el("tr", "", el("th", "", first))
	for _, h := range append(slices.Clone(rest), tail...) {
		tr.Add(el("th", "", h))
	}
	return el("thead", "", tr)
}

func cexChips(label string) *screensv1.PageBlock {
	return cpoChips(label, [][2]string{{"visits", "Visits"}, {"trainings", "Trainings"}})
}

// requirementBlocks is _types.html and _people.html.
func (s *cexSnapshot) requirementBlocks() []*screensv1.PageBlock {
	plan := s.plan
	if plan == nil {
		return nil
	}
	out := []*screensv1.PageBlock{}
	byType := plan.tree.byType
	order := []string{}
	for _, t := range rules.TypeOrder {
		if _, ok := byType[t]; ok {
			order = append(order, t)
		}
	}
	extra := []string{}
	for t := range byType {
		if !slices.Contains(rules.TypeOrder, t) {
			extra = append(extra, t)
		}
	}
	sort.Strings(extra)
	order = append(order, extra...)
	if len(order) > 0 {
		body := el("tbody", "")
		for _, t := range order {
			r := cexRequirementRow(t, typeLabel(t), byType[t], need(t).visits() > 0, need(t).trainings() > 0)
			th := el("th", "cpo-namecell", el("span", "", r.label))
			if !r.needsVisits {
				th.Add(el("span", "cpo-hint", el("span", "", "outreach only")))
			}
			body.Add(el("tr", "", append([]any{th}, anyNodes(requirementCells(r))...)...))
		}
		if len(order) > 1 {
			r := cexRequirementRow("", "All school types", plan.tree.country, true, true)
			body.Add(el("tr", "", append([]any{el("th", "cpo-namecell", el("span", "", r.label))}, anyNodes(requirementCells(r))...)...))
		}
		sec := el("section", "cpo-drill cxo-types", el("header", "cpo-drill-head", el("h2", "cpo-drill-name",
			"Verified Against the Requirement by School Type")))
		if s.data.window.period == "week" {
			sec.Add(el("p", "cpo-notice cxo-pad", "A week has no phased requirement: each type's requirement is read for the year."))
		}
		sec.Add(feeddom.PreBlock(cexChips("School type figures")),
			el("div", "cpo-tscroll", el("table", "cpo-table", headRow("School Type", requirementHeads), body)))
		out = append(out, walk(sec)...)
	}
	if len(plan.tree.leads) > 0 {
		table := el("table", "cpo-table", headRow("Programme Lead / CCEO", requirementHeads))
		for _, l := range plan.tree.leads[:min(len(plan.tree.leads), cpoRowsPerPage)] {
			r := cexRequirementRow(l.key, l.name, l.tally, true, true)
			body := el("tbody", "", el("tr", "", append([]any{el("th", "cpo-namecell", el("span", "", r.label))}, anyNodes(requirementCells(r))...)...))
			for _, o := range l.owners {
				orow := cexRequirementRow(o.key, o.name, o.tally, true, true)
				th := el("th", "cpo-namecell", el("span", "", orow.label))
				if o.kind == "pl_personal" {
					th.Add(el("span", "cpo-hint", el("span", "", "own portfolio")))
				}
				body.Add(el("tr", "", append([]any{th}, anyNodes(requirementCells(orow))...)...))
			}
			table.Add(body)
		}
		out = append(out, walk(el("section", "cpo-drill cxo-types cxo-people", el("header", "cpo-drill-head", el("h2", "cpo-drill-name",
			"Verified Against the Requirement by Programme Lead and CCEO")), feeddom.PreBlock(cexChips("Programme Lead and CCEO figures")),
			el("div", "cpo-tscroll", table)))...)
	}
	return out
}

func anyNodes(ns []*node) []any {
	out := make([]any, len(ns))
	for i, n := range ns {
		out[i] = n
	}
	return out
}

// cellNodes is _cells.html.
func cellNodes(c cexCells, reader cpoReader) []any {
	td := func(parts ...any) *node { return el("td", "", parts...) }
	onTime := td(el("span", "cpo-none", "—"))
	if c.onTime != nil {
		onTime = td(itoaP(c.onTime) + "%")
	}
	overdue := td("0")
	if c.overdue != 0 {
		overdue = td(el("span", "cpo-alert", strconv.Itoa(c.overdue)))
	}
	remaining := td(el("span", "cpo-none", "—"))
	if c.remaining != nil {
		remaining = td(itoaP(c.remaining))
	}
	reminders := td("0")
	switch {
	case c.reminders != 0:
		reminders = td(el("span", "cpo-alert", strconv.Itoa(c.reminders)))
	case c.suggested && reader.followUp:
		reminders = td(el("span", "cxo-suggest", "Suggested"))
	}
	return []any{td(strconv.Itoa(c.due)), td(strconv.Itoa(c.inProgress)), td(strconv.Itoa(c.complete)), onTime, overdue,
		td(strconv.Itoa(c.carried)), td(strconv.Itoa(c.returned)), remaining, td(el("span", "cxo-outlook", c.forecast.label)), reminders}
}

// timelinessNodes is _table.html around one of its views.
func (s *cexSnapshot) timelinessNodes(table, label string, body *node) *node {
	q := s.filters.query()
	tabs := el("div", "").Attr("data-edify-tablist", "", "role", "group", "aria-label", "View execution by")
	for _, t := range [][2]string{{"lead", "Program Leads"}, {"cceo", "CCEOs"}, {"partner", "Partners"}, {"school", "Schools"}, {"activity", "Activities"}} {
		tabs.Add(el("button", "", t[1]).Attr("type", "button", "data-edify-tab", "", "aria-pressed", strconv.FormatBool(table == t[0]),
			"hx-get", cexBase+"/table?table="+t[0]+"&"+q, "hx-target", "#cxo-table", "hx-swap", "outerHTML"))
	}
	return el("section", "cpo-drill cxo-drill",
		el("header", "cpo-drill-head", el("h2", "cpo-drill-name", "Execution Timeliness", el("span", "sr-only", " by "+label))).
			Attr("data-no-titlebar", "", "data-card-header", ""),
		el("div", "cxo-drill-bar", tabs), body).Attr("id", "cxo-table")
}

// leadTableNodes is table_leads.html.
func (s *cexSnapshot) leadTableNodes(reader cpoReader, reminders map[[2]string]int, country string) *node {
	q := s.filters.query()
	heads := []string{"Planned", "In-Progress", "Completed & PL Verified", "On-Time %", "Overdue", "Carried Forward", "Returned",
		"Remaining Slots", "Forecast", "Open Reminders"}
	table := el("table", "cpo-table cxo-table", headRow("Program Lead & Team", heads, "Action"))
	leads := s.tree.leads
	for _, l := range leads[:min(len(leads), cpoRowsPerPage)] {
		c := s.cells(l.tally, s.remainingOf("lead", l.key), reminders[[2]string{"lead", l.key}], !l.noLead)
		th := el("th", "cpo-namecell", el("span", "", l.name))
		if c.atRisk {
			th.Add(el("span", "cpo-flagged", el("span", "", "At risk")))
		}
		if c.blocker != "" {
			th.Add(el("span", "cpo-hint", el("span", "", c.blocker)))
		}
		act := el("button", "cpo-view", "View").Attr("type", "button", "hx-get", cexBase+"/drawer?kind=activities&lead="+l.key+"&stage=due&"+q,
			"hx-target", "#drawer-container", "hx-swap", "innerHTML")
		if reader.followUp && !l.noLead {
			act = el("button", "cpo-ask", "Follow Up").Attr("type", "button", "hx-get", cexBase+"/follow-up?lead="+l.key+"&"+q,
				"hx-target", "#drawer-container", "hx-swap", "innerHTML")
		}
		row := el("tr", "", append(append([]any{th}, cellNodes(c, reader)...), el("td", "cpo-actcell", el("div", "cpo-acts", act)))...)
		body := el("tbody", "", row)
		if len(l.owners) > 0 {
			body.Add(el("tr", "", el("td", "")).Attr("hidden", ""))
		}
		table.Add(body)
	}
	if len(leads) == 0 {
		table.Add(el("tbody", "", el("tr", "", el("td", "cpo-empty", "No Programme Lead is on record yet."))))
	}
	c := s.cells(s.tree.country, s.remainingOf("country", ""), reminders[[2]string{"country", ""}], false)
	table.Add(el("tbody", "", el("tr", "cxo-total", append(append([]any{el("th", "cpo-namecell", el("span", "", country+" Total"))},
		cellNodes(c, reader)...), el("td", "cpo-actcell", el("span", "cpo-none", "—")))...)))
	return el("div", "cpo-tscroll", table)
}

// lowerNodes is the issues, the recent movements and the follow-ups.
func (s *cexSnapshot) lowerNodes(recent []cexEvent, count int, followups []cpoFollowUp, reader cpoReader) *node {
	issues := el("section", "cpo-chart cxo-list", el("h2", "cpo-chart-name", "Top Execution Issues"))
	if list := s.issues(); len(list) > 0 {
		body := el("tbody", "")
		for _, it := range list {
			body.Add(el("tr", "", el("th", "", el("span", "", it.label)), el("td", "", strconv.Itoa(it.count)), el("td", "", shareText(it.share))))
		}
		issues.Add(el("table", "cxo-small", el("thead", "", el("tr", "", el("th", "", "Issue"), el("th", "", "Count"), el("th", "", "%"))), body))
	} else {
		issues.Add(el("p", "cpo-muted", "Nothing past its date is open in this selection."))
	}
	moved := el("section", "cpo-chart cxo-list", el("h2", "cpo-chart-name", "Recent Activity"))
	if len(recent) > 0 {
		body := el("tbody", "")
		for _, e := range recent {
			body.Add(el("tr", "", el("td", "", el("span", "", fmt.Sprintf("%d %s", e.day.Day(), e.day.Format("Jan 2006")))),
				el("th", "", e.what), el("td", "", e.detail)))
		}
		moved.Add(el("table", "cxo-small", el("thead", "", el("tr", "", el("th", "", "Date"), el("th", "", "Activity"), el("th", "", "Details"))), body))
	} else {
		moved.Add(el("p", "cpo-muted", "No verification, return, submission or follow-up in the last two weeks."))
	}
	side := el("section", "cpo-chart cxo-list", el("header", "cxo-list-head",
		el("h2", "cpo-chart-name", "Open Follow-ups ", el("span", "cxo-count", strconv.Itoa(count))),
		el("button", "cpo-link", "View all").Attr("type", "button", "hx-get", cpoPath+"drawer?kind=followups&"+s.filters.planning().query(nil),
			"hx-target", "#drawer-container", "hx-swap", "innerHTML")))
	if len(followups) > 0 {
		body := el("tbody", "")
		for _, f := range followups {
			body.Add(el("tr", "", el("td", "", el("span", "", fmt.Sprintf("%d %s", f.date.Day(), f.date.Format("Jan")))), el("td", "", f.to),
				el("th", "", f.title), el("td", "", el("span", "cpo-tag", f.status))))
		}
		side.Add(el("table", "cxo-small", el("thead", "", el("tr", "", el("th", "", "Date"), el("th", "", "To"), el("th", "", "Issue"),
			el("th", "", "Status"))), body))
	} else {
		text := []any{"No execution follow-up is open."}
		if reader.followUp {
			text = append(text, " Use ", el("strong", "", "Follow Up"), " on a Programme Lead's row, or Send Reminder to PL.")
		}
		side.Add(el("p", "cpo-muted", text...))
	}
	return el("section", "cxo-lower", issues, moved, side)
}

// targetPeople is target_people: every Lead and their people, and everyone
// holding work, narrowed as the table is.
func (s *cexSnapshot) targetPeople() []string {
	f := s.filters
	set := map[string]bool{}
	for _, l := range s.roster.leads {
		if f.programLead != "" && l[0] != f.programLead {
			continue
		}
		set[l[0]] = true
		for _, p := range s.roster.people[l[0]] {
			set[p[0]] = true
		}
	}
	for key, o := range s.data.owners {
		if key == rules.CountryOversight.NoOwner[0] || (f.programLead != "" && o.leadKey != f.programLead) {
			continue
		}
		set[key] = true
	}
	if f.cceo != "" {
		set = map[string]bool{f.cceo: true}
	}
	out := []string{}
	for k := range set {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
