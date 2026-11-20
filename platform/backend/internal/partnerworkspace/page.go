package partnerworkspace

import (
	"fmt"
	"math"
	"net/url"
	"slices"
	"sort"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The page's words, as templates/pages/partners/index.html writes them.
const (
	title         = "Partner Activities"
	description   = "See assigned schools, confirm delivery dates, monitor support, and follow up before work falls behind."
	stripTitle    = "Partner activity context"
	generalFocus  = "General support"
	generalSSA    = "General Support"
	noRows        = "No partner work matches these filters."
	noCardsTitle  = "No partner activities found"
	noCardsHint   = "Try changing the filters, or assign a school to an active partner."
	noPending     = "Every current assignment has a delivery date."
	noUpcoming    = "No future partner activities are scheduled."
	unassigned    = "Unassigned target"
	listedPending = 5
	listedComing  = 5
)

// row is one line of a card's table, as _partner_workspace builds it.
type row struct {
	partnerID, partnerName              string
	school, code, place, purpose, focus string
	date                                *day
	status, tone, detail                string
	cost                                int64
	costPending, pending, overdue       bool
}

type card struct {
	p                          partner
	rows                       []row
	schools, scheduled, queued int
}

type workspace struct {
	cards                       []card
	all                         []row
	schools                     int
	scheduledCost               int64
	scheduled, pending, overdue []row
}

func schoolOrCluster(t target) (name, code string) {
	switch {
	case t.hasSchool:
		return t.schoolName, t.code
	case t.hasCluster:
		return t.clusterName, ""
	}
	return unassigned, ""
}

// place is _partner_location_label (and the hand-over's twin): the school's
// district and cluster, or the cluster the work is for.
func place(t target) string {
	if t.hasSchool {
		district := "—"
		if t.hasDistrict {
			district = t.district
		}
		cluster := "Unclustered"
		switch {
		case t.hasCluster:
			cluster = t.clusterName
		case t.clusterOfSchool != "":
			cluster = t.clusterOfSchool
		}
		return district + " / " + cluster
	}
	if t.hasCluster {
		return t.clusterName
	}
	return "—"
}

// myPlanURL is _my_plan_activity_url: the week holding the planned day.
func myPlanURL(a activity) string {
	if a.planned == nil {
		return "/my-plan"
	}
	d := *a.planned
	return fmt.Sprintf("/my-plan?fy=%s&month=%d&week=%d&period=week", a.fy, int(d.Month()), min(5, (d.Day()-1)/7+1))
}

func keyOf(partnerID string, t target, kind string, d *time.Time) string {
	ref := t.schoolID
	if ref == "" {
		ref = t.clusterID
	}
	when := ""
	if d != nil {
		when = d.Format(time.DateOnly)
	}
	return partnerID + "\x00" + ref + "\x00" + kind + "\x00" + when
}

func activityRow(a activity, today day) row {
	name, code := schoolOrCluster(a.target)
	var when *day
	switch {
	case a.planned != nil:
		d := civil(*a.planned)
		when = &d
	case a.scheduled != nil:
		d := civil(a.scheduled.In(zone))
		when = &d
	}
	complete := slices.Contains(rules.CompleteStatuses, a.status)
	overdue := when != nil && when.before(today) && !complete
	status := "Awaiting schedule"
	switch {
	case complete:
		status = "Completed"
	case overdue:
		status = "Overdue"
	case when != nil:
		status = "Scheduled"
	}
	tone := map[string]string{"Completed": "success", "Overdue": "danger", "Scheduled": "info"}[status]
	if tone == "" {
		tone = "warning"
	}
	focus := generalFocus
	if label := focusDisplay(a.focus); label != "" {
		focus = label
	}
	return row{
		partnerID: a.partnerID, school: name, code: code, place: place(a.target),
		purpose: purposeLabel(a.purpose, activityLabel(a.activityType)), focus: focus,
		date: when, status: status, tone: tone, cost: a.cost, costPending: a.costMissing,
		detail: myPlanURL(a), overdue: overdue,
	}
}

func assignmentRow(a assignment, today day) row {
	name, code := schoolOrCluster(a.target)
	var when *day
	if a.scheduled != nil {
		d := civil(*a.scheduled)
		when = &d
	}
	overdue := when != nil && when.before(today)
	status, tone := "Yet to schedule", "warning"
	if overdue {
		status, tone = "Overdue", "danger"
	}
	fallback := "Partner support"
	if a.expected != "" {
		fallback = pyTitle(strings.ReplaceAll(a.expected, "_", " "))
	}
	focus := generalFocus
	if label := interventionLabel(a.focus); label != "" {
		focus = label
	}
	return row{
		partnerID: a.partnerID, school: name, code: code, place: place(a.target),
		purpose: purposeLabel(a.purpose, fallback), focus: focus,
		date: when, status: status, tone: tone, costPending: true,
		detail: "/partners/" + a.partnerID, pending: true, overdue: overdue,
	}
}

// build is _partner_workspace's cards and totals.
func build(partners []partner, activities []activity, assignments []assignment, f filters, today day) workspace {
	byPartnerActs := map[string][]activity{}
	keys := map[string]bool{}
	for _, a := range activities {
		byPartnerActs[a.partnerID] = append(byPartnerActs[a.partnerID], a)
		keys[keyOf(a.partnerID, a.target, a.activityType, a.planned)] = true
	}
	byPartnerAsg := map[string][]assignment{}
	for _, a := range assignments {
		byPartnerAsg[a.partnerID] = append(byPartnerAsg[a.partnerID], a)
	}
	w := workspace{}
	for _, pa := range partners {
		rows := []row{}
		for _, a := range byPartnerActs[pa.id] {
			rows = append(rows, activityRow(a, today))
		}
		for _, a := range byPartnerAsg[pa.id] {
			kind := a.expected
			if kind == "" {
				kind = "school_visit"
			}
			if a.scheduled != nil && keys[keyOf(pa.id, a.target, kind, a.scheduled)] {
				continue
			}
			rows = append(rows, assignmentRow(a, today))
		}
		if f.status != "" {
			kept := []row{}
			for _, r := range rows {
				if strings.ReplaceAll(strings.ToLower(r.status), " ", "_") == f.status {
					kept = append(kept, r)
				}
			}
			if len(kept) == 0 {
				continue
			}
			rows = kept
		}
		sort.SliceStable(rows, func(i, j int) bool {
			a, b := rows[i].date, rows[j].date
			if (a == nil) != (b == nil) {
				return b == nil
			}
			return a != nil && a.before(*b)
		})
		c := card{p: pa, rows: rows}
		schools := map[string]bool{}
		for _, a := range byPartnerAsg[pa.id] {
			if a.hasSchool {
				schools[a.schoolID] = true
			}
		}
		for _, a := range byPartnerActs[pa.id] {
			if a.hasSchool {
				schools[a.schoolID] = true
			}
		}
		c.schools = len(schools)
		for i := range rows {
			rows[i].partnerName = pa.name
			if rows[i].pending {
				c.queued++
			} else {
				c.scheduled++
			}
		}
		w.cards = append(w.cards, c)
		w.all = append(w.all, rows...)
	}
	for _, r := range w.all {
		if r.pending {
			w.pending = append(w.pending, r)
		} else {
			w.scheduled = append(w.scheduled, r)
			w.scheduledCost += r.cost
		}
		if r.overdue {
			w.overdue = append(w.overdue, r)
		}
	}
	schools := map[string]bool{}
	for _, a := range assignments {
		if a.hasSchool {
			schools[a.schoolID] = true
		}
	}
	for _, a := range activities {
		if a.hasSchool {
			schools[a.schoolID] = true
		}
	}
	w.schools = len(schools)
	return w
}

// share is round(part / total * 100), Python's round (half to even).
func share(part, total int) int {
	if total == 0 {
		return 0
	}
	return int(math.RoundToEven(float64(part) / float64(total) * 100))
}

type view struct {
	w         workspace
	f         filters
	fyOptions []string
	partners  []partner
	role      string
	today     day
}

func header() *screensv1.PageHeader {
	return &screensv1.PageHeader{Title: title, Description: description}
}

func (v view) blocks() []*screensv1.PageBlock {
	page := feeddom.El("div", "partner-workspace")
	page.Add(feeddom.PreBlock(v.filters()), feeddom.PreBlock(v.strip()), v.groups())
	page.Add(v.aside()...)
	return feeddom.Walk(page, nil)
}

func (v view) filters() *screensv1.PageBlock {
	years := &screensv1.PageFilter{Name: "fy", Label: "Financial Year", Value: v.f.fy}
	for _, fy := range v.fyOptions {
		years.Options = append(years.Options, &screensv1.PageFilterOption{Value: fy, Label: "FY " + fy})
	}
	partners := &screensv1.PageFilter{Name: "partner", Label: "Partner", Value: v.f.partner,
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All Partners"}}}
	for _, pa := range v.partners {
		partners.Options = append(partners.Options, &screensv1.PageFilterOption{Value: pa.id, Label: strings.Join(strings.Fields(pa.name), " ")})
	}
	status := &screensv1.PageFilter{Name: "status", Label: "Activity status", Caption: "Status", Value: v.f.status,
		Options: []*screensv1.PageFilterOption{
			{Value: "", Label: "All Statuses"}, {Value: "scheduled", Label: "Scheduled"},
			{Value: "yet_to_schedule", Label: "Yet to Schedule"}, {Value: "overdue", Label: "Overdue"},
		}}
	// A chosen value no option holds reads as the first option's.
	for _, f := range []*screensv1.PageFilter{years, partners, status} {
		if !slices.ContainsFunc(f.Options, func(o *screensv1.PageFilterOption) bool { return o.Value == f.Value }) && len(f.Options) > 0 {
			f.Value = f.Options[0].Value
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{years, partners, status},
	}}}
}

// metric is one tile as components/context_metrics.html draws it: the
// helper cut to its figure (the sentence kept as the note), its tone only
// where a helper is shown.
func metric(key, value, helper, tone string) *screensv1.PageMetric {
	m := &screensv1.PageMetric{Label: rules.KPILabels[key], Value: value}
	brief := schoolprofile.BriefHelper(helper)
	m.Helper = brief
	if brief != helper {
		m.Note = helper
	}
	if brief != "" {
		m.Tone = tone
	}
	return m
}

func ugx(n int64) string { return "UGX " + intcomma(n) }

func (v view) strip() *screensv1.PageBlock {
	w := v.w
	total := len(w.scheduled) + len(w.pending)
	late, lateTone := "No late work", "success"
	if len(w.overdue) > 0 {
		late, lateTone = "Needs attention", "danger"
	}
	metrics := []*screensv1.PageMetric{
		metric("partner_total_partners", intcomma(int64(len(w.cards))), "In this view", "neutral"),
		metric("partner_assigned_schools", intcomma(int64(w.schools)), "Across all partners", "info"),
		metric("partner_scheduled_activities", intcomma(int64(len(w.scheduled))), fmt.Sprintf("%d%% of work", share(len(w.scheduled), total)), "success"),
		metric("partner_activities_yet_to_schedule", intcomma(int64(len(w.pending))), fmt.Sprintf("%d%% need a date", share(len(w.pending), total)), "warning"),
		metric("partner_scheduled_activity_cost", schoolprofile.CompactMoney(ugx(w.scheduledCost)), "Scheduled work", "neutral"),
		metric("partner_high_risk_delays", intcomma(int64(len(w.overdue))), late, lateTone),
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: stripTitle, Metrics: metrics}}}
}

// avatarInitials is frontend_filters.avatar_initials.
func avatarInitials(name string) string {
	parts := strings.Fields(name)
	switch {
	case len(parts) >= 2:
		return strings.ToUpper(string([]rune(parts[0])[:1]) + string([]rune(parts[len(parts)-1])[:1]))
	case len(parts) == 1:
		r := []rune(parts[0])
		return strings.ToUpper(string(r[:min(2, len(r))]))
	}
	return "ED"
}

func (v view) partnerLink(name, id string) any {
	if name == "" {
		return ""
	}
	if id == "" || !mayOpen("partners", v.role) {
		return name
	}
	return feeddom.El("a", "profile-link", name).Attr("href", "/partners/"+url.PathEscape(id))
}

func (v view) schoolLink(name, ref string) any {
	if name == "" || strings.TrimSpace(ref) == "" || !mayOpen("schools", v.role) {
		return name
	}
	return feeddom.El("a", "school-link", name).Attr("href", "/schools/"+url.PathEscape(strings.TrimSpace(ref)))
}

// interventions is the card's Linked SSA Interventions: every one the
// organisation is recorded for (capabilities.describe), else its label.
func (p partner) interventionWords() string {
	stored := p.interventions
	if len(stored) == 0 && p.intervention != "" {
		stored = []string{p.intervention}
	}
	if len(stored) == 0 {
		return p.ssaLabel()
	}
	words := make([]string, len(stored))
	for i, key := range stored {
		label, ok := rules.Interventions[key]
		if !ok {
			label, ok = rules.CapabilityGroups[key]
		}
		if !ok {
			label = pyTitle(strings.ReplaceAll(key, "_", " "))
		}
		words[i] = label
	}
	return strings.Join(words, ", ")
}

// ssaLabel is Partner.ssa_intervention_label.
func (p partner) ssaLabel() string {
	if p.intervention == "" {
		return generalSSA
	}
	if label, ok := rules.Interventions[p.intervention]; ok {
		return label
	}
	return pyTitle(strings.ReplaceAll(p.intervention, "_", " "))
}

func (p partner) regionLabel() string {
	regions := p.regions
	if len(regions) == 0 && p.region != "" {
		regions = []string{p.region}
	}
	return strings.Join(regions, ", ")
}

func orDefault(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}

func (v view) cardNode(c card) *feeddom.Node {
	p := c.p
	el := feeddom.El
	role := rules.PartnerRoles[p.role]
	if role == "" {
		role = p.role
	}
	linked := el("dd", "font-semibold", p.interventionWords())
	if n := len(p.activityCodes); n > 0 {
		word := "activities"
		if n == 1 {
			word = "activity"
		}
		linked.Add(el("small", "", fmt.Sprintf("%d %s", n, word)))
	}
	head := el("header", "partner-activity-card__header",
		el("div", "partner-identity",
			el("span", "partner-identity__mark", avatarInitials(p.name)),
			el("div", "",
				el("div", "flex items-center gap-2",
					el("h2", "", v.partnerLink(p.name, p.id)),
					el("span", "inline-flex rounded-pill bg-sky-50 text-sky-700", p.ssaLabel()),
				),
				el("p", "", el("svg", ""), orDefault(p.regionLabel(), "Region not set")),
			),
		),
		el("dl", "partner-activity-card__summary",
			el("div", "", el("dt", "", "Contact Person"), el("dd", "", el("span", "", orDefault(p.contact, "Not recorded")), " ", el("small", "", orDefault(p.phone, "Phone not recorded")))),
			el("div", "", el("dt", "", "Assigned Schools"), el("dd", "", fmt.Sprint(c.schools))),
			el("div", "", el("dt", "", "Scheduled"), el("dd", "", fmt.Sprint(c.scheduled))),
			el("div", "", el("dt", "", "Pending"), el("dd", "", fmt.Sprint(c.queued))),
			el("div", "", el("dt", "", "Partner role"), el("dd", "font-semibold", role)),
			el("div", "", el("dt", "", "Linked SSA Interventions"), linked),
		),
	)
	article := el("article", "partner-activity-card", head)
	if len(c.rows) == 0 {
		return article.Add(el("div", "partner-activity-card__empty", noRows))
	}
	return article.Add(el("div", "partner-activity-card__table-wrap", feeddom.PreBlock(v.table(c.rows))))
}

func (v view) table(rows []row) *screensv1.PageBlock {
	labels := []string{"School ID", "School", "District / Cluster", "Purpose of Visit", "Intervention Focus", "Scheduled Date / Status", "Cost", ""}
	t := &screensv1.PageTable{}
	for _, l := range labels {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: l})
	}
	for _, r := range rows {
		status := r.status
		if r.date != nil {
			status = r.date.t.Format("02 Jan 2006") + " · " + r.status
		}
		cost := ugx(r.cost)
		if r.costPending {
			cost = "Set when scheduled"
		}
		school := &screensv1.PageCell{Text: r.school, Strong: true}
		if link, ok := v.schoolLink(r.school, r.code).(*feeddom.Node); ok {
			school.Href = link.Get("href")
		}
		action := "View plan"
		if r.pending {
			action = "Review"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: orDefault(r.code, "—")},
			school,
			{Text: r.place},
			{Text: r.purpose},
			{Text: r.focus},
			{Text: status},
			{Text: cost},
			{Actions: []*screensv1.PageAction{{Key: "button", Label: action, Primary: true, Enabled: true, Href: r.detail}}},
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func (v view) groups() *feeddom.Node {
	section := feeddom.El("section", "partner-activity-groups")
	if len(v.w.cards) == 0 {
		return section.Add(feeddom.El("section", "partner-empty-state",
			feeddom.El("svg", ""), feeddom.El("h2", "", noCardsTitle), feeddom.El("p", "", noCardsHint)))
	}
	for _, c := range v.w.cards {
		section.Add(v.cardNode(c))
	}
	return section
}

func (v view) aside() []any {
	el := feeddom.El
	w := v.w
	chart := &screensv1.PageChart{
		Horizontal: true,
		Categories: []string{"Scheduled", "Yet to schedule", "Overdue"},
		Series:     []*screensv1.PageSeries{{Values: []float64{float64(len(w.scheduled)), float64(len(w.pending)), float64(len(w.overdue))}}},
	}
	breakdown := el("section", "partner-aside-card", el("h2", "", "Scheduling Status Breakdown"),
		el("div", "partner-status-breakdown", feeddom.PreBlock(&screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: chart}})))

	reminders := el("ul", "partner-reminder-list")
	for _, r := range w.pending[:min(listedPending, len(w.pending))] {
		when := "No date"
		if r.date != nil {
			when = r.date.t.Format("02 Jan")
		}
		reminders.Add(el("li", "",
			el("span", "partner-reminder-list__avatar", avatarInitials(r.partnerName)),
			el("div", "",
				el("strong", "", v.partnerLink(r.partnerName, r.partnerID)),
				el("p", "", v.schoolLink(r.school, r.code), " · "+r.purpose)),
			el("time", "", when)))
	}
	if len(w.pending) == 0 {
		reminders.Add(el("li", "partner-aside-card__blank", noPending))
	}
	pending := el("section", "partner-aside-card",
		el("div", "partner-aside-card__heading", el("h2", "", "Pending Partner Reminders"), el("span", "", fmt.Sprint(min(listedPending, len(w.pending))))),
		reminders,
		el("a", "partner-aside-card__link", "Review pending work ", el("span", "", "→")).Attr("href", "#partner-activity-filters"))

	upcoming := []row{}
	for _, r := range w.scheduled {
		if r.date != nil && !r.date.before(v.today) {
			upcoming = append(upcoming, r)
		}
	}
	sort.SliceStable(upcoming, func(i, j int) bool { return upcoming[i].date.before(*upcoming[j].date) })
	coming := el("ul", "partner-upcoming-list")
	for _, r := range upcoming[:min(listedComing, len(upcoming))] {
		coming.Add(el("li", "",
			el("time", "", el("b", "", r.date.t.Format("Jan")), el("strong", "", r.date.t.Format("02"))),
			el("div", "",
				el("strong", "", v.schoolLink(r.school, r.code)),
				el("p", "", r.purpose+" · ", v.partnerLink(r.partnerName, r.partnerID)))))
	}
	if len(upcoming) == 0 {
		coming.Add(el("li", "partner-aside-card__blank", noUpcoming))
	}
	next := el("section", "partner-aside-card",
		el("div", "partner-aside-card__heading", el("h2", "", "Upcoming Partner Activities"), el("svg", "")),
		coming,
		el("a", "partner-aside-card__link", "View full calendar ", el("span", "", "→")).Attr("href", "/calendar"))

	actions := el("section", "partner-aside-card partner-aside-card--actions",
		el("h2", "", "Quick Actions"),
		el("a", "btn-premium-primary", el("svg", ""), "Open Planning").Attr("href", "/planning"),
		el("a", "btn-premium-secondary", el("svg", ""), "Open Assigned Schools").Attr("href", "/schools"))
	return []any{el("aside", "partner-workspace__aside", breakdown, pending, next, actions)}
}
