package leaveapprovals

import (
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: closedschools.Collapse(t)}}
}

func heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: closedschools.Collapse(t)}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

// initials is |slice:":2"|upper.
func initials(name string) string {
	r := []rune(name)
	return strings.ToUpper(string(r[:min(2, len(r))]))
}

// title is |title on words split by spaces and underscores made spaces.
func title(s string) string {
	words := strings.Fields(strings.ReplaceAll(s, "_", " "))
	for i, w := range words {
		words[i] = strings.ToUpper(w[:1]) + strings.ToLower(w[1:])
	}
	return strings.Join(words, " ")
}

// pyTitle is str.title(): a letter after a non-letter starts a word.
func pyTitle(s string) string {
	var b strings.Builder
	prev := false
	for _, r := range s {
		letter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case letter && !prev:
			b.WriteString(strings.ToUpper(string(r)))
		case letter:
			b.WriteString(strings.ToLower(string(r)))
		default:
			b.WriteRune(r)
		}
		prev = letter
	}
	return b.String()
}

// apMonth is |date:"N": the Associated Press month.
func apMonth(t time.Time) string {
	return [...]string{"Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."}[t.Month()-1]
}

func charged(n *int) string {
	if n == nil {
		return "None"
	}
	return strconv.Itoa(*n)
}

func country(c *string) string {
	if c == nil {
		return "None"
	}
	return *c
}

// selectValue is what the feed reads from a select: the chosen option, or
// with none chosen the first.
func selectValue(value string, options [][2]string) string {
	for _, o := range options {
		if o[0] == value {
			return value
		}
	}
	return options[0][0]
}

// metric is a registry tile: a line that starts with a figure stays the
// line under the figure; any other is the tile's note.
func metric(label string, value int, helper string) *screensv1.PageMetric {
	m := &screensv1.PageMetric{Label: label, Value: strconv.Itoa(value)}
	if brief := schoolprofile.BriefHelper(helper); brief != "" {
		m.Helper = brief
	} else {
		m.Note = helper
	}
	return m
}

func (f figures) strip() *screensv1.PageBlock {
	delta := f.approved - f.previous
	approved := "Same as previous 7 days"
	switch {
	case delta > 0:
		approved = strconv.Itoa(delta) + " more than previous 7 days"
	case delta < 0:
		approved = strconv.Itoa(-delta) + " fewer than previous 7 days"
	}
	covered := "No pending requests"
	if f.pending > 0 {
		covered = strconv.Itoa(pyRound(float64(f.covered)/float64(f.pending)*100)) + "% of pending requests"
	}
	l := rules.MetricLabels
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Leave and coverage context", Metrics: []*screensv1.PageMetric{
		metric(l[0], f.pending, "Authorized requests awaiting a decision"),
		metric(l[1], f.approved, approved),
		metric(l[2], f.covered, covered),
		metric(l[3], f.conflicts, "Detected in the pending queue"),
		metric(l[4], f.away, "Approved leave overlapping this week"),
		metric(l[5], f.alerts, "PTO balances below five days"),
	}}}}
}

// pyRound is round(): halves to even.
func pyRound(x float64) int {
	f := float64(int(x))
	switch diff := x - f; {
	case diff > 0.5, diff == 0.5 && int(f)%2 == 1:
		return int(f) + 1
	}
	return int(f)
}

// page is pages/leave/leave_approvals.html as the feed reads it.
func page(strip *decisionlog.Strip, q, kind, status string, f figures, queue []leave, chosen *selected,
	holidays []calendarpage.Holiday, recent []decision, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Time & Availability", Title: "Leave Approvals",
		Description: "Review leave requests, approve coverage, manage conflicts, and keep team operations running."}
	typeFilter := &screensv1.PageFilter{Name: "type", Label: "Type", Value: selectValue(kind, append([][2]string{{"", ""}}, typeOptions...)),
		Options: []*screensv1.PageFilterOption{{Label: "All Leave Types"}}}
	for _, o := range typeOptions {
		typeFilter.Options = append(typeFilter.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
	}
	shown := status
	if shown == "" {
		shown = defaultStatus
	}
	statusFilter := &screensv1.PageFilter{Name: "status", Label: "Status", Value: selectValue(shown, statusOptions)}
	for _, o := range statusOptions {
		statusFilter.Options = append(statusFilter.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{typeFilter, statusFilter}}}}}
	if strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: strip.Label, Scrolls: strip.Scrolls}
		for _, t := range strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	blocks = append(blocks, f.strip())
	resp := &screensv1.GetPageResponse{Header: header, WebPath: Path}
	if len(queue) == 0 {
		// The empty queue's card, with nothing chosen beside it, reads as one
		// empty table under the queue's heading.
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: "Approval Queue (0)", Subtitle: "All Caught Up No leave requests awaiting approval.",
			EmptyMessage: "No leave requests awaiting approval."}}})
		blocks = append(blocks, panel("Recent Approval Activity", text("Latest 10 decisions")))
		resp.Blocks = append(blocks, recentTable(recent, query)...)
		return resp
	}
	blocks = append(blocks, panel("Approval Queue ("+strconv.Itoa(len(queue))+")", text("Sort: Oldest First")))
	items := []*screensv1.PagePanelItem{}
	for _, l := range queue {
		items = append(items, text(initials(l.staffName)), text(l.staffName), text(l.status), text(l.staffRole+" · "+country(l.staffCountry)),
			text(title(l.kind)), text(tail(l.start)+" → "+tail(l.end)), text("Days: "+charged(l.charged)+" working"))
	}
	blocks = append(blocks, panel("", items...), detail(*chosen))
	blocks = append(blocks, sideCards(*chosen, holidays)...)
	resp.Dialogs = dialogs(*chosen)
	blocks = append(blocks, panel("Recent Approval Activity", text("Latest 10 decisions")))
	blocks = append(blocks, recentTable(recent, query)...)
	resp.Blocks = blocks
	return resp
}

// tail is |slice:"5:".
func tail(s string) string {
	r := []rune(s)
	return string(r[min(5, len(r)):])
}

// detail is the Leave Request Details card.
func detail(c selected) *screensv1.PageBlock {
	l, im := c.leave, c.impact
	balance := "Not available"
	if im.remaining != nil {
		balance = strconv.Itoa(*im.remaining) + " / " + strconv.Itoa(*im.entitlement) + " days"
	}
	reason := l.reason
	if reason == "" {
		reason = "No description notes provided."
	}
	items := []*screensv1.PagePanelItem{text(initials(l.staffName)), heading(l.staffName), text(l.staffRole + " · " + l.staffEmail),
		text(title(l.kind)), text(strings.ToUpper(l.status)),
		text("Start Date"), text(l.start), text("End Date"), text(l.end), text("Working Days"), text(charged(l.charged) + " days"),
		text("Remaining Balance"), text(balance), text("Reason / Notes"), text(reason), text("Coverage Assignee")}
	if l.coverID != "" {
		items = append(items, text(initials(l.coverName)), text(l.coverName), text(l.coverRole))
	} else {
		items = append(items, text("No coverage assignee proposed."))
	}
	if len(c.cover) > 0 {
		items = append(items, text("Change Assignee"))
	}
	items = append(items, text("Auto-Access Transfer"), text("Will Transfer"), text("Will Transfer"), text("Will Transfer"), text("Will Transfer"),
		text("Conflict Check Summary"), text("Holiday Overlap Check"), text("Blackout Overlap Check"), text("Activities Impacted"),
		text("Team Capacity Safe"), text("Affected Work Items"),
		// Each count is read beside the label before it.
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
			{Label: "Live impact analysis", Value: strconv.Itoa(im.activities)}, {Label: "Activities", Value: strconv.Itoa(im.planning)},
			{Label: "Plan Items", Value: strconv.Itoa(im.partner)}, {Label: "Partner Work", Value: strconv.Itoa(im.funds)},
			{Label: "Fund Requests", Value: strconv.Itoa(im.due)}}}}},
		text("My Plan Due"))
	if l.status == "pending" {
		items = append(items, text("Return for Clarification"), text("Reject"))
	}
	return panel("Leave Request Details", items...)
}

// sideCards is the right-hand column: holidays, conflicts, availability, the
// rules and the request's trail.
func sideCards(c selected, holidays []calendarpage.Holiday) []*screensv1.PageBlock {
	days := []*screensv1.PagePanelItem{heading("Holiday & Blackout Dates"), text("Next 5")}
	for _, h := range holidays {
		days = append(days, text(h.Label), text(apMonth(h.Date)+" "+strconv.Itoa(h.Date.Day())+", "+strconv.Itoa(h.Date.Year())))
	}
	if len(holidays) == 0 {
		days = append(days, text("No upcoming public holidays."))
	}
	found := []*screensv1.PagePanelItem{heading("Auto-Blocked Conflicts"), text("Live check")}
	for _, x := range c.conflicts {
		// The conflict's kind sits beside a dot the feed does not read.
		found = append(found, text(x.action), text(x.dates))
	}
	if len(c.conflicts) == 0 {
		found = append(found, text("No conflicts detected for this period."))
	}
	team := []*screensv1.PagePanelItem{heading("Team Availability"), links(&screensv1.PageLink{Text: "Full report", Href: "/leave/team-availability"}),
		text("Staff"), text("Wk 1"), text("Wk 2"), text("Wk 3")}
	people := []*screensv1.PageLink{}
	for _, r := range c.heat[:min(heatPeople, len(c.heat))] {
		people = append(people, &screensv1.PageLink{Text: r.Name, Href: "/staff/" + r.StaffID})
	}
	if len(people) > 0 {
		team = append(team, links(people...))
	} else {
		team = append(team, text("No availability data mapped."))
	}
	ruleLinks := []*screensv1.PageLink{}
	for _, r := range []string{"Count only working days (weekends skipped).", "Coverage must be within matching scope under supervising PL.",
		"Access delegation terminates automatically when leave ends.", "Leave category disabled when annual balance is exhausted.",
		"Conflicts must be reviewed prior to authorization."} {
		ruleLinks = append(ruleLinks, &screensv1.PageLink{Text: r})
	}
	l := c.leave
	review := "Awaiting authorized review"
	if l.status != "pending" {
		review = title(l.status)
	}
	created := l.created.In(zone)
	trail := []*screensv1.PagePanelItem{heading("Audit Trail"), text("Request Submitted"),
		text(created.Format("Jan 2, 2006") + " at " + created.Format("3:04 PM") + " by " + l.staffName),
		text("Under Review"), text(review)}
	if l.coverID != "" {
		trail = append(trail, text("Coverage Action"), text("Status: "+l.coverageStatus))
	}
	return []*screensv1.PageBlock{panel("", days...), panel("", found...), panel("", team...),
		panel("", heading("Approval Rules Check"), links(ruleLinks...)), panel("", trail...)}
}

// dialogs is the request's three forms: change the cover (when anyone may
// cover), send back, reject.
func dialogs(c selected) []*screensv1.PageDialog {
	l := c.leave
	field := func(f *screensv1.DrawerField) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
	}
	form := func(key, title, intro, submit string, fields ...*screensv1.PageFormItem) *screensv1.PageDialog {
		return &screensv1.PageDialog{Key: key, Title: title, Blocks: []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
			Text: intro, Items: fields, SubmitLabel: submit, Key: "/leave/approvals/" + l.id + "/" + strings.ToLower(strings.Fields(submit)[0])}}}}}
	}
	out := []*screensv1.PageDialog{}
	if len(c.cover) > 0 {
		options := []*screensv1.DrawerOption{{Label: "No coverage / Clear coverage"}}
		value := ""
		for _, x := range c.cover {
			options = append(options, &screensv1.DrawerOption{Value: x.id, Label: closedschools.Collapse(x.name + " (" + x.role + ")")})
			if x.id == l.coverID {
				value = x.id
			}
		}
		d := form("coverageModal", "Reassign Coverage Assignee", "Select a qualified team backup employee to cover during this leave.", "Save Assignment",
			field(&screensv1.DrawerField{Name: "covering_staff", Label: "Coverage Candidate", Kind: "select", Value: value, Options: options}))
		d.Blocks[0].GetForm().Key = "/leave/approvals/" + l.id + "/reassign"
		out = append(out, d)
	}
	ret := form("returnModal", "Return Leave for Clarification", "Provide details/reasons on what corrections are needed.", "Send Back",
		field(&screensv1.DrawerField{Name: "reason", Label: "Feedback / Reason", Kind: "textarea", Required: true,
			Placeholder: "Describe what handover details or dates are required..."}))
	ret.Blocks[0].GetForm().Key = "/leave/approvals/" + l.id + "/return"
	rej := form("rejectModal", "Reject Leave Request", "Please describe the reasons for rejecting this request.", "Reject Request",
		field(&screensv1.DrawerField{Name: "reason", Label: "Rejection Reason", Kind: "textarea", Required: true,
			Placeholder: "Describe conflict reasons, capacity shortages, etc..."}))
	rej.Blocks[0].GetForm().Key = "/leave/approvals/" + l.id + "/reject"
	return append(out, ret, rej)
}

// recentTable is the Recent Approval Activity table and its pager.
func recentTable(recent []decision, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, c := range []string{"Date & Time", "Staff Profile", "Action", "Leave Type", "Dates", "Duration", "Reviewed By"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	number, pages := closedschools.PageOf(query.Get("recent_activity_page"), len(recent), rules.PageSize)
	for _, d := range recent[(number-1)*rules.PageSize : min(number*rules.PageSize, len(recent))] {
		at := ""
		if d.at != nil {
			l := d.at.In(zone)
			at = apMonth(l) + " " + strconv.Itoa(l.Day()) + ", " + strconv.Itoa(l.Year()) + " " + l.Format("15:04")
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: at}, {Text: closedschools.Collapse(d.staff)}, {Text: pyTitle(d.status), Tone: "primary", Badge: true},
			{Text: pyTitle(strings.ReplaceAll(d.kind, "_", " "))}, {Text: d.start + " → " + d.end}, {Text: strconv.Itoa(d.days) + " days"},
			{Text: closedschools.Collapse(d.by)},
		}})
	}
	if len(recent) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No recent activity logs."}}}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("recent_activity_page", number, pages, len(recent), rules.PageSize, query, nil))
	}
	return blocks
}
