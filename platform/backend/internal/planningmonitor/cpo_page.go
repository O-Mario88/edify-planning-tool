package planningmonitor

import (
	"net/url"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// cpoPath is the page (COUNTRY_OVERSIGHT_PATH).
const cpoPath = "/country-planning-oversight/"

// cpoFmt is service._fmt: thousands separated.
func cpoFmt(n int) string {
	s := strconv.Itoa(max(n, -n))
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if n < 0 {
		s = "-" + s
	}
	return s
}

// cpoFYLabel is coverage.fy_label: "2027" → "FY 2026/27".
func cpoFYLabel(fy string) string {
	n, err := strconv.Atoi(fy)
	if err != nil {
		return "FY " + fy
	}
	return "FY " + strconv.Itoa(n-1) + "/" + fy[len(fy)-2:]
}

var cpoMonths = []string{"", "January", "February", "March", "April", "May", "June", "July", "August", "September",
	"October", "November", "December"}

// label is Window.label.
func (w cpoWindow) label() string {
	switch w.period {
	case "quarter":
		return w.quarter + " · " + cpoFYLabel(w.fy)
	case "month":
		return cpoMonths[w.month] + " " + strconv.Itoa(w.start.Year())
	case "week":
		return "Week of " + strconv.Itoa(w.start.Day()) + " " + w.start.Month().String()[:3] + " " + strconv.Itoa(w.start.Year())
	}
	return cpoFYLabel(w.fy)
}

// query is Filters.query: the period, then each school filter set, in order.
func (f cpoFilters) query(overrides map[string]string) string {
	type kv struct{ k, v string }
	values := map[string]string{"fy": f.fy, "period": f.period, "quarter": f.quarter, "week": f.week, "region": f.region,
		"district": f.district, "program_lead": f.programLead, "cceo": f.cceo, "school_type": f.schoolType, "channel": f.channel,
		"partner": f.partner, "cluster_status": f.clusterStatus, "planning_status": f.planningStatus}
	if f.month > 0 {
		values["month"] = strconv.Itoa(f.month)
	}
	for k, v := range overrides {
		values[k] = v
	}
	out := []kv{{"fy", values["fy"]}, {"period", values["period"]}}
	switch values["period"] {
	case "quarter":
		if values["quarter"] != "" {
			out = append(out, kv{"quarter", values["quarter"]})
		}
	case "month":
		if values["month"] != "" {
			out = append(out, kv{"month", values["month"]})
		}
	case "week":
		if values["week"] != "" {
			out = append(out, kv{"week", values["week"]})
		}
	}
	for _, name := range []string{"region", "district", "program_lead", "cceo", "school_type", "channel", "partner", "cluster_status",
		"planning_status"} {
		if values[name] != "" {
			out = append(out, kv{name, values[name]})
		}
	}
	parts := make([]string, 0, len(out))
	for _, p := range out {
		parts = append(parts, url.QueryEscape(p.k)+"="+url.QueryEscape(p.v))
	}
	return strings.Join(parts, "&")
}

// cpoTally reads a vector by name, with the shares the page shows.
type cpoTally []int

func (t cpoTally) n(name string) int { return t[cpoIdx[name]] }
func (t cpoTally) planned() int      { return t.n("staff") + t.n("partner_scheduled") }
func (t cpoTally) partnerToPlan() int {
	return t.n("no_visit") - t.n("unplanned")
}
func (t cpoTally) planRemaining() int  { return max(0, t.n("target")-t.n("p_visits")) }
func (t cpoTally) partnerWaiting() int { return max(0, t.n("pa_work")-t.n("pp_work")) }

func pct(part, whole int) string {
	s, ok := share(part, whole)
	if !ok {
		return "—"
	}
	return strconv.Itoa(s) + "%"
}

func paren(part, whole int) string { return "(" + pct(part, whole) + ")" }

// lensTabs is country_lens_tabs("coverage") as the feed reads the strip.
func cpoLensTabs() *screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{}
	for _, t := range rules.CountryOversight.Page.LensTabs {
		tabs = append(tabs, &screensv1.PageLinkTab{Label: t[2], Href: t[3], Active: t[0] == "coverage"})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}}
}

type cpoOption struct{ value, label string }

func filterOf(name, label, caption, value string, options []cpoOption) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label, Caption: caption}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: o.label})
	}
	// A select names its chosen option, else (the browser) its first.
	f.Value = value
	found := false
	for _, o := range options {
		if o.value == value {
			found = true
		}
	}
	if !found && len(options) > 0 {
		f.Value = options[0].value
	}
	return f
}

// cpoPageOptions are _filter_options: what each select offers.
type cpoPageOptions struct {
	years                        []string
	regions, districts, partners []cpoOption
	leads, owners                []cpoOption
}

func pairs(ps [][2]string) []cpoOption {
	out := []cpoOption{}
	for _, p := range ps {
		out = append(out, cpoOption{p[0], p[1]})
	}
	return out
}

// cpoFilters is the control card (page.html's form) as the feed reads it.
func cpoFilterBlock(f cpoFilters, o cpoPageOptions) *screensv1.PageBlock {
	page := rules.CountryOversight.Page
	years := []cpoOption{}
	for _, y := range o.years {
		years = append(years, cpoOption{y, cpoFYLabel(y)})
	}
	months := []cpoOption{}
	for _, m := range []int{10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9} {
		months = append(months, cpoOption{strconv.Itoa(m), cpoMonths[m]})
	}
	month := ""
	if f.month > 0 {
		month = strconv.Itoa(f.month)
	}
	with := func(first string, rest []cpoOption) []cpoOption { return append([]cpoOption{{"", first}}, rest...) }
	leads := with("All Program Leads", o.leads)
	leads = append(leads, cpoOption{rules.CountryOversight.NoLead[0], "No Programme Lead"})
	filters := []*screensv1.PageFilter{
		filterOf("fy", "", "Financial Year", f.fy, years),
		filterOf("period", "", "", f.period, []cpoOption{{"fy", "Full Year"}, {"quarter", "Quarter"}, {"month", "Month"}, {"week", "Week"}}),
		filterOf("quarter", "Quarter", "", f.quarter, []cpoOption{{"Q1", "Q1 · Oct–Dec"}, {"Q2", "Q2 · Jan–Mar"}, {"Q3", "Q3 · Apr–Jun"},
			{"Q4", "Q4 · Jul–Sep"}}),
		filterOf("month", "Month", "", month, months),
		filterOf("region", "", "Region", f.region, with("All Regions", o.regions)),
		filterOf("program_lead", "", "Program Lead", f.programLead, leads),
		filterOf("cceo", "", "CCEO", f.cceo, with("All CCEOs", o.owners)),
		filterOf("partner", "", "Partner", f.partner, with("All Partners", o.partners)),
		filterOf("planning_status", "", "Planning Status", f.planningStatus, with("All", pairs(page.StatusOptions))),
		filterOf("district", "", "District", f.district, with("All Districts", o.districts)),
		filterOf("school_type", "", "School Type", f.schoolType, with("All Types", pairs(page.TypeOptions))),
		filterOf("channel", "", "Delivery Channel", f.channel, with("Staff and Partner", pairs(page.ChannelOptions))),
		filterOf("cluster_status", "", "Cluster Status", f.clusterStatus, with("All", pairs(page.ClusterOptions))),
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters}}}
}

func textPanel(text string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: text}}}}}}
}

func pluralize(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// cpoNotices is the workspace's notices: the period's, and the schools of a
// type the rules do not know.
func cpoNotices(snap *cpoSnapshot) []*screensv1.PageBlock {
	w := snap.tree.window
	out := []*screensv1.PageBlock{}
	if !w.isAnnual() {
		if w.hasPhasedTarget() {
			out = append(out, textPanel(w.label()+": planned work dated in the period, against the approved phasing of the annual "+
				"requirement (Q1 20% · Q2 30% · Q3 30% · Q4 20%). Each card also reads the year to date."))
		} else {
			out = append(out, textPanel(w.label()+": there is no approved weekly phasing, so each card reads the year to date "+
				"against the annual requirement, and names the week's own planning beside it."))
		}
	}
	if n := cpoTally(snap.tree.country).n("unmapped_schools"); n > 0 {
		out = append(out, textPanel(strconv.Itoa(n)+" school"+pluralize(n, "", "s")+" "+pluralize(n, "has", "have")+
			" a type the planning rules do not know and "+pluralize(n, "is", "are")+
			" outside every figure until the product owner decides where "+pluralize(n, "it belongs", "they belong")+"."))
	}
	return out
}

// headcount is service.headcount: the Leads and CCEOs whose rows carry a
// ceiling.
func (snap *cpoSnapshot) headcount() (int, int) {
	leads, cceos := 0, 0
	for _, l := range snap.tree.leads {
		for _, o := range l.owners {
			if o.ceiling == 0 {
				continue
			}
			switch o.kind {
			case "pl_personal":
				leads++
			case "cceo":
				cceos++
			}
		}
	}
	return leads, cceos
}

// cpoCards is service.kpis as workspace.html's cards read: each card's
// label, and its figures and lines after it.
func cpoCards(snap *cpoSnapshot) *screensv1.PageBlock {
	page := rules.CountryOversight.Page
	t := cpoTally(snap.tree.country)
	w := snap.tree.window
	phased, week := w.hasPhasedTarget(), w.period == "week"
	leads, cceos := snap.headcount()
	note := ""
	switch {
	case phased:
		note = "Phased target for " + w.label()
	case week:
		note = "Year to date against the annual requirement"
	}
	visitPart, trainingPart := t.planned(), t.n("training")
	if week {
		visitPart = t.n("cum_staff") + t.n("cum_partner_scheduled")
		trainingPart = t.n("cum_training")
	}
	ceilings := rules.CountryOversight.StaffCeilings
	type card struct {
		key         string
		part, whole int
		headline    [2]string
		note        string
		extras      []string
	}
	keep := func(xs ...string) []string {
		out := []string{}
		for _, x := range xs {
			if x != "" {
				out = append(out, x)
			}
		}
		return out
	}
	when := func(ok bool, s string) string {
		if ok {
			return s
		}
		return ""
	}
	partnerPart := t.n("partner_scheduled")
	if week {
		partnerPart = t.n("cum_partner_scheduled")
	}
	meetingNote := note
	if phased || week {
		meetingNote = ""
	}
	cards := []card{
		{"cpo_staff_visit_planning", t.n("p_visits"), t.n("target"), [2]string{cpoFmt(t.planRemaining()), "visits still to plan"}, note,
			keep(cpoFmt(cceos) + " CCEOs × " + strconv.Itoa(ceilings[rules.CCEORole]) + " + " + cpoFmt(leads) + " Leads × " +
				strconv.Itoa(ceilings[rules.ProgramLeadRole]))},
		{"cpo_partner_planning", partnerPart, t.n("partner_expected"), [2]string{cpoFmt(t.n("pa_schools")), "Schools assigned to Partners"}, note,
			keep(cpoFmt(t.n("core_partner_slots"))+" Core + "+cpoFmt(t.n("client_partner_expected"))+" beyond staff capacity",
				cpoFmt(t.n("pa_work"))+" assigned · "+cpoFmt(t.partnerWaiting())+" awaiting the Partner's date")},
		{"cpo_total_visit_coverage", visitPart, t.n("visit_slots"), [2]string{cpoFmt(t.n("any_visit")), "Schools with a visit planned"}, note,
			keep(cpoFmt(t.n("unplanned"))+" schools not yet planned",
				when(t.partnerToPlan() > 0, cpoFmt(t.partnerToPlan())+" awaiting a Partner's date"),
				cpoFmt(max(0, t.n("visit_slots")-visitPart))+" visits remaining",
				when(t.n("duplicates") > 0, cpoFmt(t.n("duplicates"))+" planned twice"))},
		{"cpo_training_planning", trainingPart, t.n("training_slots"), [2]string{cpoFmt(t.n("any_training")), "Schools with training planned"}, note,
			keep(cpoFmt(t.n("no_training"))+" schools not yet planned", cpoFmt(t.n("training_gap"))+" slots remaining")},
		{"cpo_cluster_membership", t.n("clustered"), t.n("schools"), [2]string{cpoFmt(t.n("unclustered")), "Unclustered schools"}, "", nil},
		{"cpo_cluster_meeting_planning", t.n("meeting_covered_clustered"), t.n("clustered"),
			[2]string{cpoFmt(t.n("p_meetings")), "Cluster meetings planned by staff"}, meetingNote,
			keep(cpoFmt(t.n("clustered_no_meeting")) + " clustered schools on no planned meeting")},
	}
	q := snap.filters.query(nil)
	links := &screensv1.PageLinks{}
	for _, c := range cards {
		caption := []string{cpoFmt(c.part) + " / " + cpoFmt(c.whole) + " " + pct(c.part, c.whole), c.headline[0] + " " + c.headline[1]}
		if len(c.extras) > 0 {
			caption = append(caption, strings.Join(c.extras, " · "))
		}
		if c.note != "" {
			caption = append(caption, c.note)
		}
		links.Links = append(links.Links, &screensv1.PageLink{Text: page.KPILabels[c.key], Caption: strings.Join(caption, " · "),
			Href: cpoPath + "table/" + page.KPITables[c.key] + "?" + q})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: links}}}}}}
}

// cpoChips is a tab list (data-edify-tablist) as the feed reads it.
func cpoChips(label string, views [][2]string) *screensv1.PageBlock {
	chips := []*screensv1.PageChip{}
	for _, v := range views {
		chips = append(chips, &screensv1.PageChip{Value: v[0], Label: v[1]})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chips{Chips: &screensv1.PageChips{Name: "view", Label: label, Chips: chips}}}
}

// figureLink is _figure_link.html: a figure opening the table or the monitor
// list behind it; a zero is plain.
func figureLink(text, query, kind, table, list string) *feeddom.Node {
	return scopedFigure(text, query, kind, table, list, "all=1", "")
}

// scopedFigure is _figure_link.html: a figure that opens the table (or the
// Planning Monitor list) behind it for the row's scope; a zero, or a row
// drawn without a scope, keeps its plain figure.
func scopedFigure(text, query, kind, table, list, scope, people string) *feeddom.Node {
	if scope == "" || text == "0" {
		return feeddom.El("span", "", text)
	}
	href := ""
	if list != "" {
		href = cpoPath + "?" + query + "&view=monitor&gap=" + list
		if people != "" {
			href += "&" + people
		}
		if kind != "" {
			href += "&school_type=" + kind
		}
		href += "#monitor-list"
	} else {
		href = cpoPath + "table/" + table + "?" + query + "&" + scope
		if kind != "" {
			href += "&school_type=" + kind
		}
	}
	return feeddom.El("a", "cpo-link", text).Attr("href", href)
}

func sortedOptions(names map[string]string) []cpoOption {
	out := []cpoOption{}
	for k, v := range names {
		out = append(out, cpoOption{k, v})
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].label != out[j].label {
			return out[i].label < out[j].label
		}
		return out[i].value < out[j].value
	})
	return out
}
