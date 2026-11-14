package staffactivity

import (
	"fmt"
	"regexp"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The page's words, as its templates write them
// (templates/pages/staff_activity/index.html and
// templates/partials/staff_activity/).
const (
	pageTitle        = "Staff Activity Log"
	countryDesc      = "How staff across the country use the platform: active time, the parts they use, and the meaningful work they complete."
	stripTitle       = "Staff activity at a glance"
	tableTitle       = "Staff by Program Lead"
	nobody           = "Nobody matches these filters."
	insightsTitle    = "Team Insights"
	onlineNote       = "Online is not proof of work; it means a recent active beat."
	noActiveTime     = "No active time in this period."
	noSignins        = "No sign-ins in this period."
	pickedNote       = "Select a staff member to see their sign-in history, time by module, meaningful actions and period trend."
	followUpQueue    = "Follow-up Queue"
	followUpQueueURL = "/staff-activity/follow-ups"
)

var columns = []string{
	"Status", "Staff", "Role", "Supervisor", "Region", "Logins", "First Active", "Last Active", "Active Time",
	"Actions", "Schools", "Last Page", "Last Meaningful Action", "Usage", "Follow-up", "",
}

var notSlug = regexp.MustCompile(`[^a-z0-9]+`)

// slug is page_blocks._slug, a header button's key.
func slug(text string) string { return strings.Trim(notSlug.ReplaceAllString(pyLower(text), "_"), "_") }

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

func block(kind any) *screensv1.PageBlock {
	switch k := kind.(type) {
	case *screensv1.PagePanel:
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: k}}
	case *screensv1.PageTable:
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: k}}
	case *screensv1.PageFilters:
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: k}}
	}
	panic(fmt.Sprintf("staffactivity: no block for %T", kind))
}

func heading(text string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: text}}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func links(texts []string) *screensv1.PagePanelItem {
	l := make([]*screensv1.PageLink, len(texts))
	for i, t := range texts {
		l[i] = &screensv1.PageLink{Text: t}
	}
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: l}}}
}

// stripBlock is _kpi_items drawn by components/context_metrics.html: the
// line under a figure is cut to its figure, its sentence kept as the note,
// and a figure carries its tone only where a line is shown.
func stripBlock(k kpis) *screensv1.PageBlock {
	activeHelper := "nobody expected"
	if k.activeShare != nil {
		activeHelper = fmt.Sprintf("%d%% of expected", *k.activeShare)
	}
	noLoginTone := "success"
	if k.noLogin > 0 {
		noLoginTone = "danger"
	}
	suggested := "none suggested"
	if k.suggested > 0 {
		suggested = fmt.Sprintf("%d more suggested", k.suggested)
	}
	followTone := "success"
	if k.openFollowUps > 0 || k.suggested > 0 {
		followTone = "warning"
	}
	figures := []schoolprofile.StripFigure{
		{Label: "Staff Expected", Value: fmt.Sprint(k.expected), Helper: fmt.Sprintf("of %d listed", k.total)},
		{Label: "Staff Active", Value: fmt.Sprint(k.active), Helper: activeHelper},
		{Label: "No Login", Value: fmt.Sprint(k.noLogin), Helper: "expected, but did not sign in"},
		{Label: "Total Active Time", Value: k.totalLabel, Helper: "deduplicated across tabs and devices"},
		{Label: "Median Active Time", Value: k.medianLabel, Helper: "per active staff member"},
		{Label: "Meaningful Actions", Value: fmt.Sprint(k.actions), Helper: fmt.Sprintf("%d school%s acted on", k.schools, plural(k.schools))},
		{Label: "Open Follow-ups", Value: fmt.Sprint(k.openFollowUps), Helper: suggested},
	}
	tones := []string{"info", "success", noLoginTone, "info", "info", "success", followTone}
	b := schoolprofile.Strip(stripTitle, figures)
	for i, m := range b.GetStrip().GetMetrics() {
		if m.GetHelper() != "" {
			m.Tone = tones[i]
		}
	}
	return b
}

func filtersBlock(l *theLog) *screensv1.PageBlock {
	out := []*screensv1.PageFilter{}
	pick := func(name, title, all string, options [][2]string, chosen string) {
		f := &screensv1.PageFilter{Name: name, Label: title, Options: []*screensv1.PageFilterOption{{Value: "", Label: all}}}
		for _, o := range options {
			f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
			if o[0] == chosen && f.Value == "" {
				f.Value = o[0]
			}
		}
		out = append(out, f)
	}
	if len(l.roleOptions) > 1 {
		pick("role", "Role", "All roles", l.roleOptions, l.filters.role)
	}
	if len(l.leadOptions) > 0 {
		pick("pl", "Program Lead", "All PLs", l.leadOptions, l.filters.programLead)
	}
	pick("status", "Status", "All staff", rules.StatusOptions, l.filters.status)
	return block(&screensv1.PageFilters{Filters: out, Hidden: map[string]string{"period": l.period.key}})
}

func cell(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: t} }

// row is partials/staff_activity/_person_row.html as the feed reads it.
func row(x *person, l *theLog, today func(*person) (string, string, string)) *screensv1.PageRow {
	first, last, actionAt := today(x)
	actions := fmt.Sprint(x.actions)
	if x.failed > 0 {
		actions += fmt.Sprintf(" · %d failed", x.failed)
	}
	lastAction := "—"
	if x.lastAction != "" {
		lastAction = x.lastAction + " · " + actionAt
	}
	follow := "—"
	if x.openFollowUps > 0 {
		follow = fmt.Sprintf("%d open", x.openFollowUps)
	}
	status, _ := label(rules.StatusOptions, x.status)
	if status == "" {
		status = "Offline"
	}
	menu := []*screensv1.PageAction{}
	if l.canFollowUp {
		menu = append(menu, &screensv1.PageAction{
			Key: "menu", Label: "Follow up", Enabled: true, Drawer: true,
			Href: fmt.Sprintf("/staff-activity/people/%s/follow-up?period=%s&on=%s", x.id, l.period.key, l.period.on.Format("2006-01-02")),
		})
	}
	active := &screensv1.PageCell{Text: minutes(float64(x.seconds)), Strong: true}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		cell(status), cell(initials(x.name) + " " + x.name), cell(x.title), cell(orDash(x.supervisor)), cell(orDash(x.region)),
		cell(fmt.Sprint(x.logins)), cell(first), cell(last), active, cell(actions), cell(fmt.Sprint(x.schools)),
		cell(x.lastPage), cell(lastAction), cell(x.usageLabel), cell(follow), {Actions: menu},
	}}
}

// initials is services._initials.
func initials(name string) string {
	parts := []string{}
	for _, p := range strings.Fields(strings.ReplaceAll(name, "'", "")) {
		if r := []rune(p); len(r) > 0 && isAlpha(r[0]) {
			parts = append(parts, p)
		}
	}
	if len(parts) == 0 {
		return "?"
	}
	out := string([]rune(parts[0])[0])
	if len(parts) > 1 {
		out += string([]rune(parts[len(parts)-1])[0])
	}
	return strings.ToUpper(out)
}

func tableBlock(l *theLog, first *group) *screensv1.PageBlock {
	cols := make([]*screensv1.PageColumn, len(columns))
	for i, c := range columns {
		cols[i] = &screensv1.PageColumn{Label: c}
	}
	rows := []*screensv1.PageRow{}
	if first == nil {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(nobody)}})
	} else {
		head := first.label
		if first.kind == "program_lead" {
			head = "PL · " + head
		}
		head += fmt.Sprintf(" %d staff · %d online · %s active · %d action%s", first.total, first.online,
			minutes(float64(first.seconds)), first.actions, plural(first.actions))
		if first.noLogin > 0 {
			head += fmt.Sprintf(" · %d no login", first.noLogin)
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(head)}})
		labels := func(x *person) (string, string, string) {
			at := ""
			if x.lastActionAt != nil {
				at = clock(x.lastActionAt, l.today)
			}
			return clock(x.firstActive, l.today), clock(x.lastActive, l.today), at
		}
		if first.lead != nil {
			rows = append(rows, row(first.lead, l, labels))
		}
		for _, x := range first.members {
			rows = append(rows, row(x, l, labels))
		}
	}
	return block(&screensv1.PageTable{Columns: cols, Rows: rows})
}

func insightsBlock(l *theLog) *screensv1.PageBlock {
	in := l.insights
	total := in.total
	if total == 0 {
		total = 1
	}
	items := []*screensv1.PagePanelItem{heading("Online now"), text(fmt.Sprintf("%d online now", in.status[0]))}
	status := []string{}
	for i, k := range in.statusKeys {
		name, _ := label(rules.StatusOptions, k)
		status = append(status, fmt.Sprintf("%s %d (%d%%)", name, in.status[i], share(int64(in.status[i]), int64(total))))
	}
	items = append(items, links(status), text(onlineNote), heading("Active time by module"))
	if len(in.modules) > 0 {
		mods := []string{}
		for _, m := range in.modules {
			mods = append(mods, fmt.Sprintf("%s%d%%", m.label, m.share))
		}
		items = append(items, links(mods))
	} else {
		items = append(items, text(noActiveTime))
	}
	trendTitle := "Active staff a day, last 7 days"
	if !in.latest {
		trendTitle = fmt.Sprintf("Active staff a day, 7 days to %d %s", in.trendEnd.Day(), in.trendEnd.Format("Jan"))
	}
	days := []string{}
	for _, d := range in.trend {
		days = append(days, fmt.Sprintf("%d %s", d.count, d.day.Format("Mon")))
	}
	items = append(items, heading(trendTitle), links(days), heading("Sign-ins by device"))
	if in.deviceSum > 0 {
		devices := []string{}
		for i, d := range deviceKeys {
			devices = append(devices, fmt.Sprintf("%d%% %s", share(int64(in.devices[i]), int64(in.deviceSum)), d[1]))
		}
		items = append(items, links(devices))
	} else {
		items = append(items, text(noSignins))
	}
	return block(&screensv1.PagePanel{Title: insightsTitle, Subtitle: capfirst(l.period.label), Items: items})
}

// page is the log as the feed reads pages/staff_activity/index.html for a
// country reader.
func page(l *theLog, gs []*group) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Title: pageTitle, Description: countryDesc}
	if l.canFollowUp {
		label := followUpQueue
		if l.followUpCount > 0 {
			label = fmt.Sprintf("%s %d", label, l.followUpCount)
		}
		header.Actions = []*screensv1.PageAction{{Key: slug(label), Label: label, Primary: true, Enabled: true, Href: followUpQueueURL, Drawer: true}}
	}
	var first *group
	if len(gs) > 0 {
		first = gs[0]
	}
	caption := fmt.Sprintf("%d of %d staff · %s · active time excludes idle tabs (after %d minutes untouched)",
		len(l.people), l.total, capfirst(l.period.label), rules.Thresholds.IdleSeconds/60)
	return &screensv1.GetPageResponse{
		Header:  header,
		WebPath: Path,
		Blocks: []*screensv1.PageBlock{
			stripBlock(figures(l.people)),
			filtersBlock(l),
			block(&screensv1.PagePanel{Title: tableTitle, Items: []*screensv1.PagePanelItem{text(caption)}}),
			tableBlock(l, first),
			insightsBlock(l),
			block(&screensv1.PagePanel{Items: []*screensv1.PagePanelItem{text(pickedNote)}}),
		},
	}
}
