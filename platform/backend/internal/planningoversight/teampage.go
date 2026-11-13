package planningoversight

import (
	"net/url"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The words below are the templates' (pages/oversight/team_planning.html,
// partials/oversight/pl_workspace.html, period_filter_bar.html,
// _officer_panel_body.html, flagged_schools.html); the vocabularies that
// live in Python come from rules.json.
const (
	pageTitle       = "Planning Oversight"
	teamDescription = "Your team’s plans, delivery and unresolved risks."
	exportLabel     = "Export"
	exportDrawer    = "/team-planning-oversight/export-drawer"
	stripTitle      = "Team planning context"
	chartTitle      = "Planning and delivery progress by person"
	chartSubtitle   = "You and each officer you supervise · "
	schoolOversight = "School Oversight"
	evidenceGaps    = "Evidence gaps"
	evidenceHref    = "/evidence/?tab=pending"
	flaggedTitle    = "Flagged schools"
	flaggedSubtitle = "Planned this period, carrying an unresolved problem. Read-only — ask the person who owns the school."
	flaggedNone     = "No school planned this period is carrying an unresolved problem."
)

// sections are the four tables of _officer_panel_body.html: heading,
// caption, and the line each draws with no rows.
var sections = [][3]string{
	{"1. Client School Visits", "Standard support, coaching, follow-ups", "No client school visits scheduled for this officer in the selected period."},
	{"2. Core School Visits", "Core package visit slots (4/year targeted)", "No core school visits scheduled for this officer in the selected period."},
	{"3. Cluster Meetings", "Cluster leader convening and SSA reviews", "No cluster meetings scheduled for this officer in the selected period."},
	{"4. Schools with Planned Training", "In-school and group/cluster training sessions", "No schools with planned training for this officer in the selected period."},
}

var chartCategories = []string{"Planned", "Scheduled", "Completed", "Awaiting verification"}

var periodOptions = [][2]string{{"week", "Week"}, {"month", "Month"}, {"quarter", "Quarter"}, {"fy", "Financial year"}}

var quarterOptions = [][2]string{{"Q1", "Q1 · Oct–Dec"}, {"Q2", "Q2 · Jan–Mar"}, {"Q3", "Q3 · Apr–Jun"}, {"Q4", "Q4 · Jul–Sep"}}

func teamPage(w teamPlan) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{
		lensTabs(),
		teamFilters(w),
		teamStrip(),
		panel("", "", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: w.tabLinks()}}}),
		{Kind: &screensv1.PageBlock_Section{Section: tabLabel(w.tabs, w.owner)}},
		fieldPlan(w),
	}
	for _, s := range sections {
		blocks = append(blocks,
			panel("", "", heading(s[0]), text("0"), text(s[1])),
			panel("", "", text(s[2])),
		)
	}
	blocks = append(blocks, chart(w))
	var oversight []*screensv1.PagePanelItem
	if rules.TeamPlan.EvidenceLink {
		oversight = append(oversight, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: evidenceGaps, Href: evidenceHref}},
		}}})
	}
	blocks = append(blocks,
		panel(schoolOversight, "", oversight...),
		panel(flaggedTitle, flaggedSubtitle, text(flaggedNone)),
	)
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Title:       pageTitle,
			Description: teamDescription,
			Actions:     []*screensv1.PageAction{pageheader.Drawer(exportLabel, exportHref(w), false)},
		},
		Blocks:  blocks,
		WebPath: rules.Pages[teamKey].Path,
	}
}

// exportHref is _export_menu.html's drawer link as the feed gives it.
func exportHref(w teamPlan) string {
	q := url.Values{}
	q.Set("period", w.period.Kind)
	q.Set("fy", w.period.FY)
	q.Set("week", w.period.Week)
	q.Set("month", strconv.Itoa(w.period.Month))
	q.Set("quarter", w.period.Quarter)
	q.Set("owner", w.owner)
	if w.activity != allActivity {
		q.Set("activity", w.activity)
	}
	return pageheader.Href(exportDrawer, q)
}

func lensTabs() *screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{}
	for _, t := range rules.TeamPlan.LensTabs {
		tabs = append(tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}}
}

// teamFilters is period_filter_bar.html. The existing page's period select
// carries no selected option (Alpine sets it), so its feed always reads the
// first, "week"; Go shows the period in use (owner, 2026-11-13: "Can you fix
// those from the go side"; intended.json go-fix-period-select-team-plan).
func teamFilters(w teamPlan) *screensv1.PageBlock {
	years := [][2]string{}
	for _, fy := range w.fyOptions {
		years = append(years, [2]string{fy, "FY " + fy})
	}
	months := [][2]string{}
	for i, name := range monthNames {
		months = append(months, [2]string{strconv.Itoa(i + 1), name})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			{Name: "period", Label: "Time period", Value: chosen(periodOptions, w.period.Kind), Options: options(periodOptions), Caption: "View"},
			{Name: "fy", Label: "Financial year", Value: chosen(years, w.period.FY), Options: options(years), Caption: "FY"},
			{Name: "month", Label: "Month", Value: chosen(months, strconv.Itoa(w.period.Month)), Options: options(months)},
			{Name: "quarter", Label: "Financial quarter", Value: chosen(quarterOptions, w.period.Quarter), Options: options(quarterOptions), Caption: "Quarter"},
		},
		Hidden: map[string]string{"owner": w.owner},
	}}}
}

func options(pairs [][2]string) []*screensv1.PageFilterOption {
	out := make([]*screensv1.PageFilterOption, len(pairs))
	for i, p := range pairs {
		out[i] = &screensv1.PageFilterOption{Value: p[0], Label: p[1]}
	}
	return out
}

// chosen is the option a select reads: the one marked, else the first.
func chosen(pairs [][2]string, value string) string {
	for _, p := range pairs {
		if p[0] == value {
			return value
		}
	}
	if len(pairs) == 0 {
		return ""
	}
	return pairs[0][0]
}

// teamStrip is _kpi_items over no work through components/context_metrics:
// a helper line carries the tile's tone; one cut to its figure keeps the
// whole sentence as the note.
func teamStrip() *screensv1.PageBlock {
	figures := []schoolprofile.StripFigure{}
	for _, k := range rules.TeamPlan.ZeroKPIs {
		figures = append(figures, schoolprofile.StripFigure{Label: k.Label, Value: k.Value, Helper: k.Helper})
	}
	block := schoolprofile.Strip(stripTitle, figures)
	for i, m := range block.GetStrip().GetMetrics() {
		if m.Helper != "" {
			m.Tone = rules.TeamPlan.ZeroKPIs[i].Tone
		}
	}
	return block
}

// tabLinks are the people tabs then the activity tabs, each with its count
// (none here), each link keeping the other strip's choice.
func (w teamPlan) tabLinks() []*screensv1.PageLink {
	p := w.period
	rest := "&period=" + p.Kind + "&fy=" + p.FY + "&week=" + p.Week + "&month=" + strconv.Itoa(p.Month) + "&quarter=" + p.Quarter
	links := []*screensv1.PageLink{}
	for _, t := range w.tabs {
		links = append(links, &screensv1.PageLink{Text: t.Label, Href: "?owner=" + t.Key + "&activity=" + w.activity + rest, Caption: "0"})
	}
	for _, t := range rules.TeamPlan.ActivityTabs {
		links = append(links, &screensv1.PageLink{Text: t.Label, Href: "?owner=" + w.owner + "&activity=" + t.Key + rest, Caption: "0"})
	}
	return links
}

// fieldPlan is the chosen tab's header summary with nothing in it.
func fieldPlan(w teamPlan) *screensv1.PageBlock {
	return panel("", "",
		text(initials(w.panelName)),
		heading(w.panelName+" Field Plan "+w.periodLabel),
		text("0 planned activities · UGX 0"),
		text("0 planned"),
		text("0 client visits"),
		text("0 core visits"),
		text("0 meetings"),
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{
			Rows: []*screensv1.PageDataRow{{Label: "0 trainings", Value: "UGX 0"}},
		}}},
	)
}

// initials is {{ name|slice:":2"|upper }}.
func initials(name string) string {
	r := []rune(name)
	if len(r) > 2 {
		r = r[:2]
	}
	return strings.ToUpper(string(r))
}

// chart is the team_chart tag over _team_progress_rows: the reader first,
// then each officer, every figure nought.
func chart(w teamPlan) *screensv1.PageBlock {
	series := []*screensv1.PageSeries{}
	for _, t := range w.tabs {
		if t.Key == wholeTeamKey {
			continue
		}
		name := t.Label
		if t.Key == myWorkKey {
			name = w.ownLabel
		}
		series = append(series, &screensv1.PageSeries{Name: name, Values: make([]float64, len(chartCategories))})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: &screensv1.PageChart{
		Title:      chartTitle,
		Subtitle:   chartSubtitle + w.periodLabel,
		Categories: chartCategories,
		Series:     series,
	}}}
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

func text(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
}

func heading(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: s}}
}
