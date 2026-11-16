package myplan

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// A field officer's This Week (apps.analytics.pl_week_service.PLWeek in its
// solo mode, partials/dashboards/pl/week_panel.html): their own week, its
// figures and its open work in the three tables, as the feed reads the
// officer's own tab ("me") with no figure pressed.

// ActivityBar is the bar for ticked activities.
func ActivityBar() *screensv1.PageSelection { return activityBar() }

// Week is one officer's week.
type Week struct {
	Start, End, Today time.Time
	FY                string
	// PastDue is the officer's past-due count of any age ("What needs you
	// now"), which the week counts and does not list again.
	PastDue                     int
	Planned, Verified, Behind   int
	Leave                       []string
	Visits, Trainings, Meetings []*weekRow
	// Paged is a table longer than one page: the caller passes the page on.
	Paged bool
}

type weekRow struct {
	*pastDueRow
	overdue bool
	// action is the one thing the row asks of its reader: "own" (the
	// reader's own menu), "verify", "send", "sent" or "none".
	action           string
	sendName, sentOn string
}

// weekState is week_status.
type weekState struct {
	key, label, action string
	done, open         bool
}

func weekStatus(status string, d *time.Time, today time.Time, c completion) weekState {
	w := rules.Week
	past := d != nil && d.Before(today)
	var s weekState
	switch {
	case in(rules.Plan.CompletedWorkStatuses, status):
		s = weekState{key: "verified", label: "Verified", action: "none"}
	case in(w.WithIAStatuses, status):
		s = weekState{key: "with_ia", label: "With Impact Assessment", action: "none"}
	case in(w.AwaitingLeadStatuses, status):
		s = weekState{key: "awaiting_you", label: "Awaiting your verification", action: "verify"}
	case in(w.SFMissingStatuses, status):
		s = weekState{key: "sf_missing", label: "Salesforce ID missing", action: "send"}
	case in(w.NotSubmittedStatuses, status):
		s = weekState{key: "not_submitted", label: "Evidence uploaded, not submitted", action: "send"}
	case in(w.StartedStatuses, status):
		s = weekState{key: "started", label: "In Progress", action: "send"}
	case in(w.ReturnedStatuses, status):
		s = weekState{key: "returned", label: "Returned", action: "send"}
	case past:
		s = weekState{key: "past_due", label: "Past Due", action: "send"}
	case d != nil && d.Equal(today):
		s = weekState{key: "today", label: "Due today", action: "send"}
	default:
		s = weekState{key: "scheduled", label: "Scheduled", action: "send"}
	}
	officer := in(rules.Plan.OfficerCompletedStatuses, status)
	if (s.key == "verified" || s.key == "with_ia") && !(officer && officerComplete(c)) {
		// Complete only with both columns green: a verified status over a
		// missing half stays listed and says what is missing.
		s = weekState{key: "incomplete", label: completionGap(officer, c), action: "none"}
	}
	s.done = s.key == "verified" || s.key == "with_ia" || s.key == "awaiting_you"
	s.open = s.key != "verified" && s.key != "with_ia"
	return s
}

// MondayOf is monday_of.
func MondayOf(d time.Time) time.Time {
	return d.AddDate(0, 0, -((int(d.Weekday()) + 6) % 7))
}

// ResolveWeek is resolve_week: the Monday of the week raw names, or of this
// week when it names none, nonsense or one too far away.
func ResolveWeek(raw string, today time.Time) time.Time {
	this := MondayOf(today)
	raw = pyStrip(raw)
	if len(raw) > 10 {
		raw = raw[:10]
	}
	asked, err := time.Parse(time.DateOnly, raw)
	if err != nil {
		return this
	}
	asked = MondayOf(asked)
	gap := int(asked.Sub(this).Hours() / 24)
	if gap < 0 {
		gap = -gap
	}
	if gap > rules.Week.WeekReach*7 {
		return this
	}
	return asked
}

// ReadWeek is PLWeek.build for an officer's own week starting start.
func ReadWeek(ctx context.Context, db schooldirectory.Querier, owners []string, staffProfile string,
	start time.Time, now time.Time, fy string, pastDue int) (Week, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	w := Week{Start: start, End: start.AddDate(0, 0, 6), Today: today, FY: fy, PastDue: pastDue}
	if len(owners) > 0 {
		if err := w.readRows(ctx, db, owners, now); err != nil {
			return Week{}, err
		}
	}
	if staffProfile != "" {
		leave, err := w.readLeave(ctx, db, staffProfile)
		if err != nil {
			return Week{}, err
		}
		w.Leave = leave
	}
	return w, nil
}

func (w *Week) readRows(ctx context.Context, db schooldirectory.Querier, owners []string, now time.Time) error {
	from, to := w.Start.AddDate(0, 0, -7).Format(time.DateOnly), w.End.Format(time.DateOnly)
	ids, err := idsWhere(ctx, db, `SELECT a.id FROM activity a WHERE a.deleted_at IS NULL
AND a.responsible_staff_id = ANY($1) AND a.delivery_type IS DISTINCT FROM 'partner'
AND NOT COALESCE(a.status = ANY($2), false)
AND ((a.planned_date BETWEEN $3 AND $4) OR (a.planned_date IS NULL AND `+localDay+` BETWEEN $3 AND $4))
ORDER BY a.planned_date ASC, a.scheduled_date ASC, a.id ASC`, owners, rules.Week.ReleasedStatuses, from, to)
	if err != nil || len(ids) == 0 {
		return err
	}
	acts, err := readActivities(ctx, db, ids)
	if err != nil {
		return err
	}
	kinds, err := evidenceKinds(ctx, db, acts)
	if err != nil {
		return err
	}
	marks := completions(acts, now.In(kampala), kinds)
	byID := map[string]*activity{}
	for _, a := range acts {
		byID[a.id] = a
	}
	type listed struct {
		a     *activity
		state weekState
	}
	var open []listed
	for _, id := range ids {
		a := byID[id]
		if a == nil {
			continue
		}
		d := date(a.plannedDate)
		if d == nil {
			d = day(a.scheduledDate)
		}
		if d == nil || d.Before(w.Start) {
			continue
		}
		s := weekStatus(a.status, d, w.Today, marks[a.id])
		w.Planned++
		if !s.open {
			w.Verified++
		}
		if !s.done && d.Before(w.Today) {
			w.Behind++
		}
		if s.open {
			open = append(open, listed{a, s})
		}
	}
	var visits, trainings, meetings []listed
	for _, l := range open {
		switch {
		case in(rules.PastDue.TrainingTypes, l.a.activityType):
			trainings = append(trainings, l)
		case in(rules.PastDue.MeetingTypes, l.a.activityType):
			meetings = append(meetings, l)
		default:
			visits = append(visits, l)
		}
	}
	size := rules.Week.RowsPerPage
	if len(visits) > size || len(trainings) > size || len(meetings) > size {
		w.Paged = true
		return nil
	}
	shown := make([]*activity, 0, len(open))
	for _, l := range open {
		shown = append(shown, l.a)
	}
	rows, err := pastDueRows(ctx, db, shown, marks, owners)
	if err != nil {
		return err
	}
	pick := func(ls []listed) []*weekRow {
		out := make([]*weekRow, 0, len(ls))
		for _, l := range ls {
			r := rows[l.a.id]
			label := l.state.label
			if l.state.key == "awaiting_you" {
				label = rules.Week.OwnAwaitingLabel
			}
			r.status = label
			d := r.plannedDay
			action := "none"
			if l.state.action == "send" {
				action = "own"
			}
			out = append(out, &weekRow{pastDueRow: r, action: action,
				overdue: d != nil && d.Before(w.Today) && l.state.open})
		}
		return out
	}
	w.Visits, w.Trainings, w.Meetings = pick(visits), pick(trainings), pick(meetings)
	return nil
}

// readLeave is _leave: the officer's approved leave over the week, each
// span cut to the week ("Tue 17 Nov – Wed 18 Nov").
func (w *Week) readLeave(ctx context.Context, db schooldirectory.Querier, staff string) ([]string, error) {
	rows, err := db.Query(ctx, `SELECT start_date, end_date FROM leave
WHERE staff_id = $1 AND status = 'approved' AND end_date >= $2`, staff, w.Start.Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("myplan: week leave: %w", err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var begins, ends string
		if err := rows.Scan(&begins, &ends); err != nil {
			return nil, fmt.Errorf("myplan: week leave: %w", err)
		}
		b, errB := time.Parse(time.DateOnly, first10(begins))
		e, errE := time.Parse(time.DateOnly, first10(ends))
		if errB != nil || errE != nil || b.After(w.End) || e.Before(w.Start) {
			continue
		}
		if b.Before(w.Start) {
			b = w.Start
		}
		if e.After(w.End) {
			e = w.End
		}
		out = append(out, weekDay(b)+" – "+weekDay(e))
	}
	return out, rows.Err()
}

func first10(s string) string {
	if len(s) > 10 {
		return s[:10]
	}
	return s
}

// weekDay is f"{d:%a %-d %b}".
func weekDay(d time.Time) string {
	return d.Format("Mon") + " " + fmt.Sprint(d.Day()) + " " + d.Format("Jan")
}

// query is PLWeek.query for the officer's own week: fy, view, the week when
// it is not this one, whose when it is not theirs, and a figure.
func (w Week) query(who string, week time.Time, show string) string {
	q := []string{"fy=" + url.QueryEscape(w.FY), "view=week"}
	if !week.Equal(MondayOf(w.Today)) {
		q = append(q, "week="+week.Format(time.DateOnly))
	}
	if who != "" && who != "me" {
		q = append(q, "who="+url.QueryEscape(who))
	}
	if show != "" {
		q = append(q, "show="+url.QueryEscape(show))
	}
	return "/dashboard?" + strings.Join(q, "&")
}

func (w Week) rangeLabel() string {
	s, e := w.Start, w.End
	switch {
	case s.Month() == e.Month() && s.Year() == e.Year():
		return fmt.Sprintf("%d–%d %s", s.Day(), e.Day(), e.Format("January 2006"))
	case s.Year() == e.Year():
		return fmt.Sprintf("%d %s – %d %s", s.Day(), s.Format("Jan"), e.Day(), e.Format("Jan 2006"))
	}
	return fmt.Sprintf("%d %s – %d %s", s.Day(), s.Format("Jan 2006"), e.Day(), e.Format("Jan 2006"))
}

// HasTables is whether the week draws any table (the feed then reads the
// first table's "Ordered by date" as the view rail's subtitle).
func (w Week) HasTables() bool { return len(w.Visits)+len(w.Trainings)+len(w.Meetings) > 0 }

// head is the week's heading: which week, its range, what the page holds,
// and the arrows to the weeks either side (each keeping whose tab is open).
func (w Week) head(query func(who string, week time.Time, show string) string, who string) *screensv1.PagePanel {
	current := w.Start.Equal(MondayOf(w.Today))
	title := "Coming week"
	switch {
	case current:
		title = "This week"
	case w.End.Before(w.Today):
		title = fmt.Sprintf("Week of %d %s", w.Start.Day(), w.Start.Format("Jan"))
	}
	previous := w.Start.AddDate(0, 0, -7)
	arrows := []*screensv1.PageLink{{Text: "‹ Previous week", Href: query(who, previous, "")}}
	if !current {
		arrows = append(arrows, &screensv1.PageLink{Text: "This week", Href: query(who, MondayOf(w.Today), "")})
	}
	arrows = append(arrows, &screensv1.PageLink{Text: "Next week ›", Href: query(who, w.Start.AddDate(0, 0, 7), "")})
	return &screensv1.PagePanel{Title: title + " · " + w.rangeLabel(),
		Subtitle: fmt.Sprintf("Your work this week, what is overdue from the week of %d %s, and what your partners did.",
			previous.Day(), previous.Format("Jan")),
		Items: []*screensv1.PagePanelItem{linksItem(arrows...)}}
}

// WeekBlocks are the week panel's blocks as the feed reads them.
func WeekBlocks(w Week) []*screensv1.PageBlock {
	head := w.head(w.query, "me")
	mine := "My activities"
	if w.PastDue > 0 {
		mine += fmt.Sprintf(" %d", w.PastDue)
	}
	tabs := &screensv1.PageLinkTabs{Scrolls: true, Tabs: []*screensv1.PageLinkTab{
		{Label: mine, Href: w.query("me", w.Start, ""), Active: true},
		{Label: "My week", Href: w.query("everyone", w.Start, "")},
		{Label: "My partners", Href: w.query("partners", w.Start, "")},
	}}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: head}},
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
	}
	if len(w.Leave) > 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Items: []*screensv1.PagePanelItem{panelText("On approved leave " + strings.Join(w.Leave, ", ") + ".")}}}})
	}
	facts := linksItem(
		&screensv1.PageLink{Text: fmt.Sprintf("%d planned this week", w.Planned), Href: w.query("me", w.Start, "planned")},
		&screensv1.PageLink{Text: fmt.Sprintf("%d verified", w.Verified), Href: w.query("me", w.Start, "verified")},
		&screensv1.PageLink{Text: fmt.Sprintf("%d past their day, not completed", w.Behind), Href: w.query("me", w.Start, "behind")},
		&screensv1.PageLink{Text: fmt.Sprintf("%d past due, any age", w.PastDue), Href: "#what-needs-you-now"},
	)
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{facts}}}})
	if !w.HasTables() {
		return append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: "Nothing left to complete this week."}})
	}
	titles := map[string]string{}
	for _, t := range rules.Week.Tables {
		titles[t[0]] = t[1]
	}
	blocks = append(blocks, weekTable(titles["visits"], "", false, w.Visits,
		columns("School ID", "School Name", "Activity", "Planned Date", "Completed Date", "Executor", "Purpose of Visit",
			"Focus Intervention", "Cost", "Salesforce ID", "Status", "Actions"), weekVisitCells)...)
	blocks = append(blocks, weekTable(titles["trainings"], "", false, w.Trainings,
		columns("School ID", "School / Cluster", "Cluster Planned From", "Executor", "Training Name", "Planned Date",
			"Completed Date", "SSA Intervention", "Participants", "Cost", "Salesforce ID", "Status", "Actions"), weekTrainingCells)...)
	blocks = append(blocks, weekTable(titles["meetings"], "", false, w.Meetings,
		columns("Cluster Name", "District", "Planned Date", "Completed Date", "Executor", "Purpose (Meeting Topic)",
			"SSA Intervention", "Participants", "Cost", "Salesforce ID", "Status", "Actions"), weekMeetingCells)...)
	return blocks
}

func linksItem(links ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}}
}

// weekTable is one table under its title band. An empty one is drawn as its
// band alone, saying empty, where drawEmpty; otherwise not at all.
func weekTable(title, empty string, drawEmpty bool, rows []*weekRow, cols []*screensv1.PageColumn,
	cells func(*weekRow) []*screensv1.PageCell) []*screensv1.PageBlock {
	if len(rows) == 0 && !drawEmpty {
		return nil
	}
	note := "Ordered by date"
	if len(rows) == 0 {
		note = empty
	}
	band := &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Heading{Heading: title}},
		panelText(fmt.Sprint(len(rows))), panelText(note),
	}}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: band}}}
	if len(rows) == 0 {
		return blocks
	}
	table := &screensv1.PageTable{Columns: cols}
	for _, r := range rows {
		row := &screensv1.PageRow{Cells: append(cells(r), r.weekTail()...)}
		if r.overdue {
			row.Tone = "overdue"
		}
		if r.action == "own" {
			label := "Select " + orDefault(r.typeLabel, "activity")
			if name := r.placeName(); name != "" {
				label += " at " + name
			}
			if r.plannedDay != nil {
				label += " on " + shownDay(r.plannedDay)
			}
			row.PickId, row.PickLabel = r.a.id, label
		}
		table.Rows = append(table.Rows, row)
	}
	return append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}})
}

// weekTail is Cost, Salesforce ID, Status and the row's one action. The
// feed reads the officer's own menu as actions, and every other ask (Verify,
// Send to, Sent to, View Details) as the button's words.
func (r *weekRow) weekTail() []*screensv1.PageCell {
	sf := &screensv1.PageCell{Text: "Not in SF"}
	if r.salesforce != "" {
		sf = &screensv1.PageCell{Text: r.salesforce}
	}
	var action *screensv1.PageCell
	switch r.action {
	case "own":
		id := r.a.id
		menu := func(key, label, href string) *screensv1.PageAction {
			return &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href, Drawer: true}
		}
		action = &screensv1.PageCell{Actions: []*screensv1.PageAction{
			menu("menu", "Complete Activity", "/my-plan/"+id+"/complete-drawer"),
			menu("menu", "Reschedule Activity", "/my-plan/"+id+"/reschedule-drawer"),
			menu("danger", "Cancel Activity", "/my-plan/"+id+"/cancel-drawer"),
			menu("menu", "View Details", "/my-plan/"+id),
		}}
	case "verify":
		action = &screensv1.PageCell{Text: "Verify"}
	case "send":
		action = &screensv1.PageCell{Text: "Send to " + r.sendName}
	case "sent":
		words := "Sent to " + r.sendName
		if r.sentOn != "" {
			words += " · " + r.sentOn
		}
		action = &screensv1.PageCell{Text: words}
	default:
		action = &screensv1.PageCell{Text: "View Details"}
	}
	return []*screensv1.PageCell{{Text: r.cost}, sf, badge(r.status, "primary"), action}
}

// completedOn is the Completed Date column: the week's table rows never
// carry the day, so it reads "—".
func completedOn() *screensv1.PageCell { return &screensv1.PageCell{Text: dash} }

func weekVisitCells(r *weekRow) []*screensv1.PageCell {
	return []*screensv1.PageCell{
		{Text: orDefault(r.schoolID, dash)}, {Text: orDefault(r.schoolName, dash), Href: r.placeURL},
		{Text: r.typeLabel}, {Text: r.planned}, completedOn(), r.executor(),
		{Text: orDefault(r.purpose, dash)}, r.focusCell(),
	}
}

func weekTrainingCells(r *weekRow) []*screensv1.PageCell {
	return []*screensv1.PageCell{
		{Text: orDefault(r.schoolID, dash)}, {Text: r.placeName(), Href: r.placeURL},
		clusterLink(r.clusterName, r.clusterID, dash), r.executor(), {Text: r.typeLabel},
		{Text: r.planned}, completedOn(), r.focusCell(), {Text: r.expected},
	}
}

func weekMeetingCells(r *weekRow) []*screensv1.PageCell {
	return []*screensv1.PageCell{
		clusterLink(r.clusterName, r.clusterID, ""), {Text: r.clusterDistr}, {Text: r.planned}, completedOn(),
		r.executor(), {Text: orDefault(r.purpose, "Cluster Meeting")}, r.focusCell(), {Text: r.expected},
	}
}

// ShowFilter is whether value names one of the week's figures (SHOW_FILTERS).
func ShowFilter(value string) bool { return in(rules.Week.ShowFilters, value) }
