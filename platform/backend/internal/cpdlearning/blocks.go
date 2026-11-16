package cpdlearning

import (
	"fmt"
	"math"
	"net/url"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundworkspace"
)

// blocks is partials/hr/pd_dashboard/body.html under the page's filters, as
// the feed reads it.
func (d *dashboard) blocks() []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{d.filters(), d.strip(),
		fundworkspace.Panel("1. Staff Professional Development Tracker",
			fundworkspace.Text(fmt.Sprintf("%d request%s", d.trackerEntries, plural(d.trackerEntries)))),
		d.trackerTable(), section("2. HR Action Center")}
	out = append(out, d.actionCenter()...)
	out = append(out, d.fundBlocks()...)
	out = append(out, d.roleBlocks()...)
	out = append(out, d.charts()...)
	out = append(out, workflowPanel(), section("6. Completed Courses & HR Sign-Off Snapshot"), d.snapshot(),
		d.upcoming(), d.quickActions())
	return out
}

func section(title string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: title}}
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// money is "{currency} {cents / 100:,.0f}": whole units, a half to the even.
func money(currency string, cents int64) string {
	return currency + " " + whole(cents)
}

// whole is "{cents / 100:,.0f}" without the currency.
func whole(cents int64) string {
	text := strconv.FormatFloat(float64(cents)/100, 'f', 0, 64)
	sign := ""
	if strings.HasPrefix(text, "-") {
		sign, text = "-", text[1:]
	}
	var b strings.Builder
	for i, c := range text {
		if i > 0 && (len(text)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(c)
	}
	return sign + b.String()
}

// percent is round(part / whole * 100), or 0 for no whole.
func percent(part, of int64) int64 {
	if of == 0 {
		return 0
	}
	return int64(math.RoundToEven(float64(part) / float64(of) * 100))
}

func choiceFilter(name, lbl, caption, value, all string, pairs [][2]string) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: lbl, Caption: caption}
	f.Options = append(f.Options, &screensv1.PageFilterOption{Value: "", Label: all})
	for _, pair := range pairs {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: pair[0], Label: pair[1]})
		if pair[0] == value {
			f.Value = value
		}
	}
	return f
}

func (d *dashboard) filters() *screensv1.PageBlock {
	fy := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: d.fy, Caption: "Financial Year"}
	for _, y := range d.years {
		fy.Options = append(fy.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	filters := []*screensv1.PageFilter{fy}
	if d.locked == "" {
		pairs := [][2]string{}
		for _, c := range d.countries {
			pairs = append(pairs, [2]string{c, c})
		}
		filters = append(filters, choiceFilter("country", "Country", "", d.country, "All Countries", pairs))
	}
	filters = append(filters,
		choiceFilter("role", "Role", "", d.ask.role, "All Roles", rules.EligibleRoles),
		choiceFilter("status", "Status", "Course Status", d.status, "All Statuses", rules.StatusBuckets),
		choiceFilter("reminder", "Reminder", "Reminder Status", d.reminder, "Any", rules.Reminders))
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters}}}
}

func (d *dashboard) strip() *screensv1.PageBlock {
	var progress, pendingCert, pendingAcct, signOff int
	staff := map[string]bool{}
	for _, r := range d.rows {
		staff[r.staffID] = true
		switch {
		case in(rules.InProgressStatuses, r.status):
			progress++
		case in(rules.PendingCertificateStatuses, r.status):
			pendingCert++
		}
		if pendingAccountability(r) {
			pendingAcct++
		}
		if r.status == statusAwaitingHR {
			signOff++
		}
	}
	year := "FY " + d.fy
	values := []string{money(d.currency, d.totalCents), money(d.currency, d.committed), money(d.currency, d.accounted),
		strconv.Itoa(len(staff)), strconv.Itoa(progress), strconv.Itoa(pendingCert), strconv.Itoa(pendingAcct), strconv.Itoa(signOff)}
	helpers := []string{year, fmt.Sprintf("%d%% of allocation", percent(d.committed, d.totalCents)),
		fmt.Sprintf("%d%% of allocation", percent(d.accounted, d.totalCents)), year, "Active now",
		"Course ended, no certificate yet", "Funded, not yet cleared", "Ready for review"}
	return fundworkspace.Strip("Professional development context", rules.MetricLabels, values, helpers)
}

func cell(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: text} }

// staffCell is the staff_link tag: the name, opening the person's profile
// for a reader who may, then the lines under it.
func (d *dashboard) staffCell(name, staffID, sep, under string) *screensv1.PageCell {
	c := cell(strings.Join(strings.Fields(name), " "))
	if under != "" {
		c.Text += sep + under
	}
	if d.role.StaffLinks && name != "" && strings.TrimSpace(staffID) != "" {
		c.Href = "/staff/" + url.PathEscape(strings.TrimSpace(staffID))
	}
	return c
}

func table(columns []string, numeric map[int]bool, rows []*screensv1.PageRow, empty string) *screensv1.PageBlock {
	t := &screensv1.PageTable{Rows: rows}
	for i, c := range columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: numeric[i]})
	}
	if len(rows) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{cell(empty)}}}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func date(t interface{ Format(string) string }) string { return t.Format("02 Jan 2006") }

func (d *dashboard) trackerTable() *screensv1.PageBlock {
	rows := []*screensv1.PageRow{}
	for _, t := range d.tracker {
		role := t.position
		if role == "" {
			role = "—"
		}
		supervisor := t.supervisor
		if supervisor == "" {
			supervisor = "—"
		}
		certificate := "Pending"
		if !in(rules.NotStartedStatuses, t.status) && !in(rules.InProgressStatuses, t.status) && !in(rules.PendingCertificateStatuses, t.status) {
			certificate = "Uploaded"
		}
		accountability := "Pending"
		switch {
		case !in(rules.FundedTypes, t.funding):
			accountability = "N/A"
		case t.acctReviewed != nil:
			accountability = "Cleared"
		case t.acctSubmitted != nil:
			accountability = "Submitted"
		}
		signOff := "—"
		switch t.status {
		case statusClosed:
			signOff = "Signed Off"
		case statusAwaitingHR:
			signOff = "Pending"
		}
		reminder := map[string]string{"overdue": "Overdue", "due": "Due Soon"}[t.tag]
		if reminder == "" {
			reminder = "—"
		}
		next := rules.NextActions[t.status]
		if next == "" {
			next = "—"
		}
		funds := fmt.Sprintf("%s Used %s Balance %s of %s", money(t.currency, t.requested), money(t.currency, t.accounted),
			money(t.staffCurrency, t.staffBalance), money(t.staffCurrency, t.staffCents))
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			d.staffCell(t.staffName, t.staffID, " ", role), cell(supervisor),
			cell(t.course + " " + label(rules.CourseTypes, t.courseType)),
			cell(date(t.start) + " – " + date(t.end)), cell(funds),
			{Text: label(rules.Statuses, t.status), Tone: "primary", Badge: true},
			cell(certificate), cell(accountability), cell(signOff), cell(reminder), cell(next),
		}})
	}
	return table([]string{"Staff", "Supervisor", "Course", "Dates", "Funds (Req. / Used / Balance)", "Status",
		"Certificate", "Accountability", "Sign-Off", "Reminder", "Next Action"}, map[int]bool{4: true}, rows,
		"No Professional Development requests match these filters.")
}

// dueLabel is _due_label.
func (d *dashboard) dueLabel(r request, key string) string {
	switch {
	case key == "not_started":
		if days(d.today, r.start) >= 0 {
			return "Start by " + date(r.start)
		}
		return "Was due " + date(r.start)
	case key == "in_progress":
		return "Due " + date(r.end)
	case key == "pending_certificate":
		return "Ended " + date(r.end)
	case key == "ready_signoff" && r.markedComplete != nil:
		return "Completed on " + date(r.markedComplete.UTC())
	}
	return "—"
}

// actionCenter is HR's five queues: each queue's count, its first three
// courses, how many more there are, or the words for none.
func (d *dashboard) actionCenter() []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{}
	for _, g := range [][2]string{
		{"not_started", "Not Yet Started"}, {"in_progress", "In Progress"},
		{"pending_certificate", "Pending Certificate Upload"}, {"pending_accountability", "Pending Funds Accountability"},
		{"ready_signoff", "Ready for HR Sign-Off"},
	} {
		items := []request{}
		for _, r := range d.rows {
			if (g[0] == "pending_accountability" && pendingAccountability(r)) ||
				(g[0] == "ready_signoff" && r.status == statusAwaitingHR) || bucket(r.status) == g[0] {
				items = append(items, r)
			}
		}
		out = append(out, fundworkspace.Strip("Performance overview", []string{g[1]}, []string{strconv.Itoa(len(items))}, []string{""}))
		if len(items) == 0 {
			out = append(out, fundworkspace.Panel("", fundworkspace.Text("Nothing here right now.")))
			continue
		}
		lines := []*screensv1.PagePanelItem{}
		for _, r := range items[:min(len(items), queueSample)] {
			lines = append(lines, fundworkspace.Text(strings.Join(strings.Fields(r.staffName), " ")),
				fundworkspace.Text(r.course), fundworkspace.Text(d.dueLabel(r, g[0])))
		}
		out = append(out, fundworkspace.Panel("", feeddom.Paired(lines)...))
		if len(items) > queueSample {
			out = append(out, fundworkspace.Panel("", fundworkspace.Text(fmt.Sprintf("+%d more", len(items)-queueSample))))
		}
	}
	return out
}

// sortFund puts Not Applied first, then by name, keeping the order by name
// the people were read in for equal names.
func sortFund(people []person) {
	order := map[string]int{}
	for i, k := range fundOrder {
		order[k] = i
	}
	sort.SliceStable(people, func(i, j int) bool {
		a, b := order[fundStatus(people[i].req)], order[fundStatus(people[j].req)]
		if a != b {
			return a < b
		}
		return people[i].name < people[j].name
	})
}

// fundBlocks is fund_table.html: the not-yet-applied count, the status
// chips and every eligible person's row.
func (d *dashboard) fundBlocks() []*screensv1.PageBlock {
	counts := map[string]int{}
	rows := []*screensv1.PageRow{}
	for _, p := range d.fund {
		status := fundStatus(p.req)
		counts[status]++
		certificate := certificateStatus(p.req, p.certificateID != "")
		course, actions, href := "", []string{}, ""
		if reminder := fundReminder(status, certificate); reminder != "" && (reminder != "Remind to Apply" || d.role.AdjustAllocation) {
			actions = append(actions, reminder)
		}
		if p.req != nil {
			course = p.req.course
			actions = append(actions, "View Form")
			href = "/my-professional-development/request/" + p.req.id + "/form.pdf"
		}
		if p.certificateID != "" {
			actions = append(actions, "Certificate", "Download")
		}
		country := p.country
		if country == "" {
			country = "—"
		}
		action := cell(strings.Join(actions, " "))
		action.Href = href
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(country), d.staffCell(p.name, p.staffID, "", course), cell(roleLabel(p.role)),
			cell(money(p.currency, p.cents)), cell(rules.FundStatusLabels[status]),
			cell(rules.CertificateLabels[certificate]), action,
		}})
	}
	chips := []*screensv1.PageLink{{Text: fmt.Sprintf("All (%d)", len(d.fund)), Href: PagePath}}
	for _, k := range fundOrder {
		chips = append(chips, &screensv1.PageLink{Text: fmt.Sprintf("%s (%d)", rules.FundStatusLabels[k], counts[k]), Href: PagePath})
	}
	return []*screensv1.PageBlock{
		fundworkspace.Panel(fmt.Sprintf("2b. Staff Development Fund · Not Yet Applied (%d)", counts["not_applied"])),
		fundworkspace.Panel("", fundworkspace.Links(chips...)),
		table([]string{"Country", "Staff Name", "Staff Role", "Allocation (USD)", "Status", "Certificate", "Action"},
			map[int]bool{3: true, 6: true}, rows, "No Professional-Development-eligible staff found."),
	}
}

func (d *dashboard) roleBlocks() []*screensv1.PageBlock {
	country := d.country
	if country == "" {
		country = defaultCountry
	}
	action := "HR only"
	if d.role.AdjustAllocation {
		action = "Adjust"
	}
	rows := []*screensv1.PageRow{}
	for _, r := range d.roleRows {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(roleLabel(r.role)), cell(money(r.currency, r.perStaff)), cell(strconv.Itoa(r.count)),
			cell(money(r.currency, r.perStaff*int64(r.count))), cell(action),
		}})
	}
	return []*screensv1.PageBlock{
		fundworkspace.Panel("3. Role-Based PD Allocation Settings", fundworkspace.Text(fmt.Sprintf(
			"%s · %d staff · %s %s total FY %s allocation", country, d.roleStaff, d.currency, whole(d.roleCents), d.fy))),
		table([]string{"Role", "Per Staff / Year", "Staff Count", "Total Allocated", "Action"},
			map[int]bool{1: true, 3: true, 4: true}, rows, "No Professional-Development-eligible staff found."),
	}
}

func chart(title string, categories []string, values []float64) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: &screensv1.PageChart{Title: title, Horizontal: true,
		Categories: categories, Series: []*screensv1.PageSeries{{Name: title, Values: values}}}}}
}

func (d *dashboard) charts() []*screensv1.PageBlock {
	keys := []string{"not_started", "in_progress", "pending_certificate", "completed", "signed_off"}
	counts := map[string]float64{}
	for _, r := range d.rows {
		counts[bucket(r.status)]++
	}
	values := make([]float64, len(keys))
	for i, k := range keys {
		values[i] = counts[k]
	}
	return []*screensv1.PageBlock{
		chart("4a. Course Status Distribution",
			[]string{"Not Started", "In Progress", "Pending Certificate", "Completed", "Signed Off"}, values),
		chart("4b. Fund Utilization", []string{"Accounted For", "Committed, Not Accounted", "Uncommitted"},
			[]float64{float64(d.accounted), float64(max(0, d.committed-d.accounted)),
				float64(max(0, d.totalCents-d.committed-d.accounted))}),
	}
}

// workflowPanel is section 5, the reminders the daily job sends.
func workflowPanel() *screensv1.PageBlock {
	lines := []string{
		"1", "Pre-Course Reminder", "7, 3, and 1 day before the course start date — to the employee.",
		"2", "In-Progress Check-In", "Daily, while the course is under way — to the employee.",
		"3", "Mark Complete Prompt", "Once the end date passes, until marked complete — to the employee.",
		"4", "Overdue Escalation", "7, 14, and 30 days overdue and still not marked complete — to the employee.",
		"5", "Supervisor + HR Escalation", "From 14 days overdue onward — to the supervisor and HR too.",
		"Reminders are computed and sent by a daily scheduled job (send_pd_reminders). Every reminder is deduplicated, so no one is notified twice for the same milestone on the same day.",
	}
	items := make([]*screensv1.PagePanelItem, len(lines))
	for i, l := range lines {
		items[i] = fundworkspace.Text(l)
	}
	return fundworkspace.Panel("5. Automated Notification Workflow", feeddom.Paired(items)...)
}

func (d *dashboard) snapshot() *screensv1.PageBlock {
	var closed, bamboo, eligible int64
	for _, r := range d.rows {
		if r.status == statusClosed {
			closed++
			if r.bamboo {
				bamboo++
			}
		}
		if in(rules.EmployeeDoneStatuses, r.status) || in(rules.SignedOffStatuses, r.status) {
			eligible++
		}
	}
	return fundworkspace.Strip("Performance overview",
		[]string{"Signed off, FY " + d.fy, "Certificates verified", "BambooHR confirmed", "Sign-off rate"},
		[]string{strconv.FormatInt(closed, 10), strconv.Itoa(d.certsVerified), strconv.FormatInt(bamboo, 10),
			fmt.Sprintf("%d%%", percent(closed, eligible))},
		[]string{"", "", "", ""})
}

// upcoming is section 7: courses starting within 30 days, ended without a
// certificate, and funded courses whose accountability is a week late.
func (d *dashboard) upcoming() *screensv1.PageBlock {
	var soon, noCert, late []request
	for _, r := range d.rows {
		if (in(rules.NotStartedStatuses, r.status) || in(rules.InProgressStatuses, r.status)) &&
			days(d.today, r.start) >= 0 && days(d.today, r.start) <= 30 {
			soon = append(soon, r)
		}
		if in(rules.PendingCertificateStatuses, r.status) && days(r.end, d.today) > 0 {
			noCert = append(noCert, r)
		}
		if pendingAccountability(r) && days(dayOf(r.updated.UTC()), d.today) > 7 {
			late = append(late, r)
		}
	}
	items := []*screensv1.PagePanelItem{}
	list := func(title string, rs []request, empty string, line func(request) string) {
		items = append(items, fundworkspace.Text(title), fundworkspace.Text(strconv.Itoa(len(rs))))
		if len(rs) == 0 {
			items = append(items, fundworkspace.Text(empty))
		}
		for _, r := range rs[:min(len(rs), listSample)] {
			name := d.staffCell(r.staffName, r.staffID, "", "")
			if name.Href != "" {
				items = append(items, fundworkspace.Links(&screensv1.PageLink{Text: name.Text, Href: name.Href}))
			} else {
				items = append(items, fundworkspace.Text(name.Text))
			}
			items = append(items, fundworkspace.Text(line(r)))
		}
	}
	list("Starting in 30 Days", soon, "Nothing starting soon.", func(r request) string {
		return r.course + " · starts " + r.start.Format("02 Jan")
	})
	list("Overdue — No Certificate", noCert, "Nothing overdue.", func(r request) string {
		return r.course + " · ended " + r.end.Format("02 Jan")
	})
	list("Overdue — Accountability", late, "Nothing overdue.", func(r request) string { return r.course })
	return fundworkspace.Panel("7. Upcoming & Overdue Courses", feeddom.Paired(items)...)
}

func (d *dashboard) quickActions() *screensv1.PageBlock {
	if !d.role.AdjustAllocation {
		return fundworkspace.Panel("8. Quick Actions")
	}
	return fundworkspace.Panel("8. Quick Actions",
		fundworkspace.Links(&screensv1.PageLink{Text: "Adjust Allocations", Href: "#pd-role-settings"}))
}
