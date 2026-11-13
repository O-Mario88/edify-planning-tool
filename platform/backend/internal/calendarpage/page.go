package calendarpage

import (
	"regexp"
	"strings"
	"time"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The page as the feed reads pages/calendar/index.html and its partials
// (apps.mobile_feed.page_blocks): the header, the workspace strip, the
// people strip, the day-off notice, the event composer, the filter bar and
// the event-type rail, whose five tabs each hold the same two panels (the
// phone's month and agenda, and the month itself), each read as
// page_blocks._panel_items reads loose parts: a line of text, a heading, a
// link joining the links just before it, and a label line followed by a
// figure paired into a data row.

// view is everything one answer draws.
type view struct {
	year            int
	mon             time.Month
	today           time.Time
	agenda          bool
	m               *month
	person          *person
	teamTabs        []tab
	memberTabs      []tab
	hidden          map[string]string
	kind, status    string
	eventKind       string
	filtersActive   bool
	leave, addEvent bool
	strip           *Strip
	picks           int
}

// tab is one link of the people strip and the number its calendar draws.
type tab struct {
	label, href string
	count       int
}

type items []*screensv1.PagePanelItem

func (it *items) text(s string) {
	if s = collapse(s); s != "" {
		*it = append(*it, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}})
	}
}

func (it *items) heading(s string) {
	*it = append(*it, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: collapse(s)}})
}

// link is _panel_items' link branch: a link joins the list just before it.
func (it *items) link(link *screensv1.PageLink) {
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

// list is _panel_items' ul/ol branch: always a list of its own.
func (it *items) list(links []*screensv1.PageLink) {
	*it = append(*it, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})
}

// linkItem is page_blocks._link_item for a link whose child elements say
// lines (each already read) and whose whole text is whole.
func linkItem(lines []string, whole, href string) *screensv1.PageLink {
	kept := []string{}
	for _, l := range lines {
		if l = collapse(l); l != "" {
			kept = append(kept, l)
		}
	}
	if len(kept) > 1 {
		return &screensv1.PageLink{Text: kept[0], Href: href, Caption: strings.Join(kept[1:], " · ")}
	}
	return &screensv1.PageLink{Text: collapse(whole), Href: href}
}

// figure is page_blocks.FIGURE: a figure on its own.
var figure = regexp.MustCompile(`^(?:—|[-+−]?(?:UGX\s+)?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB])?(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?)$`)

var pagerCaption = regexp.MustCompile(`^Showing\s+\d`)

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
			strings.IndexFunc(item.GetText(), unicode.IsLetter) < 0 || !figure.MatchString(strip(after.GetText())) {
			out = append(out, item)
			continue
		}
		row := &screensv1.PageDataRow{Label: item.GetText(), Value: strip(after.GetText()), Tone: after.GetTone()}
		if n := len(out); n > 0 && out[n-1].GetRows() != nil {
			out[n-1].GetRows().Rows = append(out[n-1].GetRows().Rows, row)
		} else {
			out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{row}}}})
		}
		i++
	}
	return out
}

func panel(title, subtitle string, it items) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: collapse(title), Subtitle: collapse(subtitle), Items: paired(it)}}}
}

func (v *view) monthName() string { return v.mon.String() }

// chip is partials/calendar/event.html in the month grid: a tick box beside
// its link, a link, or plain words.
func chip(it *items, e event) {
	title, meta := collapse(e.title), collapse(e.meta)
	switch {
	case e.href != "" && e.pick:
		it.link(linkItem([]string{title, meta}, e.title+e.meta, e.href))
	case e.href != "":
		it.link(linkItem([]string{e.title + e.meta}, e.title+e.meta, e.href))
	default:
		it.text(title)
		it.text(meta)
	}
}

// agendaLink is _list_link of one day of partials/calendar/agenda.html: the
// day's first link (a chip with a tick box always holds one), or the whole
// day's words when it holds none.
func (v *view) agendaLink(d time.Time) *screensv1.PageLink {
	events := v.m.days[d]
	for _, e := range events {
		if e.pick || e.href != "" {
			return &screensv1.PageLink{Text: collapse(e.title + e.meta), Href: e.href}
		}
	}
	words := []string{longDay(d)}
	if d.Equal(v.today) {
		words = append(words, "Today")
	}
	for _, e := range events {
		words = append(words, e.title+e.meta)
	}
	return &screensv1.PageLink{Text: collapse(strings.Join(words, " "))}
}

// agendaItems is partials/calendar/agenda.html outside the phone's panel.
func (v *view) agendaItems(it *items) {
	days := v.m.agendaDays()
	if len(days) == 0 {
		suffix := ""
		if v.filtersActive {
			suffix = " for the selected filters"
		}
		it.text("No events in " + v.monthName() + " " + itoa(v.year) + suffix + ".")
		return
	}
	links := []*screensv1.PageLink{}
	for _, d := range days {
		links = append(links, v.agendaLink(d))
	}
	it.list(links)
}

// mobilePanel is the phone's month (section.calendar-mobile).
func (v *view) mobilePanel() *screensv1.PageBlock {
	it := items{}
	it.text("Today")
	for _, w := range rules.WeekdayLabels {
		it.text(string([]rune(w)[:1]))
	}
	for d := v.m.start; !d.After(v.m.end); d = d.AddDate(0, 0, 1) {
		it.text(itoa(d.Day()))
	}
	it.heading("")
	if v.picks > 0 {
		it.text("Select all")
	}
	it.text("All month")
	if days := v.m.agendaDays(); len(days) > 0 {
		links := []*screensv1.PageLink{}
		for _, d := range days {
			links = append(links, v.agendaLink(d))
		}
		it.list(links)
		it.text("No matching events for this date and event type.")
	}
	subtitle := "Your schedule"
	if v.person != nil {
		subtitle = v.person.name
	}
	return panel(v.monthName()+" "+itoa(v.year), subtitle, it)
}

// monthPanel is the month itself (section.calendar-month).
func (v *view) monthPanel() *screensv1.PageBlock {
	it := items{}
	it.text(strings.ToUpper(v.monthName()[:3]))
	it.text("01")
	if v.picks > 0 {
		it.text("Select all")
	}
	it.text("Today")
	if !v.agenda {
		for _, w := range rules.WeekdayLabels {
			it.text(w)
		}
		for d := v.m.start; !d.After(v.m.end); d = d.AddDate(0, 0, 1) {
			it.text(itoa(d.Day()))
			if d.Equal(v.today) {
				it.text("Today")
			}
			for _, e := range v.m.days[d] {
				chip(&it, e)
			}
		}
	}
	v.agendaItems(&it)
	it.text("Leave, holidays, and organization events are overlays and never count as activities. Organization events block new visits and trainings.")
	subtitle := v.monthName() + " 1, " + itoa(v.year) + " – " + v.monthName() + " " + itoa(v.m.end.Day()) + ", " + itoa(v.year)
	return panel(v.monthName()+" "+itoa(v.year), subtitle, it)
}

func pluralize(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// dayOffPanel is the notice above the month (section.calendar-dayoff): its
// heading and line; its list sits inside the heading's part and is not read.
func (v *view) dayOffPanel() *screensv1.PageBlock {
	n := len(v.m.dayOff)
	noun := "activit" + pluralize(n, "y", "ies")
	if v.person != nil {
		return panel(v.person.name+" has "+itoa(n)+" "+noun+" to reschedule in "+v.monthName(),
			pluralize(n, "It is", "They are")+" planned on a public holiday or on a day "+v.person.name+" is on leave.", nil)
	}
	return panel("Reschedule "+itoa(n)+" "+noun+" in "+v.monthName(),
		pluralize(n, "It is", "They are")+" planned on a public holiday or on a day the responsible person is on leave. Open an activity and choose Reschedule.", nil)
}

// peoplePanel is the strips that choose whose calendar is open: one list of
// links, each with the count its calendar draws.
func (v *view) peoplePanel() *screensv1.PageBlock {
	it := items{}
	for _, t := range append(append([]tab{}, v.teamTabs...), v.memberTabs...) {
		it.link(linkItem([]string{t.label, itoa(t.count)}, t.label+" "+itoa(t.count), t.href))
	}
	return panel("", "", it)
}

func (v *view) filters() *screensv1.PageBlock {
	types := []*screensv1.PageFilterOption{{Value: "", Label: "All types"}}
	for _, c := range rules.ActivityTypes {
		types = append(types, &screensv1.PageFilterOption{Value: c[0], Label: collapse(c[1])})
	}
	statuses := []*screensv1.PageFilterOption{{Value: "", Label: "All statuses"}}
	for _, c := range rules.StatusOptions {
		statuses = append(statuses, &screensv1.PageFilterOption{Value: c[0], Label: collapse(c[1])})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			{Name: "activity_type", Label: "Activity type", Value: v.kind, Options: types},
			{Name: "status", Label: "Status", Value: v.status, Options: statuses},
		},
		Hidden: v.hidden,
	}}}
}

// rail is the event-type tab list: five tabs over the one part they all
// control, so each holds the same two panels.
func (v *view) rail() *screensv1.PageBlock {
	parts := func() []*screensv1.PageBlock { return []*screensv1.PageBlock{v.mobilePanel(), v.monthPanel()} }
	segments := []*screensv1.PageSegment{}
	for _, t := range kindTabs {
		segments = append(segments, &screensv1.PageSegment{Label: t.label + itoa(v.kindCount(t.key)), Blocks: parts()})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: &screensv1.PageSegments{
		Caption: "Operations calendar", Segments: segments}}}
}

func header(leave bool) *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow:     "Operations calendar",
		Title:       "Calendar",
		Description: "See scheduled work, approved leave, organization events, and important holidays in one place.",
	}
	if leave {
		h.Actions = []*screensv1.PageAction{{Key: "apply_for_leave", Label: "Apply for Leave", Enabled: true, Href: "/personal-time-off"}}
	}
	return h
}

func (v *view) page() *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if v.strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: v.strip.Label, Scrolls: v.strip.Scrolls}
		for _, t := range v.strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	if len(v.teamTabs) > 0 {
		blocks = append(blocks, v.peoplePanel())
	}
	if len(v.m.dayOff) > 0 {
		blocks = append(blocks, v.dayOffPanel())
	}
	if v.addEvent && v.person == nil {
		it := items{}
		it.heading("Add other event")
		blocks = append(blocks, panel("Add an organization event", "Country calendar", it))
	}
	blocks = append(blocks, v.filters(), v.rail(), v.calendar())
	out := &screensv1.GetPageResponse{
		Header:  header(v.leave && v.person == nil),
		Blocks:  blocks,
		WebPath: Path,
	}
	if v.picks > 0 {
		out.Selection = &screensv1.PageSelection{Noun: "activities selected", Actions: []*screensv1.PageSelectionAction{
			{Label: "Reschedule", Href: "/activity-selection/reschedule", Param: "ids", Joined: true},
			{Label: "Cancel", Href: "/activity-selection/cancel", Param: "ids", Joined: true},
		}}
	}
	return out
}
