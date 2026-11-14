package partneroversight

import (
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// Words the templates hold.
const (
	eyebrow     = "Supervision"
	title       = "Partner Monitoring"
	description = "One Partner at a time: the schools, clusters and activities handed to it, by team member, and where each stands."
	tilesTitle  = "Partner planning context"
	allMembers  = "All team members"
	emptyWork   = "When a school's support is handed to a Partner it appears here — first waiting on the Partner's date, then through delivery, IA verification and payment."

	registerTitle      = "Partner engagements this FY"
	registerTilesTitle = "Partner engagement at a glance"
	recordedEmpty      = "No partner engagements recorded"
	recordedHint       = "Record a review meeting, an orientation on Edify's CCE framework or a training quality follow-up once it has happened."
	readerEmpty        = "No partner engagements to show"
	readerHint         = "Engagements a Programme Lead or the Country Director records with this partner appear here."
)

var monthNames = []string{"January", "February", "March", "April", "May", "June", "July",
	"August", "September", "October", "November", "December"}

var quarterOptions = [][2]string{{"Q1", "Q1 · Oct–Dec"}, {"Q2", "Q2 · Jan–Mar"}, {"Q3", "Q3 · Apr–Jun"}, {"Q4", "Q4 · Jul–Sep"}}

// page is pages/oversight/partner_oversight.html with an empty workspace as
// the feed reads it.
func page(w workspace) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: description}
	if w.role.CreatePartner {
		header.Actions = []*screensv1.PageAction{{
			Key: "add_partner_organisation", Label: "Add Partner Organisation",
			Enabled: true, Href: "/partners/create", Drawer: true,
		}}
	}
	blocks := []*screensv1.PageBlock{filters(w), memberTabs(w), tiles(w),
		{Kind: &screensv1.PageBlock_Empty{Empty: emptyWork}}}
	if w.role.EngagementRegister {
		blocks = append(blocks, register(w)...)
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

// filters is period_filter_bar.html with partner_filter_fields.html: the
// period select carries no selected option (Alpine sets it), so the feed
// reads its first.
func filters(w workspace) *screensv1.PageBlock {
	options := func(pairs [][2]string) []*screensv1.PageFilterOption {
		out := make([]*screensv1.PageFilterOption, len(pairs))
		for i, p := range pairs {
			out[i] = &screensv1.PageFilterOption{Value: p[0], Label: p[1]}
		}
		return out
	}
	chosen := func(pairs [][2]string, value string) string {
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
	periods := [][2]string{{"week", "Week"}, {"month", "Month"}, {"quarter", "Quarter"}, {"fy", "Financial year"}}
	years := [][2]string{}
	for _, fy := range w.fyOptions {
		years = append(years, [2]string{fy, "FY " + fy})
	}
	months := [][2]string{}
	for i, name := range monthNames {
		months = append(months, [2]string{strconv.Itoa(i + 1), name})
	}
	statuses := [][2]string{{"", "All statuses"}}
	for _, key := range rules.StatusFilterKeys {
		statuses = append(statuses, [2]string{key, title_(key) + " (0)"})
	}
	hidden := map[string]string{"member": w.member, "work": w.work}
	if w.programLead != "" {
		hidden["program_lead"] = w.programLead
	}
	// Each select's caption is the short word partials/oversight/
	// period_filter_bar.html draws beside it, which the feed reads
	// (_filter_caption) when it differs from the select's name: Month's
	// "Month" does not.
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			{Name: "period", Label: "Time period", Value: chosen(periods, w.period.kind), Options: options(periods), Caption: "View"},
			{Name: "fy", Label: "Financial year", Value: chosen(years, w.period.fy), Options: options(years), Caption: "FY"},
			{Name: "month", Label: "Month", Value: chosen(months, strconv.Itoa(w.period.month)), Options: options(months)},
			{Name: "quarter", Label: "Financial quarter", Value: chosen(quarterOptions, w.period.quarter), Options: options(quarterOptions), Caption: "Quarter"},
			{Name: "status", Label: "Status", Value: chosen(statuses, w.status), Options: options(statuses)},
		},
		Hidden: hidden,
	}}}
}

// memberTabs is the Team members strip: everyone on the reader's team with
// the work each holds (none here).
func memberTabs(w workspace) *screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{w.memberTab("all", allMembers)}
	for _, m := range w.members {
		tabs = append(tabs, w.memberTab(m.key, m.name))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs, Scrolls: true}}}
}

func (w workspace) memberTab(key, label string) *screensv1.PageLinkTab {
	p := w.period
	href := "?program_lead=" + w.programLead + "&partner=&member=" + key + "&work=" + w.work +
		"&period=" + p.kind + "&fy=" + p.fy + "&month=" + strconv.Itoa(p.month) + "&quarter=" + p.quarter + "&week=" + p.week
	return &screensv1.PageLinkTab{Label: label + " 0", Href: href, Active: key == w.member}
}

// tiles is _partner_kpis over no partner work, with the Partner target
// when the reader's Planning Monitor has people (all of its totals zero).
func tiles(w workspace) *screensv1.PageBlock {
	from := rules.ZeroTiles
	if w.withTarget {
		from = rules.ZeroTilesWithTarget
	}
	metrics := make([]*screensv1.PageMetric, len(from))
	for i, t := range from {
		metrics[i] = &screensv1.PageMetric{Label: t.Label, Value: t.Value, Helper: t.Helper, Note: t.Note, Tone: t.Tone}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: tilesTitle, Metrics: metrics}}}
}

// register is partials/partners/engagement_register.html with no
// engagements: its title, its tiles (each a sentence, so the line under the
// figure is the note) and the empty table.
func register(w workspace) []*screensv1.PageBlock {
	keys := []string{"recorded", "partners_engaged", "follow_ups_due"}
	if w.role.ObservationsTile {
		keys = append(keys, "observations")
	}
	figures := []schoolprofile.StripFigure{}
	for _, key := range keys {
		words := rules.EngagementMetricWords[key]
		figures = append(figures, schoolprofile.StripFigure{
			Label: words[0], Value: "0", Helper: strings.ReplaceAll(words[1], "{fy}", w.period.fy),
		})
	}
	message, hint := readerEmpty, readerHint
	if w.role.RecordsEngagements {
		message, hint = recordedEmpty, recordedHint
	}
	table := &screensv1.PageTable{
		Rows:         []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: message + " " + hint}}}},
		EmptyMessage: message,
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: registerTitle}}},
		schoolprofile.Strip(registerTilesTitle, figures),
		{Kind: &screensv1.PageBlock_Table{Table: table}},
	}
}

// title_ is |replace_underscore|title: words split at underscores, each
// with its first letter capital and the rest small.
func title_(key string) string {
	words := strings.Fields(strings.ReplaceAll(key, "_", " "))
	for i, word := range words {
		words[i] = strings.ToUpper(word[:1]) + strings.ToLower(word[1:])
	}
	return strings.Join(words, " ")
}
