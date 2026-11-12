package clusterpage

import (
	"fmt"
	"math"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// pageSize is the page's Paginator(cards, 5).
const pageSize = 5

// collapse is the feed's reading of a text: its whitespace run together.
func collapse(text string) string { return strings.Join(strings.Fields(text), " ") }

// header is pages/clusters/index.html's header as the feed reads it: the
// buttons each gated on the door the drawer behind it enforces (Export is a
// link the feed does not offer).
func header(d Doors) *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow:     "Schools & Field",
		Title:       "Clusters",
		Description: "Manage cluster performance, SSA weaknesses, meetings, trainings, and school-level improvement.",
	}
	button := func(key, label, href string) *screensv1.PageAction {
		return &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href, Drawer: true}
	}
	if d.Create {
		h.Actions = append(h.Actions, button("create_cluster", "Create Cluster", "/clusters/create-drawer"))
	}
	if d.Plan {
		h.Actions = append(h.Actions,
			button("schedule_group_training", "Schedule Group Training", "/planning/schedule-modal?action=training"),
			button("schedule_cluster_meeting", "Schedule Cluster Meeting", "/planning/schedule-modal?action=meeting"))
	}
	return h
}

// option is one <option> of a filter.
type option struct{ value, label string }

// filterState is the page's query as the view reads it (each value
// stripped) and the year it validated.
type filterState struct {
	q, fy, quarter, district, subCounty, staff, ssaStatus, risk, activity string
}

// selectBlock is one <select> as the feed reads it: the selected option's
// value, or the first option's when none is selected.
func selectBlock(name, label, selected string, options []option) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label}
	chosen := ""
	for i, o := range options {
		if i == 0 {
			chosen = o.value
		}
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: collapse(o.label)})
	}
	for _, o := range options {
		if o.value == selected {
			chosen = o.value
			break
		}
	}
	f.Value = chosen
	return f
}

func withAll(options []option) []option { return append([]option{{"", "All"}}, options...) }

// filters is partials/clusters/filters.html.
func filters(f filterState, fyOptions []string, districts, subCounties, staff []option) *screensv1.PageBlock {
	years := []option{}
	for _, y := range fyOptions {
		years = append(years, option{y, "FY " + y})
	}
	list := []*screensv1.PageFilter{
		selectBlock("fy", "Fiscal year", f.fy, years),
		selectBlock("quarter", "Quarter", f.quarter, withAll([]option{{"Q1", "Q1"}, {"Q2", "Q2"}, {"Q3", "Q3"}, {"Q4", "Q4"}})),
		selectBlock("district", "District", f.district, withAll(districts)),
		selectBlock("sub_county", "Sub-county", f.subCounty, withAll(subCounties)),
		selectBlock("staff", "Staff", f.staff, withAll(staff)),
		selectBlock("ssa_status", "SSA status", f.ssaStatus, withAll([]option{{"done", "Complete"}, {"not_done", "Incomplete"}})),
		selectBlock("cluster_risk", "Cluster risk", f.risk, withAll([]option{{"critical", "Critical"}, {"needs_attention", "Needs Attention"}, {"healthy", "Healthy"}})),
		selectBlock("activity_status", "Activity status", f.activity, withAll([]option{{"pending", "Pending"}, {"completed", "Completed"}})),
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: list}}}
}

// ── The strip ────────────────────────────────────────────────────────────

// percentOf is the strip's round(n * 100 / total), Python's round to even.
func percentOf(n, total int) int {
	if total <= 0 {
		return 0
	}
	return int(math.RoundToEven(float64(n*100) / float64(total)))
}

// stripBlock is get_dashboard_data's eight figures over the listed cards.
func stripBlock(list []card) *screensv1.PageBlock {
	total, schools, withoutSSA, needing, notMet, pending := len(list), 0, 0, 0, 0, 0
	ssas := []float64{}
	byIntervention := map[string][]float64{}
	for _, c := range list {
		schools += c.schools
		if c.plan.WithSSA < c.schools {
			withoutSSA++
		}
		if c.risk() == "critical" || (c.avgSSA != nil && *c.avgSSA < 5.5) {
			needing++
		}
		if !c.plan.metThisQuarter() {
			notMet++
		}
		pending += c.plan.MeetingsOpen
		if c.avgSSA != nil {
			ssas = append(ssas, *c.avgSSA)
		}
		for _, w := range c.weakest() {
			byIntervention[w.intervention] = append(byIntervention[w.intervention], w.avg)
		}
	}
	avg := 0.0
	if len(ssas) > 0 {
		avg = schooldirectory.PyRound1(schooldirectory.PySum(ssas) / float64(len(ssas)))
	}
	weakestName, weakestAvg, lowest := "None", 0.0, 99.0
	for _, iv := range rules.SSAInterventions {
		values := byIntervention[iv[0]]
		if len(values) == 0 {
			continue
		}
		if a := schooldirectory.PySum(values) / float64(len(values)); a < lowest {
			lowest, weakestName, weakestAvg = a, iv[1], schooldirectory.PyRound1(a)
		}
	}
	share := func(n int) string { return fmt.Sprintf("%d%% of total", percentOf(n, total)) }
	l := rules.StripLabels
	return schoolprofile.Strip("Cluster context", []schoolprofile.StripFigure{
		{Label: l[0], Value: strconv.Itoa(total), Helper: "Active"},
		{Label: l[1], Value: thousands(schools), Helper: fmt.Sprintf("Across %d clusters", total)},
		{Label: l[2], Value: strconv.Itoa(withoutSSA), Helper: share(withoutSSA)},
		{Label: l[3], Value: strconv.Itoa(needing), Helper: share(needing)},
		{Label: l[4], Value: strconv.Itoa(notMet), Helper: share(notMet)},
		{Label: l[5], Value: strconv.FormatFloat(avg, 'f', 1, 64), Helper: "Out of 10.0"},
		{Label: l[6], Value: weakestName, Helper: "Avg " + strconv.FormatFloat(weakestAvg, 'f', 1, 64)},
		{Label: l[7], Value: strconv.Itoa(pending), Helper: "This quarter"},
	})
}

// thousands is Python's f"{n:,}".
func thousands(n int) string {
	s := strconv.Itoa(n)
	sign := ""
	if strings.HasPrefix(s, "-") {
		sign, s = "-", s[1:]
	}
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return sign + s
}

// ── A card ───────────────────────────────────────────────────────────────

// pyFloat is Python's str() of a float rounded to one place: "71.4", "100.0".
func pyFloat(v float64) string {
	s := strconv.FormatFloat(v, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eE") {
		s += ".0"
	}
	return s
}

// scoreText is |floatformat:"-1": one place, none when it is a whole number.
func scoreText(v float64) string {
	s := strconv.FormatFloat(v, 'f', 1, 64)
	return strings.TrimSuffix(s, ".0")
}

// dayText is strftime("%d %b %Y"), or "Never".
func dayText(c *card, meeting bool) string {
	at := c.lastTraining
	if meeting {
		at = c.lastMeeting
	}
	if at == nil {
		return "Never"
	}
	return at.Format("02 Jan 2006")
}

// riskTone is the feed's colour for a word of the card's risk.
func riskTone(risk string) string {
	switch risk {
	case "critical":
		return "alert"
	case "needs_attention":
		return "caution"
	}
	return "good"
}

func orDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

// record is partials/clusters/cluster_card.html as the feed reads a record.
func record(c card, d Doors, fy string) *screensv1.PageRecord {
	risk := c.risk()
	badge := map[string]string{"critical": "Critical", "needs_attention": "Needs Attention", "healthy": "Healthy"}[risk]
	nextAction := map[string]string{"critical": "Schedule training", "needs_attention": "Monitor progress", "healthy": "Continue support"}[risk]
	r := &screensv1.PageRecord{
		Title:       collapse(c.Name),
		Badges:      []*screensv1.PageBadge{{Text: badge, Tone: riskTone(risk)}},
		DetailsPath: "/partials/clusters/" + c.ID + "/schools",
	}
	if r.Title != "" {
		r.Href = "/clusters/" + c.ID
	}
	menu := func(label, href string) *screensv1.PageAction {
		return &screensv1.PageAction{Key: "menu", Label: label, Enabled: true, Href: href, Drawer: true}
	}
	if d.Plan {
		r.Actions = append(r.Actions,
			menu("Schedule Group Training", "/planning/schedule-modal?cluster_id="+c.ID+"&action=training"),
			menu("Schedule Cluster Meeting", "/planning/schedule-modal?cluster_id="+c.ID+"&action=meeting"),
			menu("Partner to Facilitate", "/clusters/"+c.ID+"/facilitator-drawer"))
	}
	if d.AddSchools {
		r.Actions = append(r.Actions, menu("Add Schools", "/clusters/"+c.ID+"/bulk-assign-drawer"))
	}
	avg := "—"
	if c.avgSSA != nil {
		avg = strconv.FormatFloat(*c.avgSSA, 'f', 1, 64) + "/10"
	}
	coverage := "0"
	if v := c.plan.coverage(); v != 0 {
		coverage = pyFloat(v)
	}
	fact := func(label, value, tone string) *screensv1.PageFact {
		return &screensv1.PageFact{Label: label, Value: collapse(value), Tone: tone}
	}
	r.Facts = []*screensv1.PageFact{
		fact("Location", c.districtLine()+", "+c.subCountyLine(), ""),
		fact("Cluster Leader", orDefault(c.LeaderName, "Not Assigned"), ""),
		fact("Cluster Leader Phone", orDefault(c.LeaderPhone, "Not Entered"), ""),
		fact("Facilitated by", orDefault(c.facilitator, "Staff"), ""),
		fact("Schools", strconv.Itoa(c.schools), ""),
		fact("Assigned Staff", strconv.Itoa(c.staff), ""),
		fact("Avg SSA", avg, riskTone(risk)),
		fact("Meetings (FY)", strconv.Itoa(c.meetingsFY), ""),
		fact("Last Meeting", dayText(&c, true), ""),
		fact("Last Training", dayText(&c, false), ""),
		fact("SSA Coverage", fmt.Sprintf("%d/%d (%s%%)", c.plan.WithSSA, c.schools, coverage), ""),
		fact("Without SSA", fmt.Sprintf("%d schools", c.plan.Schools-c.plan.WithSSA), "caution"),
		fact("SSA Required", strconv.Itoa(c.plan.Baseline), "alert"),
		fact("Needing Cleanup", strconv.Itoa(c.plan.Cleanup), ""),
		fact("Ready for Planning", strconv.Itoa(c.plan.Ready), "good"),
		fact("Next Action", nextAction, riskTone(risk)),
	}
	r.Details = []*screensv1.PageBlock{scoresPanel(c, fy)}
	return r
}

func textItem(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// scoresPanel is partials/schools/ssa_score_groups.html for the cluster's
// averages: its groups, or the line that none is recorded.
func scoresPanel(c card, fy string) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{textItem("Latest confirmed assessment · FY " + fy)}
	groups, has := schooldirectory.SSAGroups(c.summary())
	if !has {
		items = append(items, textItem("No confirmed SSA scores are available yet."))
	}
	for _, g := range groups {
		if !has {
			break
		}
		links := []*screensv1.PageLink{}
		for _, item := range g.Items {
			links = append(links, &screensv1.PageLink{Text: collapse(fmt.Sprintf("%s (%s/10)", item.Label, scoreText(item.Score)))})
		}
		if len(links) == 0 {
			links = append(links, &screensv1.PageLink{Text: "No confirmed scores in this group."})
		}
		items = append(items,
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: g.Title}},
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Intervention scores", Subtitle: "SSA detail", Items: items,
	}}}
}

// empty is cluster_list.html's "No clusters found." card.
func empty(d Doors) *screensv1.PageBlock {
	links := []*screensv1.PageLink{}
	if d.Create {
		links = append(links, &screensv1.PageLink{Text: "Create Cluster", Href: "/clusters/create-drawer", Drawer: true})
	}
	links = append(links, &screensv1.PageLink{Text: "Open School Directory", Href: "/schools"})
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		textItem("No clusters found."),
		textItem("Create new clusters or modify your filter settings to locate clusters."),
		{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}},
	}}}}
}

// ── Pages ────────────────────────────────────────────────────────────────

// pyInt is Python's int() of a query value: surrounding whitespace, a sign,
// and underscores between digits allowed.
func pyInt(text string) (int, bool) {
	s := strings.TrimSpace(text)
	sign := 1
	if strings.HasPrefix(s, "+") || strings.HasPrefix(s, "-") {
		if s[0] == '-' {
			sign = -1
		}
		s = s[1:]
	}
	if s == "" || s[0] == '_' || s[len(s)-1] == '_' || strings.Contains(s, "__") {
		return 0, false
	}
	n, err := strconv.Atoi(strings.ReplaceAll(s, "_", ""))
	if err != nil || strings.ContainsAny(strings.ReplaceAll(s, "_", ""), "+-") {
		return 0, false
	}
	return sign * n, true
}

// pageOf is Paginator.get_page: a page that is not a number is the first,
// one out of range the last.
func pageOf(requested string, count int) (number, pages int) {
	pages = max(1, (count+pageSize-1)/pageSize)
	n, ok := pyInt(requested)
	switch {
	case requested == "":
		return 1, pages
	case !ok:
		return 1, pages
	case n < 1 || n > pages:
		return pages, pages
	}
	return n, pages
}

// elided is Paginator.get_elided_page_range(number, on_each_side=1,
// on_ends=1); 0 is the gap.
func elided(number, pages int) []int {
	out := []int{}
	span := func(from, to int) {
		for i := from; i < to; i++ {
			out = append(out, i)
		}
	}
	if pages <= 4 {
		span(1, pages+1)
		return out
	}
	if number > 4 {
		out = append(out, 1, 0)
		span(number-1, number+1)
	} else {
		span(1, number+1)
	}
	if number < pages-3 {
		span(number+1, number+2)
		out = append(out, 0, pages)
	} else {
		span(number+1, pages+1)
	}
	return out
}

// pager is cluster_list.html's footer as the feed reads it.
func pager(number, pages, count int) *screensv1.PageBlock {
	start := (number-1)*pageSize + 1
	end := min(number*pageSize, count)
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d to %d of %d clusters", start, end, count)}
	link := func(label string, page int) *screensv1.PagePagerPage {
		return &screensv1.PagePagerPage{Label: label, Href: "/clusters?page=" + strconv.Itoa(page)}
	}
	if number > 1 {
		p.Pages = append(p.Pages, link("Prev", number-1))
	}
	for _, n := range elided(number, pages) {
		switch {
		case n == 0:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "…"})
		case n == number:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Current: true})
		default:
			p.Pages = append(p.Pages, link(strconv.Itoa(n), n))
		}
	}
	if number < pages {
		p.Pages = append(p.Pages, link("Next", number+1))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: p}}
}
