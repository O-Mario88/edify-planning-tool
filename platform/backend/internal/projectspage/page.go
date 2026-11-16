package projectspage

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// The query the page reads, in the order its filter form sends it; the
// tab and the table page are dropped from a tab's link.
var (
	ownQuery = []string{"fy", "type", "status", "project", "tab", "portfolio_page"}
	keptKeys = []string{"fy", "type", "status", "project"}
)

// zone is the application's TIME_ZONE.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic("projectspage: " + err.Error())
	}
	return z
}()

type filters struct{ fy, kind, status string }

// Build answers /projects; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	doors, known := rules.Doors[p.ActiveRole]
	if !known || !doors.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return nil, false, nil
		}
	}
	now := s.now()
	f := filters{fy: strings.TrimSpace(query.Get("fy")), kind: query.Get("type"), status: query.Get("status")}
	if !slices.Contains(schooldirectory.FYOptions(now), f.fy) {
		f.fy = schooldirectory.OperationalFY(now)
	}
	if _, ok := label(rules.Categories, f.kind); !ok {
		f.kind = ""
	}
	if _, ok := rules.StatusFilterLabels[f.status]; !ok {
		f.status = ""
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	d, err := read(ctx, s.db, scope, f)
	if err != nil {
		return nil, true, err
	}
	blocks := []*screensv1.PageBlock{}
	if doors.Strip != nil {
		blocks = append(blocks, stripBlock(*doors.Strip))
	}
	blocks = append(blocks, filterBlock(f, schooldirectory.FYOptions(now)))
	if len(d.projects) == 0 {
		blocks = append(blocks, empty("When a project is assigned to you, its cohort, planning queue, budget and impact "+
			"appear here — all driven by the same planning engine."))
		return response(doors, blocks), true, nil
	}
	rest, err := s.body(ctx, d, doors, query, now)
	if errors.Is(err, errUnpriced) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return response(doors, append(blocks, rest...)), true, nil
}

func response(doors Doors, blocks []*screensv1.PageBlock) *screensv1.GetPageResponse {
	h := &screensv1.PageHeader{
		Eyebrow: "Special Projects",
		Title:   "Projects",
		Description: "Track the Projects assigned to you, enrolled schools, intervention focus, delivery progress, " +
			"budget and upcoming follow-ups.",
	}
	if doors.Create {
		h.Actions = []*screensv1.PageAction{{Key: "new_project", Label: "New Project", Primary: true, Enabled: true,
			Href: "/projects/create", Drawer: true}}
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, WebPath: PagePath}
}

func stripBlock(s Strip) *screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{}
	for _, t := range s.Tabs {
		tabs = append(tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{
		Tabs: tabs, Label: s.Label, Scrolls: s.Scrolls}}}
}

func filterBlock(f filters, years []string) *screensv1.PageBlock {
	fy := &screensv1.PageFilter{Name: "fy", Label: "Financial year", Value: f.fy}
	for _, y := range years {
		fy.Options = append(fy.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	kind := &screensv1.PageFilter{Name: "type", Label: "Project type", Value: f.kind,
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All Types"}}}
	for _, c := range rules.Categories {
		kind.Options = append(kind.Options, &screensv1.PageFilterOption{Value: c[0], Label: c[1]})
	}
	status := &screensv1.PageFilter{Name: "status", Label: "Status", Value: f.status,
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All Statuses"}}}
	for _, c := range rules.StatusFilters {
		status.Options = append(status.Options, &screensv1.PageFilterOption{Value: c[0], Label: c[1]})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{fy, kind, status}}}}
}

func empty(text string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: text}}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func row(label, value string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{
		Rows: []*screensv1.PageDataRow{{Label: label, Value: value}}}}}
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: title, Subtitle: subtitle, Items: feeddom.Paired(items)}}}
}

func link(t, href string) *screensv1.PageLink { return &screensv1.PageLink{Text: t, Href: href} }

func plural(n int, word string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, word)
	}
	return fmt.Sprintf("%d %ss", n, word)
}

// body is everything under the filters for a reader with projects.
func (s *Service) body(ctx context.Context, d *dashboard, doors Doors, query url.Values, now time.Time) ([]*screensv1.PageBlock, error) {
	bars, err := d.impactBars()
	if err != nil {
		return nil, err
	}
	blocks := []*screensv1.PageBlock{figures(d)}
	portfolio := d.portfolio(now)
	if d.status != "" {
		allowed := rules.StatusFilterLabels[d.status]
		kept := portfolio[:0:0]
		for _, r := range portfolio {
			if in(allowed, r.status) {
				kept = append(kept, r)
			}
		}
		portfolio = kept
	}
	if len(portfolio) > 0 {
		blocks = append(blocks, projectTabs(portfolio, query, doors.Export)...)
	} else {
		blocks = append(blocks, empty("No project matches these filters."))
	}
	blocks = append(blocks, budgetBlocks(d)...)
	blocks = append(blocks, impactBlock(bars))
	sel := d.projects[0]
	for _, p := range d.projects {
		if p.id == query.Get("project") {
			sel = p
			break
		}
	}
	selected, err := s.selectedBlocks(ctx, d, sel)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, selected...)
	blocks = append(blocks, d.followUps(doors)...)
	return append(blocks, d.partnerBlocks()...), nil
}

// thousands is Python's "{:,}".
func thousands(n int64) string {
	s := strconv.FormatInt(n, 10)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if neg {
		return "-" + s
	}
	return s
}

// ugx is _fmt_ugx: "UGX 2.48B", "UGX 1.2M", "UGX 50K", "UGX 900".
func ugx(a int64) string {
	switch {
	case a >= 1_000_000_000:
		return "UGX " + strconv.FormatFloat(float64(a)/1_000_000_000, 'f', 2, 64) + "B"
	case a >= 1_000_000:
		return "UGX " + strconv.FormatFloat(float64(a)/1_000_000, 'f', 1, 64) + "M"
	case a >= 1_000:
		return "UGX " + strconv.FormatFloat(float64(a)/1_000, 'f', 0, 64) + "K"
	}
	return "UGX " + thousands(a)
}

// figures is the KPI strip.
func figures(d *dashboard) *screensv1.PageBlock {
	active, schools, partners, deliveredSchools := map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}
	var teachers, leaders, inPlan, evidence, ia, closed int64
	for _, a := range d.acts {
		if a.inPlan() {
			active[a.projectID] = true
			inPlan++
		}
		if a.delivered() {
			if a.school != nil {
				deliveredSchools[*a.school] = true
			}
			if a.training() {
				if a.teachers != nil {
					teachers += int64(*a.teachers)
				}
				if a.leaders != nil {
					leaders += int64(*a.leaders)
				}
			}
		}
		if a.evidenceDue() {
			evidence++
		}
		if a.iaDue() {
			ia++
		}
		if a.status == "closed" {
			closed++
		}
	}
	for _, a := range d.assignments {
		schools[a.schoolID] = true
	}
	for _, l := range d.partnerLinks {
		partners[l[1]] = true
	}
	var learners int64
	for id := range deliveredSchools {
		if s, ok := d.live[id]; ok && s.enrollment != nil {
			learners += int64(*s.enrollment)
		}
	}
	values := []struct{ value, note, href string }{
		{strconv.Itoa(len(d.projects)), "In your scope", ""},
		{strconv.Itoa(len(active)), "With in-flight work", ""},
		{strconv.Itoa(len(schools)), "Assigned cohorts", "/planning"},
		{thousands(teachers), "Verified trainings", ""},
		{thousands(leaders), "Verified trainings", ""},
		{thousands(learners), "At schools visited", ""},
		{strconv.Itoa(len(partners)), "Delivery partners", ""},
		{ugx(d.budget()), "Auto from schedules", "/fund-requests/weekly"},
		{thousands(inPlan), "In the pipeline", "/my-plan"},
		{thousands(evidence), "Awaiting proof", ""},
		{thousands(ia), "Awaiting verification", ""},
		{thousands(closed), "Fully cleared", ""},
	}
	strip := &screensv1.PageStrip{Title: "Project portfolio context"}
	for i, v := range values {
		strip.Metrics = append(strip.Metrics, &screensv1.PageMetric{Label: rules.MetricLabels[i], Value: v.value, Note: v.note, Href: v.href})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

// portfolioRow is one project as its card draws it.
type portfolioRow struct {
	id, name, code, kind, region, partner, budget, status, tone, next string
	schools, completion                                               int
	interventions                                                     []string
}

func (d *dashboard) portfolio(now time.Time) []portfolioRow {
	schools := map[string]int{}
	regions := map[string]map[string]bool{}
	for _, a := range d.assignments {
		schools[a.projectID]++
		if a.region != nil {
			if regions[a.projectID] == nil {
				regions[a.projectID] = map[string]bool{}
			}
			regions[a.projectID][*a.region] = true
		}
	}
	partners := map[string][]string{}
	for _, l := range d.partnerLinks {
		partners[l[0]] = append(partners[l[0]], d.partnerNames[l[1]])
	}
	budget, actCounts, upcoming := d.budgetBy(), d.countsBy(), d.upcoming(now)
	out := []portfolioRow{}
	for _, p := range d.projects {
		c := actCounts[p.id]
		completion := percent(int64(c.closed), int64(c.total))
		status, tone := statusBand(completion, c.total)
		kind, ok := label(rules.Categories, p.category)
		if !ok {
			kind = p.category
			if kind == "" {
				kind = "—"
			}
		}
		r := portfolioRow{id: p.id, name: p.name, code: p.code, kind: kind, region: "—", partner: "—",
			budget: ugx(budget[p.id]), status: status, tone: tone, next: "—", schools: schools[p.id], completion: completion}
		if names := sortedKeys(regions[p.id]); len(names) > 0 {
			r.region = names[0]
		}
		if prs := partners[p.id]; len(prs) > 0 {
			r.partner = prs[0]
		}
		if at, ok := upcoming[p.id]; ok {
			r.next = djangoDateTime(at.In(zone))
		}
		for _, i := range p.targetList() {
			r.interventions = append(r.interventions, interventionLabel(i))
		}
		out = append(out, r)
	}
	return out
}

func sortedKeys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// badgeTone is the feed's tone for the web's status badge.
func badgeTone(tone string) string {
	switch tone {
	case "danger":
		return "alert"
	case "warning":
		return "caution"
	case "success":
		return "good"
	case "info":
		return "info"
	}
	return "plain"
}

// keptQuery is the tab links' query: the page's own filters as asked, the
// tab and the table page left out.
func keptQuery(query url.Values) string {
	parts := []string{}
	for _, k := range keptKeys {
		for _, v := range query[k] {
			parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(v))
		}
	}
	if len(parts) == 0 {
		return ""
	}
	return strings.Join(parts, "&") + "&"
}

// projectTabs is one tab per project and the open project's card.
func projectTabs(portfolio []portfolioRow, query url.Values, export bool) []*screensv1.PageBlock {
	open := portfolio[0]
	for _, r := range portfolio {
		if r.id == strings.TrimSpace(query.Get("tab")) {
			open = r
		}
	}
	kept := keptQuery(query)
	tabs := &screensv1.PageLinkTabs{Scrolls: true}
	for _, r := range portfolio {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: r.name + " " + strconv.Itoa(r.schools),
			Href: "?" + kept + "tab=" + r.id, Active: r.id == open.id})
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		{Kind: &screensv1.PageBlock_Record{Record: open.record(export)}},
	}
}

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

func (r portfolioRow) record(export bool) *screensv1.PageRecord {
	menu := func(label, href string) *screensv1.PageAction {
		return &screensv1.PageAction{Key: "menu", Label: label, Enabled: true, Href: href}
	}
	rec := &screensv1.PageRecord{
		Title: r.name,
		Href:  "/projects/" + r.id,
		Actions: []*screensv1.PageAction{
			menu("Plan", "/projects/planning?project="+r.id),
			menu("Open Project", "/projects/"+r.id),
			menu("Assign", "/projects/planning?project="+r.id+"&partner_type=unassigned"),
			menu("View Impact", "/projects/analytics?project="+r.id),
		},
		Details: []*screensv1.PageBlock{panel("", "", text("Loading the schools in this project..."))},
	}
	if export {
		// {% url 'frontend:special_project_export' row.id %}
		rec.Actions = append(rec.Actions, menu("Export to Excel", "/team-planning-oversight/projects/"+r.id+"/export"))
	}
	if r.status != "" {
		rec.Badges = []*screensv1.PageBadge{{Text: r.status, Tone: badgeTone(r.tone)}}
	}
	fact := func(label, value string) *screensv1.PageFact { return &screensv1.PageFact{Label: label, Value: value} }
	rec.Facts = []*screensv1.PageFact{
		fact("Code", orDash(r.code)),
		fact("Type", orDash(r.kind)),
		fact("Scope", orDash(r.region)),
		fact("Schools", strconv.Itoa(r.schools)),
		fact("Delivery", orDash(r.partner)),
		fact("Progress", strconv.Itoa(r.completion)+"%"),
		fact("Budget", orDash(r.budget)),
		fact("Next Follow-Up", r.next),
	}
	if len(r.interventions) > 0 {
		rec.Facts = append(rec.Facts, fact("Interventions", strings.Join(r.interventions, ", ")))
	}
	return rec
}

// budgetBlocks is the Budget & Execution card.
func budgetBlocks(d *dashboard) []*screensv1.PageBlock {
	bucket := func(types []string) int64 {
		var n int64
		for _, l := range d.lines {
			if in(types, l.activityType) {
				n += l.amount
			}
		}
		return n
	}
	var disbursed int64
	for _, l := range d.lines {
		if in(rules.DisbursedPaymentStatuses, l.payment) {
			disbursed += l.amount
		}
	}
	total := d.budget()
	metric := func(label, value string) *screensv1.PageMetric {
		return &screensv1.PageMetric{Label: label, Value: value}
	}
	strip := &screensv1.PageStrip{Title: "Performance overview", Metrics: []*screensv1.PageMetric{
		metric("Total budget", ugx(total)),
		metric("Visits", ugx(bucket(rules.VisitTypes))),
		metric("Trainings", ugx(bucket(rules.TrainingTypes))),
		metric("SSA Collection", ugx(bucket(rules.SSATypes))),
		metric("Partner Activities", ugx(bucket([]string{"partner_activity", "project_activity"}))),
	}}
	return []*screensv1.PageBlock{
		panel("Budget & Execution", "Auto from scheduled activities · all financial stages shown separately",
			links(link("Fund Requests →", "/fund-requests/weekly"))),
		{Kind: &screensv1.PageBlock_Strip{Strip: strip}},
		panel("", "", row("Budget Utilization", strconv.Itoa(percent(disbursed, total))+"%"),
			text("Disbursed as a share of planned.")),
	}
}

// impactBlock is Delivery by Intervention: the bars, or the empty table.
func impactBlock(bars []bar) *screensv1.PageBlock {
	const title, subtitle = "Delivery by Intervention", "Verified delivered activities, split by delivery channel"
	if len(bars) == 0 {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: title, Subtitle: subtitle,
			EmptyMessage: "Intervention impact appears here once activities are delivered and verified."}}}
	}
	items := []*screensv1.PagePanelItem{}
	for _, b := range bars {
		items = append(items, text(b.label), text(fmt.Sprintf("Staff %d · Partner %d", b.staff, b.partner)))
	}
	items = append(items, links(link("View full Impact Analytics →", "/projects/analytics")))
	return panel(title, subtitle, items...)
}

// selectedBlocks is Attention Needed and the Selected Project card.
func (s *Service) selectedBlocks(ctx context.Context, d *dashboard, sel project) ([]*screensv1.PageBlock, error) {
	c := d.countsBy()[sel.id]
	completion := percent(int64(c.closed), int64(c.total))
	status, _ := statusBand(completion, c.total)
	var partnerPending, evidence, returns int
	for _, a := range d.acts {
		if a.projectID != sel.id {
			continue
		}
		if a.status == "assigned_to_partner" {
			partnerPending++
		}
		if a.evidenceDue() {
			evidence++
		}
		if a.status == "returned_by_ia" || a.ia == "flagged" {
			returns++
		}
	}
	noSSA := map[string]bool{}
	regions := map[string]bool{}
	var start *time.Time
	for _, a := range d.assignments {
		if a.projectID != sel.id {
			continue
		}
		if s, ok := d.live[a.schoolID]; ok && s.ssa == "not_done" {
			noSSA[a.schoolID] = true
		}
		if a.region != nil {
			regions[*a.region] = true
		}
		if a.start != nil && (start == nil || a.start.Before(*start)) {
			start = a.start
		}
	}
	coordinator, err := coordinatorName(ctx, s.db, sel.managerStaff)
	if err != nil {
		return nil, err
	}
	kind, ok := label(rules.Categories, sel.category)
	if !ok {
		kind = orDash(sel.category)
	}
	focus := "—"
	if sel.intervention != nil && *sel.intervention != "" {
		focus = interventionLabel(*sel.intervention)
	}
	startText := "—"
	if start != nil {
		startText = start.Format("02 Jan 2006")
	}
	step := "All project schools have a current SSA — schedule support activities."
	if n := len(noSSA); n > 0 {
		step = fmt.Sprintf("Schedule SSA visits for %d school%s without a current assessment.", n, map[bool]string{true: "", false: "s"}[n == 1])
	}
	plan := "/projects/planning?" + url.Values{"project": {sel.id}}.Encode()
	attention := panel("Attention Needed", "Risk signals on "+sel.name, links(
		link(fmt.Sprintf("Schools without SSA %d", len(noSSA)), ""),
		link(fmt.Sprintf("Partner pending schedule %d", partnerPending), ""),
		link(fmt.Sprintf("Evidence overdue %d", evidence), ""),
		link(fmt.Sprintf("IA returns %d", returns), ""),
	))
	card := panel("", "",
		text("Selected Project"),
		links(link(sel.name, "/projects/"+sel.id)),
		text(status), text(kind),
		text("Coordinator"), text(coordinator),
		text("Focus"), text(focus),
		text("Regions"), text(orDash(strings.Join(sortedKeys(regions), ", "))),
		text("Start"), text(startText),
		text("Recommended Next Step"), text(step),
		links(link("Go to Planning →", plan)),
	)
	return []*screensv1.PageBlock{attention, card}, nil
}

type queued struct{ school, district, state, action, href string }

// queue is the Project Planning Queue, schools needing action first.
func (d *dashboard) queue() []queued {
	names := map[string]string{}
	for _, p := range d.projects {
		names[p.id] = p.name
	}
	out := []queued{}
	for _, a := range d.assignments {
		q := queued{school: a.name, district: "—"}
		if a.district != nil {
			q.district = *a.district
		}
		switch {
		case a.ssa == "not_done":
			q.state, q.action = "SSA Required", "Schedule SSA"
		case a.readiness == "in_my_plan":
			q.state, q.action = "In My Plan", "View in My Plan"
		case a.readiness == "ready_for_partner_assignment":
			q.state, q.action = "Partner Pending Schedule", "Assign"
		case a.readiness == "scheduled":
			q.state, q.action = "Scheduled", "View School"
		case a.readiness == "requires_cluster":
			q.state, q.action = "Cluster Required", "Add to Cluster"
		default:
			q.state, q.action = "Ready for Support", "Schedule"
		}
		find := url.Values{"project": {a.projectID}, "q": {a.name}}.Encode()
		switch q.state {
		case "In My Plan":
			q.href = "/projects/my-plan?" + find
		case "Cluster Required":
			q.href = "/clusters"
		default:
			q.href = "/projects/planning?" + find
		}
		out = append(out, q)
	}
	sort.SliceStable(out, func(i, j int) bool {
		done := func(q queued) bool { return q.state == "In My Plan" || q.state == "Scheduled" }
		return !done(out[i]) && done(out[j])
	})
	return out
}

// followUps is Upcoming Follow-Ups: its heading card and the first six.
func (d *dashboard) followUps(doors Doors) []*screensv1.PageBlock {
	q := d.queue()
	head := panel("Upcoming Follow-Ups", plural(len(q), "school")+" needing action", links(link("View all →", "/planning")))
	if len(q) == 0 {
		head.GetPanel().Items = append(head.GetPanel().Items, text("All caught up — no follow-ups pending."))
		return []*screensv1.PageBlock{head}
	}
	if len(q) > 6 {
		q = q[:6]
	}
	items := []*screensv1.PagePanelItem{}
	for _, r := range q {
		items = append(items, text(r.school), text(r.district+" · "+r.state))
		path, _, _ := strings.Cut(r.href, "?")
		if doors.Opens[path] {
			items = append(items, links(link(r.action+" →", r.href)))
		}
	}
	return []*screensv1.PageBlock{head, panel("", "", items...)}
}

// partnerBlocks is Partner Delivery, one row per partner in the links' order.
func (d *dashboard) partnerBlocks() []*screensv1.PageBlock {
	seen := map[string]bool{}
	items := []*screensv1.PagePanelItem{}
	count := 0
	for _, l := range d.partnerLinks {
		partner := l[1]
		if seen[partner] {
			continue
		}
		seen[partner] = true
		count++
		var total, closed, scheduled, accepted int
		schools := map[string]bool{}
		for _, a := range d.acts {
			if a.partner != partner {
				continue
			}
			total++
			if a.status == "closed" {
				closed++
			}
			if a.inPlan() {
				scheduled++
			}
			if a.evidence == "accepted" {
				accepted++
			}
			key := "\x00"
			if a.school != nil {
				key = *a.school
			}
			schools[key] = true
		}
		evidence := "—"
		if total > 0 {
			evidence = fmt.Sprintf("%d/%d", accepted, total)
		}
		items = append(items, row(d.partnerNames[partner], strconv.Itoa(percent(int64(closed), int64(total)))+"%"),
			text(fmt.Sprintf("%s · %d scheduled · evidence %s", plural(len(schools), "school"), scheduled, evidence)))
	}
	if count == 0 {
		return nil
	}
	return []*screensv1.PageBlock{
		panel("Partner Delivery", plural(count, "partner"), links(link("All partners →", "/partners"))),
		panel("", "", items...),
	}
}

// ── Django's default date-time (DATETIME_FORMAT "N j, Y, P", en-us) ─────────

var apMonths = [...]string{"Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."}

// djangoDateTime is "Dec. 1, 2026, 10 a.m." / "Dec. 1, 2026, 1:30 p.m." /
// "midnight" / "noon", as the template's default datetime rendering writes it.
func djangoDateTime(t time.Time) string {
	return fmt.Sprintf("%s %d, %d, %s", apMonths[t.Month()-1], t.Day(), t.Year(), djangoP(t))
}

func djangoP(t time.Time) string {
	h, m := t.Hour(), t.Minute()
	switch {
	case h == 0 && m == 0:
		return "midnight"
	case h == 12 && m == 0:
		return "noon"
	}
	hour := h % 12
	if hour == 0 {
		hour = 12
	}
	suffix := "a.m."
	if h >= 12 {
		suffix = "p.m."
	}
	if m == 0 {
		return fmt.Sprintf("%d %s", hour, suffix)
	}
	return fmt.Sprintf("%d:%02d %s", hour, m, suffix)
}
