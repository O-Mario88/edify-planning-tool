package projectplanning

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	_ "time/tzdata" // the page's day is Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundworkspace"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PagePath is the page's path.
const PagePath = "/projects/planning"

var ownQuery = []string{"fy", "quarter", "region", "district", "staff", "project", "project_type", "partner_type",
	"activity_type", "tab", "q", "selected", "page", "per_page"}

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("projectplanning: " + err.Error())
	}
	return z
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService returns the page's builder.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

type filters struct {
	fy, quarter, tab, project, region, district, staff, projectType, partnerType, activityType, search string
	selected                                                                                           string
	perPage                                                                                            int
}

func dayOf(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

func quarterOf(d time.Time) string {
	switch m := d.Month(); {
	case m >= time.October:
		return "Q1"
	case m <= time.March:
		return "Q2"
	case m <= time.June:
		return "Q3"
	}
	return "Q4"
}

func choose(value string, allowed []string, fallback string) string {
	value = strings.TrimSpace(value)
	if slices.Contains(allowed, value) {
		return value
	}
	return fallback
}

// Build answers /projects/planning.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return nil, false, nil
		}
	}
	if len(role.Strip) > 0 && string(role.Strip) != "null" {
		return nil, false, nil
	}
	now := s.now()
	today := dayOf(now.In(zone))
	sc, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, fmt.Errorf("projectplanning: resolving the reader's scope: %w", err)
	}
	list, err := projects(ctx, s.db, p, sc)
	if err != nil {
		return nil, true, err
	}
	h := &screensv1.PageHeader{Eyebrow: "Special Projects", Title: "Special Projects Planning",
		Description: "Plan SSA scores, school support, partner assignments, and delivery for schools assigned from the School Directory."}
	if len(list) == 0 {
		return &screensv1.GetPageResponse{Header: h, WebPath: PagePath, Blocks: []*screensv1.PageBlock{
			{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "No special projects are assigned to your role",
				Subtitle: "When a project is assigned to you—or to schools in your portfolio—it will appear here."}}},
		}}, true, nil
	}
	pg, ok, err := s.read(ctx, p, role, list, query, now, today)
	if err != nil {
		return nil, true, err
	}
	if !ok {
		return nil, false, nil
	}
	blocks := pg.blocks()
	if line, err := planningpage.WorkloadLine(ctx, s.db, p, schooldirectory.OperationalFY(now)); err != nil {
		return nil, true, err
	} else if line != nil {
		// partials/planning/_workload_line.html, under the strip.
		at := 2
		if pg.f.project != "" {
			at = 3
		}
		blocks = slices.Insert(blocks, at, line)
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, WebPath: PagePath}, true, nil
}

// row is one school a project holds, as get_planning writes it.
type row struct {
	a                                         assignment
	bucket, baseline, readiness, action, next string
	kind                                      string // action_kind
	partner, activityType                     string
	planned                                   *time.Time
	average                                   *float64
}

type page struct {
	f             filters
	role          roleRules
	fyOptions     []string
	projects      []project
	assignments   []assignment
	rows          []row // after every filter, the tab's included
	counts        map[string]int
	pageRows      []row
	number, pages int
	selected      *row
	activities    []activity
	districts     [][2]string
	staff         [][2]string
	projectTypes  []string
	activityTypes []string
	budget        int64
	today         time.Time
}

func (s *Service) read(ctx context.Context, p auth.Principal, role roleRules, list []project, query url.Values, now, today time.Time) (*page, bool, error) {
	pg := &page{role: role, projects: list, today: today, fyOptions: schooldirectory.FYOptions(now)}
	ids := make([]string, len(list))
	for i, pr := range list {
		ids[i] = pr.id
	}
	f := filters{
		project: strings.TrimSpace(query.Get("project")), region: strings.TrimSpace(query.Get("region")),
		district: strings.TrimSpace(query.Get("district")), staff: strings.TrimSpace(query.Get("staff")),
		projectType: strings.TrimSpace(query.Get("project_type")), activityType: strings.TrimSpace(query.Get("activity_type")),
		search: strings.TrimSpace(query.Get("q")), selected: query.Get("selected"),
	}
	f.fy = choose(query.Get("fy"), pg.fyOptions, schooldirectory.OperationalFY(now))
	f.quarter = choose(query.Get("quarter"), []string{"Q1", "Q2", "Q3", "Q4"}, quarterOf(today))
	f.tab = choose(query.Get("tab"), tabs, "all")
	f.partnerType = choose(query.Get("partner_type"), []string{"staff", "partner", "unassigned"}, "")
	if !slices.Contains(ids, f.project) {
		f.project = ""
	}
	f.perPage = 50
	if raw := query.Get("per_page"); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && isDigits(raw) && slices.Contains(sizes, n) {
			f.perPage = n
		}
	}
	pg.f = f
	var err error
	if pg.assignments, err = s.assignments(ctx, ids, f); err != nil {
		return nil, false, err
	}
	if pg.activities, err = s.activities(ctx, ids, f.fy, f.quarter); err != nil {
		return nil, false, err
	}
	opens, err := s.handovers(ctx, ids)
	if err != nil {
		return nil, false, err
	}
	partnerIDs := []string{}
	for _, a := range pg.activities {
		if a.partnerID != "" {
			partnerIDs = append(partnerIDs, a.partnerID)
		}
	}
	partnerNames, _, err := s.names(ctx, `SELECT id, name FROM partner WHERE deleted_at IS NULL AND id = ANY($1)`, partnerIDs)
	if err != nil {
		return nil, false, err
	}
	byPair := map[[2]string][]activity{}
	for _, a := range pg.activities {
		k := [2]string{a.projectID, a.schoolID}
		byPair[k] = append(byPair[k], a)
	}
	all := []row{}
	for _, a := range pg.assignments {
		pair := byPair[[2]string{a.projectID, a.schoolPK}]
		if f.activityType != "" && !slices.ContainsFunc(pair, func(x activity) bool { return x.kind == f.activityType }) {
			continue
		}
		ho, hasHandover := opens[[2]string{a.projectID, a.schoolPK}]
		switch f.partnerType {
		case "partner":
			if !hasHandover && !slices.ContainsFunc(pair, func(x activity) bool { return x.delivery == "partner" }) {
				continue
			}
		case "staff":
			if !slices.ContainsFunc(pair, func(x activity) bool { return x.delivery == "staff" }) {
				continue
			}
		case "unassigned":
			if len(pair) > 0 || hasHandover {
				continue
			}
		}
		var hop *handover
		if hasHandover {
			hop = &ho
		}
		all = append(all, rowOf(a, pair, hop, partnerNames))
	}
	pg.counts = map[string]int{"all": len(all)}
	for _, r := range all {
		pg.counts[r.bucket]++
	}
	for _, r := range all {
		if f.tab == "all" || r.bucket == f.tab {
			pg.rows = append(pg.rows, r)
		}
	}
	pg.pages = max(1, (len(pg.rows)+f.perPage-1)/f.perPage)
	if pg.pages > 4 {
		return nil, false, nil
	}
	pg.number = 1
	if raw := query.Get("page"); raw != "" {
		if n, err := strconv.Atoi(strings.TrimSpace(raw)); err == nil {
			pg.number = min(max(n, 1), pg.pages)
			if n < 1 {
				pg.number = pg.pages
			}
		}
	}
	start := (pg.number - 1) * f.perPage
	pg.pageRows = pg.rows[min(start, len(pg.rows)):min(start+f.perPage, len(pg.rows))]
	for i := range pg.pageRows {
		if pg.pageRows[i].a.id == f.selected {
			pg.selected = &pg.pageRows[i]
		}
	}
	if pg.selected == nil && len(pg.pageRows) > 0 {
		pg.selected = &pg.pageRows[0]
	}
	if pg.selected != nil {
		pg.f.selected = pg.selected.a.id
	}
	if err := s.options(ctx, pg); err != nil {
		return nil, false, err
	}
	actIDs := make([]string, len(pg.activities))
	for i, a := range pg.activities {
		actIDs[i] = a.id
	}
	if pg.budget, err = s.budget(ctx, actIDs); err != nil {
		return nil, false, err
	}
	return pg, true, nil
}

func isDigits(s string) bool {
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return s != ""
}

// options is the filters' choices: the queue's districts, the projects'
// leads, the queue's project types and the quarter's activity types.
func (s *Service) options(ctx context.Context, pg *page) error {
	districtIDs := []string{}
	types := map[string]bool{}
	for _, a := range pg.assignments {
		districtIDs = append(districtIDs, a.districtID)
		t := a.projectType
		if t == "" {
			t = a.projectCategory
		}
		types[t] = true
	}
	sql := `SELECT id, name FROM district WHERE id = ANY($1)`
	args := []any{districtIDs}
	if pg.f.region != "" {
		sql += ` AND region_id = $2`
		args = append(args, pg.f.region)
	}
	names, order, err := s.names(ctx, sql+` ORDER BY name`, args...)
	if err != nil {
		return err
	}
	for _, id := range order {
		pg.districts = append(pg.districts, [2]string{id, names[id]})
	}
	managers := []string{}
	for _, pr := range pg.projects {
		if pr.manager != "" {
			managers = append(managers, pr.manager)
		}
	}
	names, order, err = s.names(ctx, `SELECT sp.id, COALESCE(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND sp.id = ANY($1) ORDER BY u.name`, managers)
	if err != nil {
		return err
	}
	for _, id := range order {
		pg.staff = append(pg.staff, [2]string{id, names[id]})
	}
	for t := range types {
		pg.projectTypes = append(pg.projectTypes, t)
	}
	sort.Strings(pg.projectTypes)
	kinds := map[string]bool{}
	for _, a := range pg.activities {
		kinds[a.kind] = true
	}
	for k := range kinds {
		pg.activityTypes = append(pg.activityTypes, k)
	}
	sort.Strings(pg.activityTypes)
	return nil
}

// activityState is _activity_state's words: Activity.get_status_display,
// which names staff work's verification as the Programme Lead's.
func activityState(a *activity) string {
	if a == nil {
		return "Not planned"
	}
	if l, ok := rules.StaffVerificationStatuses[a.status]; ok && a.delivery != "partner" {
		return l
	}
	return label(rules.Statuses, a.status)
}

// rowOf is _row_state over a school's SSA, this quarter's work there and
// any open handover.
func rowOf(a assignment, pair []activity, ho *handover, partnerNames map[string]string) row {
	r := row{a: a, kind: "my_plan"}
	var latest *activity
	if len(pair) > 0 {
		latest = &pair[0]
	}
	var current *activity
	ssaLine := ""
	if a.ssaDate != nil {
		ssaLine = "SSA score available · " + a.ssaDate.UTC().Format("02 Jan 2006")
	}
	switch {
	case ho != nil && (latest == nil || !in(rules.LivePlanStatuses, latest.status)):
		r.bucket, r.baseline, r.readiness = "partner", ssaLine, "Awaiting partner schedule"
		if a.ssaDate == nil {
			r.baseline = "SSA Required"
		}
		r.action, r.next = "Monitor partner scheduling", "Confirm the partner's delivery date and monitor the evidence workflow."
	case a.ssaDate == nil:
		r.bucket, r.kind = "baseline", "schedule"
		for i := range pair {
			if pair[i].ssaExpected {
				current = &pair[i]
				break
			}
		}
		if current != nil {
			r.baseline, r.readiness, r.action = "SSA scheduled", activityState(current), "Monitor SSA visit"
			r.next = "The SSA visit gives the project its baseline. Project support can be scheduled alongside it."
		} else {
			r.baseline, r.readiness, r.action = "SSA Required", "SSA Required", "Schedule SSA visit"
			r.next = "An SSA visit gives the project its baseline. Project support can be scheduled without it."
		}
	case latest == nil:
		r.bucket, r.baseline, r.readiness, r.kind = "ready", ssaLine, "Ready for support", "schedule"
		r.action, r.next = "Schedule recommended support", "Use the weakest SSA intervention to plan a targeted visit or training."
	default:
		current = latest
		r.baseline, r.readiness = ssaLine, activityState(latest)
		if latest.delivery == "partner" && (latest.status == "assigned_to_partner" || latest.status == "planned") {
			r.bucket, r.action, r.next = "partner", "Monitor partner scheduling", "Confirm the partner's delivery date and monitor the evidence workflow."
		} else {
			r.bucket, r.action = "scheduled", "Open activity in My Plan"
			r.next = "Continue this activity through completion, evidence, review, and finance clearance."
		}
	}
	if a.ssaAverage != nil {
		v := math.RoundToEven(*a.ssaAverage*100) / 100
		r.average = &v
	}
	r.partner, r.activityType = "—", "—"
	switch {
	case current != nil:
		if n, ok := partnerNames[current.partnerID]; ok {
			r.partner = n
		}
		r.activityType = label(rules.ActivityTypes, current.kind)
		r.planned = current.planned
	case ho != nil:
		r.partner = ho.partner
		r.planned = ho.scheduled
	}
	return r
}

// pyFloat is Python's str of a float.
func pyFloat(f float64) string {
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.Contains(s, ".") {
		s += ".0"
	}
	return s
}

// floatformat1 is Django's floatformat:1 (a half rounds away from zero).
func floatformat1(f float64) string {
	return strconv.FormatFloat(math.Round(f*10)/10, 'f', 1, 64)
}

func projectTypeOf(a assignment) string {
	if a.projectType != "" {
		return a.projectType
	}
	if l, ok := rules.ProjectTypes[a.projectCategory]; ok {
		return l
	}
	return pyTitle(strings.ReplaceAll(a.projectCategory, "_", " "))
}

// pyTitle is Python's str.title() over plain words.
func pyTitle(s string) string {
	out := []rune{}
	start := true
	for _, c := range s {
		if start {
			out = append(out, []rune(strings.ToUpper(string(c)))...)
		} else {
			out = append(out, []rune(strings.ToLower(string(c)))...)
		}
		start = !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z')
	}
	return string(out)
}

// encode is urlencode over ordered pairs, as Python's urlencode writes them.
func encode(pairs [][2]string) string {
	parts := make([]string, len(pairs))
	for i, kv := range pairs {
		parts[i] = url.QueryEscape(kv[0]) + "=" + url.QueryEscape(kv[1])
	}
	return strings.Join(parts, "&")
}

// stable is the selection's filters, in the context's order, without the
// chosen school or empty values.
func (pg *page) stable() [][2]string {
	out := [][2]string{}
	for _, kv := range [][2]string{{"fy", pg.f.fy}, {"quarter", pg.f.quarter}, {"region", pg.f.region}, {"district", pg.f.district},
		{"staff", pg.f.staff}, {"project", pg.f.project}, {"project_type", pg.f.projectType}, {"partner_type", pg.f.partnerType},
		{"activity_type", pg.f.activityType}, {"tab", pg.f.tab}, {"q", pg.f.search}, {"per_page", strconv.Itoa(pg.f.perPage)}} {
		if kv[1] != "" {
			out = append(out, kv)
		}
	}
	return out
}

func with(pairs [][2]string, more ...[2]string) [][2]string {
	return append(append([][2]string{}, pairs...), more...)
}

// templateQuery is the template's `{{ key }}={{ value|urlencode }}&` loop
// over the selection (Django's urlencode: a space as %20).
func (pg *page) templateQuery() string {
	var b strings.Builder
	for _, kv := range pg.stable() {
		b.WriteString(kv[0] + "=" + strings.ReplaceAll(url.PathEscape(kv[1]), "+", "%2B") + "&")
	}
	return b.String()
}

func cell(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: t} }
func text(t string) *screensv1.PagePanelItem {
	return fundworkspace.Text(t)
}
func heading(t string) *screensv1.PagePanelItem { return fundworkspace.Heading(t) }

func filter(name, lbl, caption, value string, options [][2]string) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: lbl, Caption: caption}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		if o[0] == value {
			f.Value = value
		}
	}
	return f
}

func (pg *page) filters() *screensv1.PageBlock {
	years := [][2]string{}
	for _, y := range pg.fyOptions {
		years = append(years, [2]string{y, "FY " + y})
	}
	types := [][2]string{{"", "All types"}}
	for _, t := range pg.projectTypes {
		l, ok := rules.ProjectTypes[t]
		if !ok {
			l = pyTitle(strings.ReplaceAll(t, "_", " "))
		}
		types = append(types, [2]string{t, l})
	}
	kinds := [][2]string{{"", "All activities"}}
	for _, k := range pg.activityTypes {
		l, ok := rules.ActivityTypes[k]
		if !ok {
			l = pyTitle(strings.ReplaceAll(k, "_", " "))
		}
		kinds = append(kinds, [2]string{k, l})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			filter("fy", "Fiscal year", "Fiscal Year", pg.f.fy, years),
			filter("quarter", "Quarter", "", pg.f.quarter, [][2]string{{"Q1", "Q1"}, {"Q2", "Q2"}, {"Q3", "Q3"}, {"Q4", "Q4"}}),
			filter("district", "District", "", pg.f.district, append([][2]string{{"", "All districts"}}, pg.districts...)),
			filter("staff", "Staff", "Project Lead", pg.f.staff, append([][2]string{{"", "All project leads"}}, pg.staff...)),
			filter("project_type", "Project type", "Project Type", pg.f.projectType, types),
			filter("partner_type", "Partner type", "Delivery Type", pg.f.partnerType,
				[][2]string{{"", "All delivery types"}, {"staff", "Staff-led"}, {"partner", "Partner-led"}, {"unassigned", "Not assigned"}}),
			filter("activity_type", "Activity type", "Activity Type", pg.f.activityType, kinds),
		},
		Hidden: map[string]string{"tab": pg.f.tab, "project": pg.f.project},
	}}}
}

func pct(part, whole int) int {
	return int(math.RoundToEven(float64(part) / float64(max(whole, 1)) * 100))
}

func (pg *page) strip() *screensv1.PageBlock {
	baseline, risk := 0, 0
	for _, r := range pg.rows {
		if r.bucket == "baseline" {
			baseline++
		}
		if r.average != nil && *r.average < 5 {
			risk++
		}
	}
	weekStart := pg.today.AddDate(0, 0, -((int(pg.today.Weekday()) + 6) % 7))
	weekEnd := weekStart.AddDate(0, 0, 6)
	week, followup := 0, 0
	pairs := map[[2]string]bool{}
	for _, a := range pg.activities {
		live := in(rules.ActiveStatuses, a.status)
		if a.planned != nil && live && !dayOf(*a.planned).Before(weekStart) && !dayOf(*a.planned).After(weekEnd) {
			week++
		}
		if live {
			pairs[[2]string{a.projectID, a.schoolID}] = true
		}
		late := a.planned != nil && dayOf(*a.planned).Before(pg.today) && (a.status == "scheduled" || a.status == "in_progress")
		if in(rules.ReturnedStatuses, a.status) || a.reschedules != 0 || late {
			followup++
		}
	}
	completion := 0
	if len(pg.assignments) > 0 {
		completion = int(math.RoundToEven(float64(len(pairs)) / float64(len(pg.assignments)) * 100))
	}
	values := []string{strconv.Itoa(len(pg.assignments)), strconv.Itoa(baseline), strconv.Itoa(week),
		fmt.Sprintf("%d%%", completion), strconv.Itoa(risk), strconv.Itoa(followup)}
	helpers := []string{"school–project assignments", "FY " + pg.f.fy, "project activities", "project pairs with an activity",
		"SSA average below 5.0", "returned, overdue or rescheduled"}
	return fundworkspace.Strip("Project planning context", rules.MetricLabels[:6], values, helpers)
}

func (pg *page) bands() *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{heading("Readiness guidance")}
	for i, b := range []struct {
		key, trend string
	}{{"baseline", "Complete SSA before support planning"}, {"ready", "Use SSA recommendations"}, {"partner", "Monitor delivery confirmation"}} {
		n := pg.counts[b.key]
		items = append(items, text(rules.MetricLabels[6+i]), text(fmt.Sprintf("%d schools", n)),
			text(fmt.Sprintf("%d%% · %s", pct(n, pg.counts["all"]), b.trend)))
	}
	return fundworkspace.Panel("", items...)
}

func (pg *page) tabPanel() *screensv1.PageBlock {
	return fundworkspace.Panel("",
		text(fmt.Sprintf("All Project Schools %d", pg.counts["all"])), text(fmt.Sprintf("SSA Required %d", pg.counts["baseline"])),
		text(fmt.Sprintf("Ready for Support %d", pg.counts["ready"])), text(fmt.Sprintf("Assigned to Partner %d", pg.counts["partner"])),
		text(fmt.Sprintf("Scheduled %d", pg.counts["scheduled"])))
}

func plural(n int, many string) string {
	if n == 1 {
		return ""
	}
	return many
}

func (pg *page) urls(r row) (schedule, partner, myPlan string) {
	schedule = "/planning/schedule-modal?" + encode([][2]string{{"school_id", r.a.schoolPK}, {"project_id", r.a.projectID}})
	partner = "/projects/planning/bulk-partner?" + encode([][2]string{{"assignments", r.a.id}})
	myPlan = "/projects/my-plan?" + encode([][2]string{{"project", r.a.projectID}, {"q", r.a.schoolName}})
	return
}

func (pg *page) actions(r row) *screensv1.PageCell {
	schedule, partner, myPlan := pg.urls(r)
	first := &screensv1.PageAction{Label: "My Plan", Enabled: true, Href: myPlan}
	if r.kind == "schedule" && pg.role.CanSchedule {
		first = &screensv1.PageAction{Label: "Schedule", Enabled: true, Href: schedule, Drawer: true}
	}
	if !pg.role.CanAssignPartner {
		first.Key, first.Primary = "button", true
		return &screensv1.PageCell{Actions: []*screensv1.PageAction{first}}
	}
	first.Key = "menu"
	return &screensv1.PageCell{Actions: []*screensv1.PageAction{first,
		{Key: "menu", Label: "Assign", Enabled: true, Href: partner, Drawer: true}}}
}

func (pg *page) queue() []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, c := range []string{"", "School ID", "School", "District", "Project", "SSA Score", "Planning readiness",
		"Weakest intervention", "Recommended action", "Partner", "Actions"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	if len(pg.pageRows) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{
			cell("No project schools match these filters · Clear the filters or assign schools to a project from the School Directory.")}}}
	}
	stable := pg.stable()
	for i := 0; i < len(pg.pageRows); {
		group := pg.pageRows[i].a.projectID
		j := i
		for j < len(pg.pageRows) && pg.pageRows[j].a.projectID == group {
			j++
		}
		first := pg.pageRows[i]
		n := j - i
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{
			Text: fmt.Sprintf("%s %s · %d school%s on this page", first.a.projectName, projectTypeOf(first.a), n, plural(n, "s")),
			Href: "/projects/" + first.a.projectID}}})
		for _, r := range pg.pageRows[i:j] {
			code := r.a.schoolCode
			if code == "" {
				code = "—"
			}
			district := r.a.district
			if r.a.districtID == "" {
				district = "—"
			}
			ssa := cell(r.baseline)
			if r.average != nil {
				band, _ := schooldirectory.SSABand(*r.average)
				ssa.Text += fmt.Sprintf("Average %s/10 · %s", pyFloat(*r.average), band)
			}
			ready := cell(r.readiness)
			if r.planned != nil {
				ready.Text += r.planned.Format("02 Jan 2006") + " · " + r.activityType
			}
			weakest := r.a.weakest
			if r.a.ssaDate == nil || weakest == "" {
				weakest = "Not assessed"
			} else {
				weakest = label(rules.Interventions, weakest)
			}
			weak := &screensv1.PageCell{Text: weakest, Strong: true}
			if r.a.ssaDate != nil && r.a.weakestScore != nil {
				weak = cell(weakest + floatformat1(*r.a.weakestScore) + "/10")
			}
			selectURL := PagePath + "?" + encode(with(stable, [2]string{"page", strconv.Itoa(pg.number)}, [2]string{"selected", r.a.id}))
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				cell(""), cell(code), {Text: r.a.schoolName, Href: selectURL, Strong: true}, cell(district),
				cell(r.a.projectName + projectTypeOf(r.a) + " · " + label(rules.SchoolTypes, r.a.schoolType)),
				ssa, ready, weak, cell(r.action), cell(r.partner), pg.actions(r),
			}})
		}
		// The feed reads the table's first <tbody> alone: the first project's
		// block is the queue it shows, the others are not read.
		break
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Project school planning queue",
			Subtitle: "School Directory intake", Items: []*screensv1.PagePanelItem{text(fmt.Sprintf("%d matching assignments", len(pg.rows)))}}}},
		{Kind: &screensv1.PageBlock_Table{Table: t}},
		pg.pager(),
	}
}

func (pg *page) pager() *screensv1.PageBlock {
	first, last := 0, 0
	if len(pg.rows) > 0 {
		first = (pg.number-1)*pg.f.perPage + 1
		last = min(pg.number*pg.f.perPage, len(pg.rows))
	}
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d–%d of %d assignments", first, last, len(pg.rows)),
		Size: &screensv1.PageFilter{Name: "per_page", Label: "Rows", Value: strconv.Itoa(pg.f.perPage)}}
	for _, n := range sizes {
		p.Size.Options = append(p.Size.Options, &screensv1.PageFilterOption{Value: strconv.Itoa(n), Label: strconv.Itoa(n)})
	}
	stable := pg.stable()
	if pg.number > 1 {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Prev", Href: "?" + pg.templateQuery() + "page=" + strconv.Itoa(pg.number-1)})
	}
	for n := 1; n <= pg.pages; n++ {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n),
			Href: PagePath + "?" + encode(with(stable, [2]string{"page", strconv.Itoa(n)}))})
	}
	if pg.number < pg.pages {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Next", Href: "?" + pg.templateQuery() + "page=" + strconv.Itoa(pg.number+1)})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: p}}
}

func (pg *page) side() *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	r := pg.selected
	if r == nil {
		items = append(items, text("Select a school to see its project context and next step."))
	} else {
		name := &screensv1.PageLink{Text: r.a.schoolName}
		if pg.role.SchoolLinks && r.a.schoolName != "" && r.a.schoolCode != "" {
			name.Href = "/schools/" + url.PathEscape(r.a.schoolCode)
		}
		if name.Href != "" {
			items = append(items, fundworkspace.Links(name))
		} else {
			items = append(items, text(r.a.schoolName))
		}
		average := "Not assessed"
		if r.average != nil {
			average = pyFloat(*r.average) + "/10"
		}
		weakest := "Not assessed"
		if r.a.ssaDate != nil && r.a.weakest != "" {
			weakest = label(rules.Interventions, r.a.weakest)
		}
		lines := []*screensv1.PagePanelItem{}
		if r.a.schoolCode != "" {
			lines = append(lines, text(r.a.schoolCode))
		}
		for _, l := range []string{"Project", r.a.projectName, "District", r.a.district, "Weakest intervention", weakest,
			"SSA average", average, "Current partner", r.partner, "Planning readiness", r.readiness} {
			if l != "" {
				lines = append(lines, text(l))
			}
		}
		items = append(items, feeddom.Paired(lines)...)
		items = append(items, fundworkspace.Links(&screensv1.PageLink{Text: "View School", Href: "/schools/" + r.a.schoolPK},
			&screensv1.PageLink{Text: "View SSA", Href: "/schools/" + r.a.schoolPK + "#ssa-timeline"}))
		schedule, _, myPlan := pg.urls(*r)
		step := &screensv1.PageLink{Text: "Open in My Plan", Href: myPlan}
		if r.kind == "schedule" && pg.role.CanSchedule {
			step = &screensv1.PageLink{Text: "Schedule", Href: schedule, Drawer: true}
		}
		items = append(items, text("Recommended next step"), heading(r.action), text(r.next), fundworkspace.Links(step))
	}
	items = append(items, text("Bulk Actions"), heading("0 selected"))
	bulk := []*screensv1.PageLink{}
	if pg.role.CanExport {
		bulk = append(bulk, &screensv1.PageLink{Text: "Export Filtered", Href: PagePath + "?" + encode(with(pg.stable(), [2]string{"export", "csv"}))})
	}
	if r != nil {
		bulk = append(bulk, &screensv1.PageLink{Text: "Open Project Plan", Href: "/projects/" + r.a.projectID})
	}
	if len(bulk) > 0 {
		items = append(items, fundworkspace.Links(bulk...))
	}
	return fundworkspace.Panel("Selected school", items...)
}

// fmtUGX is projects.dashboard_service._fmt_ugx.
func fmtUGX(a int64) string {
	switch {
	case a >= 1_000_000_000:
		return fmt.Sprintf("UGX %.2fB", float64(a)/1e9)
	case a >= 1_000_000:
		return fmt.Sprintf("UGX %.1fM", float64(a)/1e6)
	case a >= 1_000:
		return fmt.Sprintf("UGX %.0fK", float64(a)/1e3)
	}
	return fmt.Sprintf("UGX %d", a)
}

func (pg *page) summary() []*screensv1.PageBlock {
	visits, trainings := 0, 0
	for _, a := range pg.activities {
		if !in(rules.ActiveStatuses, a.status) {
			continue
		}
		if strings.Contains(a.kind, "visit") {
			visits++
		}
		if strings.Contains(a.kind, "training") {
			trainings++
		}
	}
	t := &screensv1.PageTable{}
	for _, c := range []string{"Project", "Schools Assigned", "Ready for Planning", "SSA Required", "Assigned to Partner", "Scheduled"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for _, pr := range pg.projects {
		assigned, ready, baseline, partner, scheduled := 0, 0, 0, 0, 0
		for _, r := range pg.rows {
			if r.a.projectID != pr.id {
				continue
			}
			assigned++
			switch r.bucket {
			case "baseline":
				baseline++
			case "partner":
				partner++
				ready++
			case "ready":
				ready++
			case "scheduled":
				scheduled++
				ready++
			}
		}
		if assigned == 0 && pg.f.project != "" {
			continue
		}
		if len(t.Rows) == 8 {
			break
		}
		readyPct := 0
		if assigned > 0 {
			readyPct = int(math.RoundToEven(float64(ready) / float64(assigned) * 100))
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: pr.name, Href: "/projects/" + pr.id}, cell(strconv.Itoa(assigned)), cell(fmt.Sprintf("%d (%d%%)", ready, readyPct)),
			cell(strconv.Itoa(baseline)), cell(strconv.Itoa(partner)), cell(strconv.Itoa(scheduled)),
		}})
	}
	if len(t.Rows) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{cell("No projects match these filters.")}}}
	}
	return []*screensv1.PageBlock{
		fundworkspace.Panel("Project Planning Summary", text(fmt.Sprintf("%d visit%s and %d training%s in the workflow · Budget generated: %s",
			visits, plural(visits, "s"), trainings, plural(trainings, "s"), fmtUGX(pg.budget)))),
		{Kind: &screensv1.PageBlock_Table{Table: t}},
	}
}

// workspaceNav is partials/projects/workspace_nav.html for the chosen
// project, Plan being this page.
func (pg *page) workspaceNav() *screensv1.PageBlock {
	name := ""
	for _, p := range pg.projects {
		if p.id == pg.f.project {
			name = p.name
		}
	}
	id := pg.f.project
	t := &screensv1.PageLinkTabs{Label: name, Scrolls: true}
	for _, tab := range [][2]string{
		{"Overview", "/projects/" + id}, {"Schools", "/projects/" + id + "#participating-schools"},
		{"Plan", "/projects/planning?project=" + id}, {"Activities", "/projects/my-plan?project=" + id},
		{"Partners", "/projects/planning?project=" + id + "&partner_type=partner"}, {"Budget", "/projects/" + id + "#budget-execution"},
		{"Impact", "/projects/analytics?project=" + id}, {"Issues", "/projects/my-plan?project=" + id + "#project-attention"},
	} {
		t.Tabs = append(t.Tabs, &screensv1.PageLinkTab{Label: tab[0], Href: tab[1], Active: tab[0] == "Plan"})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: t}}
}

func (pg *page) blocks() []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{}
	if pg.f.project != "" {
		out = append(out, pg.workspaceNav())
	}
	out = append(out, pg.filters(), pg.strip(), pg.bands(), pg.tabPanel())
	out = append(out, pg.queue()...)
	out = append(out, pg.side())
	out = append(out, pg.summary()...)
	records := "s"
	if len(pg.assignments) == 1 {
		records = ""
	}
	out = append(out, fundworkspace.Panel("", heading(fmt.Sprintf("Data details · %d records", len(pg.assignments))),
		text(fmt.Sprintf("%d scoped record%s · %s evidence · Decision support; source workflow records remain authoritative.",
			len(pg.assignments), records, strings.ToLower(qualityOf(len(pg.assignments)))))))
	return out
}

// qualityOf is platform_engine._quality's label for a count of records.
func qualityOf(n int) string {
	switch {
	case n == 0:
		return "No data"
	case n < 5:
		return "Very limited"
	case n < 10:
		return "Limited"
	case n < 30:
		return "Moderate"
	}
	return "Strong"
}
