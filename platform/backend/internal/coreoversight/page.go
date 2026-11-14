package coreoversight

import (
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The page's words, as templates/pages/oversight/core_schools_oversight.html
// writes them.
const (
	dash           = "—"
	pageParam      = "page"
	emptySchools   = "No Core school in your scope matches."
	emptyPlan      = "No planned work for the Core schools shown."
	noSchool       = "No school."
	noRecommended  = "No open recommendation for the schools shown."
	recommendIntro = "The SSA recommendations recorded for each school from its confirmed SSA, with the recommended catalogue training (or why none is mapped) and where each stands. A recommendation is not an activity: support is planned from My Plan and Planning."
	championIntro  = "Edify's Champion rule: latest confirmed SSA average 8.0 or more, no intervention below 7.0, and all 8 package visits and trainings done. Readiness is a recommendation; a school becomes a Champion only through the Champion review."
	closingNote    = "Improved and declined follow the published IA measurement rule for each SSA domain; where none is approved, any change counts. Teacher and leader figures are attendance headcounts, not unique people. Planned visits and trainings are on My Plan and Planning Oversight."
)

// schoolColumns are the Core Schools table's headings: (label, numeric).
var schoolColumns = []struct {
	label   string
	numeric bool
}{
	{"School", false}, {"School ID", false}, {"Type", false}, {"District", false}, {"Cluster", false},
	{"CCEO", false}, {"Latest SSA", true}, {"Previous SSA", true}, {"SSA Change", true}, {"Trajectory", false},
	{"Weakest Intervention", false}, {"Visits", true}, {"Trainings", true}, {"Package", true},
	{"Partner Hand-overs", false}, {"Attendance", true}, {"Teacher / Leader Attendances", true},
	{"Enrolment Change", true}, {"Learning Change", true}, {"Champion", false}, {"Needs", false},
}

// groupColumns follow the grouping's own heading.
var groupColumns = []string{
	"Schools", "Current SSA", "Average SSA", "Compared", "Improved", "Declined", "Average Change",
	"Package Complete", "Attendance", "Teacher / Leader Attendances", "Enrolment Growth", "Need Attention",
	"Potential Champions",
}

// view is what the request asks for, read as the view reads it.
type view struct {
	fy, tab, sort, group string
	years                []string
	// get is request.GET.get: the raw value, "" when absent.
	get func(string) string
	// links is the page's own query for its links (the query without tab,
	// page or format), and paged every value but the table's page.
	links, paged string
	query        url.Values
}

// choice is the view's _choice: the value stripped, if it is one of keys.
func choice(query url.Values, key string, keys []string, fallback string) string {
	value := strings.TrimSpace(query.Get(key))
	if in(keys, value) {
		return value
	}
	return fallback
}

func keysOf(pairs [][2]string) []string {
	out := make([]string, len(pairs))
	for i, p := range pairs {
		out[i] = p[0]
	}
	return out
}

// sortedKeys is the query's keys in the order the existing page receives
// them (the gateway hands its query on in key order).
func sortedKeys(query url.Values) []string {
	keys := make([]string, 0, len(query))
	for key := range query {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// encode is QueryDict.urlencode() of the query without the keys left out.
func encode(query url.Values, skip func(key, value string) bool) string {
	parts := []string{}
	for _, key := range sortedKeys(query) {
		for _, value := range query[key] {
			if skip(key, value) {
				continue
			}
			parts = append(parts, url.QueryEscape(key)+"="+url.QueryEscape(value))
		}
	}
	return strings.Join(parts, "&")
}

func newView(query url.Values, fy string, years []string) view {
	v := view{fy: fy, years: years, query: query, get: query.Get}
	v.tab = choice(query, "tab", keysOf(rules.Tabs), "schools")
	v.sort = choice(query, "sort", keysOf(rules.Sorts), "name")
	v.group = choice(query, "group", keysOf(rules.Groupings), "cceo")
	v.links = encode(query, func(key, _ string) bool { return key == "tab" || key == pageParam || key == "format" })
	if paged := encode(query, func(key, value string) bool { return value == "" || key == pageParam }); paged != "" {
		v.paged = paged + "&"
	}
	return v
}

// filtered is the view's _filtered.
func filtered(rows []*school, query url.Values) []*school {
	trajectory := choice(query, "trajectory", keysOf(rules.TrajectoryFilters), "")
	reason := choice(query, "attention", rules.Attention.Order, "")
	readiness := choice(query, "readiness", rules.Champion.Order, "")
	district := strings.TrimSpace(query.Get("district"))
	schoolType := strings.TrimSpace(query.Get("type"))
	q := strings.ToLower(strings.TrimSpace(query.Get("q")))
	out := []*school{}
	for _, r := range rows {
		if (trajectory == "" || r.trajectory == trajectory) &&
			(reason == "" || in(r.attention, reason)) &&
			(readiness == "" || r.champion == readiness) &&
			(district == "" || r.district == district) &&
			(schoolType == "" || r.schoolType == schoolType) &&
			(q == "" || strings.Contains(strings.ToLower(r.name), q) || strings.Contains(strings.ToLower(r.code), q)) {
			out = append(out, r)
		}
	}
	return out
}

// nilLast orders as the sorts' (value is None, value): a missing figure last.
func nilLast[T int | float64](a, b *T) int {
	switch {
	case a == nil && b == nil:
		return 0
	case a == nil:
		return 1
	case b == nil:
		return -1
	case *a < *b:
		return -1
	case *a > *b:
		return 1
	}
	return 0
}

// sorted is the view's sorted(rows, key=SORTS[sort][1]); the sort is
// stable, as Python's is.
func sortedBy(rows []*school, by string) []*school {
	out := slices.Clone(rows)
	compare := map[string]func(a, b *school) int{
		"name":       func(a, b *school) int { return strings.Compare(strings.ToLower(a.name), strings.ToLower(b.name)) },
		"latest":     func(a, b *school) int { return nilLast(a.ssaNow, b.ssaNow) },
		"change":     func(a, b *school) int { return nilLast(a.ssaChange, b.ssaChange) },
		"package":    func(a, b *school) int { return nilLast(a.packagePct(), b.packagePct()) },
		"attendance": func(a, b *school) int { return nilLast(a.attendanceRate(), b.attendanceRate()) },
	}[by]
	slices.SortStableFunc(out, compare)
	return out
}

// reader is who the page is drawn for: what their role may open.
type reader struct {
	doors Doors
}

// page is the page drawn from the records for one reader. operational is
// the running fiscal year the Champion rule reads a school's live plan in.
func page(r *records, who reader, fy string, years []string, operational string, query url.Values) *screensv1.GetPageResponse {
	out, _ := pageWith(r, who, fy, years, operational, query, nil)
	return out
}

// planSheet answers a tab of planned work for the schools the filters keep.
type planSheet func(shown []*school) (myplan.Sheet, error)

// pageWith is the page, with plan answering the two tabs of planned work.
func pageWith(r *records, who reader, fy string, years []string, operational string, query url.Values, plan planSheet) (*screensv1.GetPageResponse, error) {
	v := newView(query, fy, years)
	every := sortedBy(performance(r, fy, operational), "name")
	shown := filtered(every, query)
	rows := sortedBy(shown, v.sort)
	sum := summarise(rows)

	blocks := []*screensv1.PageBlock{filterBlock(v, every), stripBlock(v, sum, len(every)), tabsBlock(v)}
	switch v.tab {
	case "core_visits", "core_trainings":
		if plan == nil {
			return nil, myplan.ErrUnported
		}
		sheet, err := plan(shown)
		if err != nil {
			return nil, err
		}
		blocks = append(blocks, planBlock(v, sheet))
	case "groups":
		blocks = append(blocks, groupBlocks(v, rows)...)
	case "attention":
		blocks = append(blocks, attentionBlocks(rows, who)...)
	case "recommendations":
		blocks = append(blocks, recommendationBlocks(v, rows, r)...)
	case "champion":
		blocks = append(blocks, championBlocks(rows, who)...)
	default:
		blocks = append(blocks, schoolsBlock(v, rows, who))
	}
	blocks = append(blocks, panelBlock("", []*screensv1.PagePanelItem{textItem(closingNote)}))
	return &screensv1.GetPageResponse{
		Header:  header(v, who.doors),
		Blocks:  blocks,
		WebPath: Path,
	}, nil
}

// planBlock is the tab of planned work: table_export's sheet under
// components/data_table, fifty rows a page.
func planBlock(v view, sheet myplan.Sheet) *screensv1.PageBlock {
	t := &screensv1.PageTable{Title: sheet.Title + ", FY " + v.fy, Subtitle: itoa(len(sheet.Rows)) + " planned"}
	if len(sheet.Rows) == 0 {
		t.EmptyMessage = emptyPlan
		return tableBlock(t)
	}
	for _, h := range sheet.Headers {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: h})
	}
	number, pages := pageNumber(v.get(pageParam), len(sheet.Rows))
	start := (number - 1) * rules.TablePageSize
	shown := sheet.Rows[start:min(start+rules.TablePageSize, len(sheet.Rows))]
	for _, cells := range shown {
		row := &screensv1.PageRow{}
		for _, c := range cells {
			row.Cells = append(row.Cells, cell(collapse(c), "", ""))
		}
		t.Rows = append(t.Rows, row)
	}
	if pages > 1 {
		t.Pager = pager(number, pages, len(sheet.Rows), len(shown), v.paged)
		t.Footnote = t.Pager.GetSummary()
	}
	return tableBlock(t)
}

func option(value, label string) *screensv1.PageFilterOption {
	return &screensv1.PageFilterOption{Value: value, Label: collapse(label)}
}

// selectFilter is a select as the feed reads it: the option marked
// selected, else the first.
func selectFilter(name, label string, options []*screensv1.PageFilterOption, selected func(string) bool) *screensv1.PageFilter {
	value := ""
	if len(options) > 0 {
		value = options[0].GetValue()
	}
	for _, o := range options {
		if selected(o.GetValue()) {
			value = o.GetValue()
			break
		}
	}
	return &screensv1.PageFilter{Name: name, Label: label, Value: value, Options: options}
}

func filterBlock(v view, every []*school) *screensv1.PageBlock {
	years := []*screensv1.PageFilterOption{}
	for _, year := range v.years {
		years = append(years, option(year, "FY "+year))
	}
	districts := []string{}
	type kind struct{ value, label string }
	kinds := []kind{}
	for _, r := range every {
		if r.district != "" && !in(districts, r.district) {
			districts = append(districts, r.district)
		}
		if k := (kind{r.schoolType, r.typeLabel}); !slices.Contains(kinds, k) {
			kinds = append(kinds, k)
		}
	}
	sort.Strings(districts)
	slices.SortFunc(kinds, func(a, b kind) int {
		if c := strings.Compare(a.value, b.value); c != 0 {
			return c
		}
		return strings.Compare(a.label, b.label)
	})
	districtOptions := []*screensv1.PageFilterOption{option("", "All districts")}
	for _, d := range districts {
		districtOptions = append(districtOptions, option(d, d))
	}
	typeOptions := []*screensv1.PageFilterOption{option("", "All Core types")}
	for _, k := range kinds {
		typeOptions = append(typeOptions, option(k.value, k.label))
	}
	trajectories := []*screensv1.PageFilterOption{option("", "Any")}
	for _, t := range rules.TrajectoryFilters {
		trajectories = append(trajectories, option(t[0], t[1]))
	}
	reasons := []*screensv1.PageFilterOption{option("", "Anything")}
	for _, reason := range rules.Attention.Order {
		reasons = append(reasons, option(reason, reason))
	}
	readiness := []*screensv1.PageFilterOption{option("", "Any")}
	for _, status := range rules.Champion.Order {
		readiness = append(readiness, option(status, status))
	}
	sorts := []*screensv1.PageFilterOption{}
	for _, s := range rules.Sorts {
		sorts = append(sorts, option(s[0], s[1]))
	}
	// A blank option is never marked selected; the others are by the raw
	// value the request carries, the year and the sort by the one read.
	raw := func(key string) func(string) bool {
		return func(value string) bool { return value != "" && value == v.get(key) }
	}
	hidden := map[string]string{"tab": v.tab}
	if v.tab == "groups" {
		hidden["group"] = v.group
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			selectFilter("fy", "Fiscal year", years, func(value string) bool { return value == v.fy }),
			selectFilter("district", "District", districtOptions, raw("district")),
			selectFilter("type", "Type", typeOptions, raw("type")),
			selectFilter("trajectory", "SSA trajectory", trajectories, raw("trajectory")),
			selectFilter("attention", "Needs", reasons, raw("attention")),
			selectFilter("readiness", "Champion readiness", readiness, raw("readiness")),
			selectFilter("sort", "Sort", sorts, func(value string) bool { return value == v.sort }),
		},
		Hidden: hidden,
	}}}
}

// orDash is {{ x|default_if_none:"—" }} of a float.
func orDash(x *float64) string {
	if x == nil {
		return dash
	}
	return floatStr(*x)
}

func intOrDash(n *int) string {
	if n == nil {
		return dash
	}
	return strconv.Itoa(*n)
}

func signedOrDash(x *float64) string {
	if x == nil {
		return dash
	}
	return signedFloat(*x)
}

func percentOrDash(n *int) string {
	if n == nil {
		return dash
	}
	return strconv.Itoa(*n) + "%"
}

func floatPercentOrDash(x *float64) string {
	if x == nil {
		return dash
	}
	return floatStr(*x) + "%"
}

func itoa(n int) string { return strconv.Itoa(n) }

func stripBlock(v view, s summary, scope int) *screensv1.PageBlock {
	q := "?" + v.links
	inScope := "In your scope"
	if s.schools != scope {
		inScope = "of " + itoa(scope) + " in your scope"
	}
	fyText := "FY " + v.fy
	return schoolprofile.Strip("Performance overview", []schoolprofile.StripFigure{
		{Label: "Core Schools", Value: itoa(s.schools), Helper: inScope},
		{Label: "Current-Year SSA", Value: itoa(s.withCurrentSSA) + " of " + itoa(s.schools), Helper: "Confirmed in " + fyText},
		{Label: "Compared", Value: itoa(s.compared) + " of " + itoa(s.schools), Link: q + "&trajectory=not_comparable",
			Helper: "Confirmed SSA in both years · " + itoa(s.notCompared) + " not compared"},
		{Label: "Improved", Value: itoa(s.improved), Link: q + "&trajectory=improved", Helper: "Of " + itoa(s.compared) + " compared"},
		{Label: "Declined", Value: itoa(s.declined), Link: q + "&trajectory=declined", Helper: "Of " + itoa(s.compared) + " compared"},
		{Label: "Average SSA", Value: orDash(s.avgLatest), Helper: itoa(s.withCurrentSSA) + " schools, " + fyText},
		{Label: "Average SSA Change", Value: signedOrDash(s.avgChange), Helper: "Points, " + itoa(s.compared) + " compared"},
		{Label: "Package Complete", Value: itoa(s.packageComplete) + " of " + itoa(s.withPlan),
			Helper: "Visits " + itoa(s.visitsDone) + "/" + itoa(s.visitsTarget) + " · Trainings " + itoa(s.trainingsDone) + "/" + itoa(s.trainingsTarget)},
		{Label: "Session Attendance", Value: percentOrDash(s.attendanceRate), Helper: itoa(s.attended) + " of " + itoa(s.invited) + " invitations"},
		{Label: "Teacher Attendances", Value: itoa(s.teachers), Helper: "Headcounts, not unique people · " + itoa(s.leaders) + " leader attendances"},
		{Label: "Enrolment Growth", Value: floatPercentOrDash(s.enrolGrowthPct), Helper: itoa(s.enrolCompared) + " schools with both years"},
		{Label: "Need Attention", Value: itoa(s.needsAttention), Link: q + "&tab=attention",
			Helper: itoa(s.readiness[rules.Champion.Potential]) + " Potential Champion"},
	})
}

func linkTabs(tabs []*screensv1.PageLinkTab) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs, Scrolls: true}}}
}

func tabsBlock(v view) *screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{}
	for _, t := range rules.Tabs {
		tabs = append(tabs, &screensv1.PageLinkTab{Label: collapse(t[1]), Href: "?" + v.links + "&tab=" + t[0], Active: t[0] == v.tab})
	}
	return linkTabs(tabs)
}

// schoolHref is {% school_link %}'s link: the profile for a reader it lets
// in, none for a school with no name or id.
func schoolHref(r *school, who reader) string {
	if !who.doors.School || r.name == "" || strings.TrimSpace(r.id) == "" {
		return ""
	}
	return "/schools/" + url.PathEscape(strings.TrimSpace(r.id))
}

func cell(text, href, tone string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: collapse(text), Href: href, Tone: tone}
}

func orDashText(s string) string {
	if s == "" {
		return dash
	}
	return s
}

func schoolCells(r *school, who reader) []*screensv1.PageCell {
	cluster := cell(dash, "", "")
	if r.clusterID != "" && r.cluster != "" {
		cluster = cell(r.cluster, "/clusters/"+r.clusterID+"/profile", "")
	}
	weakest := dash
	if r.weakest != "" {
		weakest = r.weakestLabel + " (" + orDash(r.weakestScore) + ")"
	}
	visits, trainings := dash, dash
	if r.hasPlan {
		visits = itoa(r.visitsDone) + "/" + itoa(r.visitsTarget)
		trainings = itoa(r.trainingsDone) + "/" + itoa(r.trainingsTarget)
	}
	handovers := "None"
	if r.handoversAssigned != 0 || r.handoversScheduled != 0 || r.handoversCompleted != 0 {
		handovers = fmt.Sprintf("%d unscheduled · %d scheduled · %d done", r.handoversAssigned, r.handoversScheduled, r.handoversCompleted)
	}
	attendance := dash
	if rate := r.attendanceRate(); rate != nil {
		attendance = fmt.Sprintf("%d%% (%d/%d)", *rate, r.attended, r.invited)
	}
	enrolment := dash
	if change := r.enrolChange(); change != nil {
		enrolment = signedInt(*change)
		if pct := r.enrolGrowthPct(); pct != nil {
			enrolment += " (" + floatStr(*pct) + "%)"
		}
	}
	learning := dash
	if change := r.learnChange(); change != nil {
		learning = signedFloat(*change) + " pts"
	}
	needs := strings.Join(r.attention, "; ")
	if needs == "" {
		needs = dash
	}
	return []*screensv1.PageCell{
		cell(r.name, schoolHref(r, who), ""),
		cell(orDashText(r.code), "", ""),
		cell(r.typeLabel, "", ""),
		cell(orDashText(r.district), "", ""),
		cluster,
		cell(r.owner, "", ""),
		cell(orDash(r.ssaNow), "", ""),
		cell(orDash(r.ssaBefore), "", ""),
		cell(signedOrDash(r.ssaChange), "", ""),
		cell(r.trajectoryLabel(), "", r.trajectoryTone()),
		cell(weakest, "", ""),
		cell(visits, "", ""),
		cell(trainings, "", ""),
		cell(r.packageLabel(), "", ""),
		cell(handovers, "", ""),
		cell(attendance, "", ""),
		cell(intOrDash(r.teachers)+" / "+intOrDash(r.leaders), "", ""),
		cell(enrolment, "", ""),
		cell(learning, "", ""),
		cell(r.champion, "", ""),
		cell(needs, "", ""),
	}
}

func tableBlock(t *screensv1.PageTable) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func schoolsBlock(v view, rows []*school, who reader) *screensv1.PageBlock {
	t := &screensv1.PageTable{Title: "Core Schools, FY " + v.fy, Subtitle: itoa(len(rows)) + " school" + pluralS(len(rows))}
	if len(rows) == 0 {
		t.EmptyMessage = emptySchools
		return tableBlock(t)
	}
	for _, c := range schoolColumns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c.label, Numeric: c.numeric})
	}
	number, pages := pageNumber(v.get(pageParam), len(rows))
	start := (number - 1) * rules.TablePageSize
	shown := rows[start:min(start+rules.TablePageSize, len(rows))]
	for _, r := range shown {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: schoolCells(r, who)})
	}
	if pages > 1 {
		t.Pager = pager(number, pages, len(rows), len(shown), v.paged)
		// The feed takes the first paragraph under the table for its note:
		// the pager's own "Showing 1–50 of 60".
		t.Footnote = t.Pager.GetSummary()
	}
	return tableBlock(t)
}

// pageNumber is {% paginate %}'s reading of the page asked for: a number
// from one up, the first for anything else, clamped to the pages there are.
func pageNumber(requested string, total int) (number, pages int) {
	size := rules.TablePageSize
	pages = max(1, (total+size-1)/size)
	number = 1
	if n, ok := clusterpage.PyInt(requested); ok && requested != "" {
		number = max(1, n)
	}
	return min(number, pages), pages
}

// window is pagination.make_pagination_window(current, pages, window_size=1):
// the page numbers the pager shows, 0 for a gap.
func window(current, pages int) []int {
	out := []int{}
	if pages <= 7 {
		for p := 1; p <= pages; p++ {
			out = append(out, p)
		}
		return out
	}
	out = append(out, 1)
	if current-1 > 2 {
		out = append(out, 0, current-1)
	} else {
		for p := 2; p < current; p++ {
			out = append(out, p)
		}
	}
	if current != 1 {
		out = append(out, current)
	}
	if current+1 < pages-1 {
		out = append(out, current+1, 0)
	} else {
		for p := current + 1; p < pages; p++ {
			out = append(out, p)
		}
	}
	if !slices.Contains(out, pages) {
		out = append(out, pages)
	}
	return out
}

// pager is components/table_pager.html as the feed reads it; base is
// {% pager_query %}.
func pager(number, pages, total, shown int, base string) *screensv1.PagePager {
	first := (number-1)*rules.TablePageSize + 1
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d–%d of %d", first, first+shown-1, total)}
	href := func(page int) string { return "?" + base + pageParam + "=" + strconv.Itoa(page) }
	if number > 1 {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Prev", Href: href(number - 1)})
	}
	for _, n := range window(number, pages) {
		switch {
		case n == 0:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "…"})
		case n == number:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Current: true})
		default:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Href: href(n)})
		}
	}
	if number < pages {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Next", Href: href(number + 1)})
	}
	return p
}

func groupBlocks(v view, rows []*school) []*screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{}
	heading := ""
	for _, g := range rules.Groupings {
		tabs = append(tabs, &screensv1.PageLinkTab{Label: "By " + g[1], Href: "?" + v.links + "&tab=groups&group=" + g[0], Active: g[0] == v.group})
		if g[0] == v.group {
			heading = g[1]
		}
	}
	grouped := groups(rows, v.group)
	t := &screensv1.PageTable{Title: "Core Schools by " + heading + ", FY " + v.fy, Subtitle: itoa(len(grouped)) + " group" + pluralS(len(grouped))}
	if len(grouped) == 0 {
		t.EmptyMessage = emptySchools
	} else {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: heading})
		for _, label := range groupColumns {
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label, Numeric: true})
		}
		for _, g := range grouped {
			s := g.sum
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				cell(g.label, "", ""),
				cell(itoa(s.schools), "", ""),
				cell(itoa(s.withCurrentSSA)+" of "+itoa(s.schools), "", ""),
				cell(orDash(s.avgLatest), "", ""),
				cell(itoa(s.compared), "", ""),
				cell(itoa(s.improved), "", ""),
				cell(itoa(s.declined), "", ""),
				cell(signedOrDash(s.avgChange), "", ""),
				cell(itoa(s.packageComplete)+" of "+itoa(s.withPlan), "", ""),
				cell(percentOrDash(s.attendanceRate), "", ""),
				cell(itoa(s.teachers)+" / "+itoa(s.leaders), "", ""),
				cell(floatPercentOrDash(s.enrolGrowthPct), "", ""),
				cell(itoa(s.needsAttention), "", ""),
				cell(itoa(s.readiness[rules.Champion.Potential]), "", ""),
			}})
		}
	}
	return []*screensv1.PageBlock{linkTabs(tabs), tableBlock(t)}
}

// ── Panels, as the feed reads a list section (page_blocks._fallback) ───────

func textItem(text string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: collapse(text)}}
}

func panelBlock(title string, items []*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: collapse(title), Items: paired(items)}}}
}

// items gathers a panel's parts as page_blocks._panel_items reads them: a
// line of text where the page writes one, and a link joining the list of
// links just before it.
type items []*screensv1.PagePanelItem

func (it *items) text(text string) {
	if text = collapse(text); text != "" {
		*it = append(*it, textItem(text))
	}
}

func (it *items) link(text, href string, drawer bool) {
	link := &screensv1.PageLink{Text: collapse(text), Href: href, Drawer: drawer}
	if link.GetText() == "" {
		return
	}
	if n := len(*it); n > 0 {
		if links := (*it)[n-1].GetLinks(); links != nil {
			links.Links = append(links.Links, link)
			return
		}
	}
	*it = append(*it, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{link}}}})
}

// figure is page_blocks.FIGURE: a figure on its own.
var figure = regexp.MustCompile(`^(?:—|[-+−]?(?:UGX\s+)?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB])?(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?)$`)

var pagerCaption = regexp.MustCompile(`^Showing\s+\d`)

func hasLetter(s string) bool {
	return strings.IndexFunc(s, unicode.IsLetter) >= 0
}

// paired is page_blocks._paired: a label line followed by its figure, as
// data rows; consecutive pairs share one list.
func paired(in []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	out := []*screensv1.PagePanelItem{}
	for i := 0; i < len(in); i++ {
		item := in[i]
		_, isText := item.GetKind().(*screensv1.PagePanelItem_Text)
		var after *screensv1.PagePanelItem
		if i+1 < len(in) {
			after = in[i+1]
		}
		_, afterText := after.GetKind().(*screensv1.PagePanelItem_Text)
		if !isText || pagerCaption.MatchString(item.GetText()) || after == nil || !afterText ||
			!hasLetter(item.GetText()) || !figure.MatchString(strings.TrimSpace(after.GetText())) {
			out = append(out, item)
			continue
		}
		row := &screensv1.PageDataRow{Label: item.GetText(), Value: strings.TrimSpace(after.GetText()), Tone: after.GetTone()}
		if n := len(out); n > 0 && out[n-1].GetRows() != nil {
			out[n-1].GetRows().Rows = append(out[n-1].GetRows().Rows, row)
		} else {
			out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{row}}}})
		}
		i++
	}
	return out
}

// listSection is one card of a list tab: its heading and count, then its
// schools (or "No school.").
func listSection(title string, count int, body items) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{}
	// The heading and its count are read as one text with nothing between
	// them ("Champion39"), and a part of fewer than two words is not drawn
	// (page_blocks.MIN_FALLBACK_WORDS): a one-word heading is lost.
	if len(strings.Fields(title+itoa(count))) >= minFallbackWords {
		out = append(out, panelBlock(title, []*screensv1.PagePanelItem{textItem(itoa(count))}))
	}
	if count == 0 {
		return append(out, panelBlock("", []*screensv1.PagePanelItem{textItem(noSchool)}))
	}
	return append(out, panelBlock("", body))
}

// name writes a school's name as {% school_link %} does: a link the feed
// reads, or text it leaves out (a line beside an element is not read).
func (it *items) name(r *school, who reader) {
	if href := schoolHref(r, who); href != "" {
		it.link(r.name, href, false)
	}
}

// caption is the line beside a school's name. A reader who cannot open the
// school sees its name as plain text, which the feed reads together with the
// caption that follows it (the reader joins words around an element).
func caption(r *school, who reader, text string) string {
	if schoolHref(r, who) == "" {
		return r.name + " " + text
	}
	return text
}

func attentionBlocks(rows []*school, who reader) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{}
	for _, reason := range rules.Attention.Order {
		body := items{}
		count := 0
		for _, r := range rows {
			if !in(r.attention, reason) {
				continue
			}
			count++
			body.name(r, who)
			body.text(caption(r, who, r.code+" · "+orDashText(r.district)+" · "+r.owner))
			body.text("Latest SSA " + orDash(r.ssaNow) + " · " + r.trajectoryLabel() + " · Package " + r.packageLabel())
		}
		out = append(out, listSection(reason, count, body)...)
	}
	return out
}

func championBlocks(rows []*school, who reader) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{panelBlock("", []*screensv1.PagePanelItem{textItem(championIntro)})}
	for _, status := range rules.Champion.Order {
		body := items{}
		count := 0
		for _, r := range rows {
			if r.champion != status {
				continue
			}
			count++
			body.name(r, who)
			body.text(caption(r, who, r.code+" · "+r.owner))
			weakest := dash
			if r.weakest != "" {
				weakest = r.weakestLabel + " (" + orDash(r.weakestScore) + ")"
			}
			line := "Latest SSA " + orDash(r.ssaNow) + " · Weakest " + weakest + " · Package " + r.packageLabel()
			if r.championScore != nil {
				line += " · Champion score " + floatStr(*r.championScore)
			}
			body.text(line)
			if status == rules.Champion.Potential && who.doors.Review {
				body.link("Review", "/core-schools/"+r.code+"/champion-review", true)
			}
		}
		out = append(out, listSection(status, count, body)...)
	}
	return out
}

func recommendationBlocks(v view, rows []*school, r *records) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{panelBlock("", []*screensv1.PagePanelItem{textItem(recommendIntro)})}
	shown := map[string]bool{}
	for _, row := range rows {
		shown[row.id] = true
	}
	bySchool := map[string][]recommendationRow{}
	for _, rec := range r.Recommendations {
		if shown[rec.SchoolID] && in(rules.RecommendationShownStates, rec.State) {
			bySchool[rec.SchoolID] = append(bySchool[rec.SchoolID], rec)
		}
	}
	any := false
	for _, row := range rows {
		recs := bySchool[row.id]
		if len(recs) == 0 {
			continue
		}
		any = true
		head := items{}
		head.text(itoa(len(recs)))
		head.link("Act on these", "/schools/"+row.id+"?tab=core&fy="+v.fy, false)
		out = append(out, panelBlock(row.name+" "+row.code+" · "+row.owner, head))
		body := items{}
		for _, rec := range recs {
			body.text(recommendationText(rec))
			state, ok := rules.RecommendationStates[rec.State]
			if !ok {
				state = rec.State
			}
			body.text(state)
		}
		out = append(out, panelBlock("", body))
	}
	if !any {
		out = append(out, panelBlock("", []*screensv1.PagePanelItem{textItem(noRecommended)}))
	}
	return out
}

// minFallbackWords is page_blocks.MIN_FALLBACK_WORDS: a part the feed reads
// as a plain panel needs this many words.
const minFallbackWords = 2

// header is the page's header with its downloads for a reader who may
// export: the schools the filters keep as a CSV, and on a tab of planned
// work that tab as an Excel workbook (the query without tab, page or format,
// none the feed holds back).
func header(v view, d Doors) *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow: "Oversight",
		Title:   "Core School Oversight",
		Description: "Are the Core schools improving, is the package delivered, are schools taking part, and which need action: FY " +
			v.fy + " against the year before.",
	}
	if !d.Export {
		return h
	}
	own := url.Values{}
	for key, values := range v.query {
		if key != "tab" && key != pageParam && key != "format" && !in(rules.NotPassedQueryKeys, key) {
			own[key] = values
		}
	}
	with := func(pairs ...string) url.Values {
		out := url.Values{}
		for key, values := range own {
			out[key] = values
		}
		for i := 0; i+1 < len(pairs); i += 2 {
			out.Set(pairs[i], pairs[i+1])
		}
		return out
	}
	h.Actions = append(h.Actions, pageheader.Download("Download CSV", pageheader.Href(Path, with("format", "csv"))))
	if in(rules.PlanTabs, v.tab) {
		h.Actions = append(h.Actions,
			pageheader.Download("Download Excel", pageheader.Href(Path, with("tab", v.tab, "format", "xlsx"))))
	}
	return h
}

// recommendationText is one recommendation's line as the feed reads the
// template's span: the intervention (score, band), " · ", the recommended
// training or "No mapped training[: why]", then the reason, joined with no
// separator as the feed joins adjacent inline text.
func recommendationText(rec recommendationRow) string {
	line := interventionDisplay(rec.Intervention)
	if rec.Score != nil {
		line += " (" + decimalOne(*rec.Score)
		if rec.Band != "" {
			line += ", " + rec.Band
		}
		line += ")"
	}
	line += " · "
	if rec.HasItem {
		line += rec.Item
	} else {
		line += "No mapped training"
		if rec.Unmapped != "" {
			line += ": " + rec.Unmapped
		}
	}
	return line + rec.Reason
}
