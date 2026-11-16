package myplan

import (
	"context"
	"fmt"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// A Programme Lead's This Week (apps.analytics.pl_week_service.PLWeek, not
// solo): the lead's and every officer's week, one tab each, Everyone first,
// each tab's work overdue from the week before and then due this week, every
// row asking one thing of the lead.

// TeamPerson is one person on the lead's week: the lead ("me"), or an
// officer keyed by their staff profile.
type TeamPerson struct {
	Key, Name, StaffID string
	IDs                []string
	Me                 bool
}

func (p TeamPerson) first() string {
	if p.Me {
		return "You"
	}
	if f := strings.Fields(p.Name); len(f) > 0 {
		return f[0]
	}
	return ""
}

// teamStats are one person's week in figures.
type teamStats struct {
	TeamPerson
	planned, closed, behind, awaiting, late int
}

func (s teamStats) needsYou() int {
	if s.Me {
		return 0
	}
	return s.late + s.behind + s.awaiting
}

// TeamWeek is the lead's week, drawn for one tab.
type TeamWeek struct {
	Start, End, Today time.Time
	FY, Who           string
	people            []teamStats
	shown             teamStats
	everyone          bool
	leave             []string
	overdue, due      [3][]*weekRow
	// Paged is a table longer than one page: the caller passes the page on.
	Paged bool
}

// tableIndex is table_of: trainings, meetings, and every other type with
// the school visits.
func tableIndex(kind string) int {
	switch {
	case in(rules.PastDue.TrainingTypes, kind):
		return 1
	case in(rules.PastDue.MeetingTypes, kind):
		return 2
	}
	return 0
}

// teamListed is one activity on the week, with its state and whose it is.
type teamListed struct {
	a      *activity
	state  weekState
	person string
}

// ReadTeamWeek is PLWeek.build for the lead and people (the lead first),
// drawing who's tab ("everyone" when who names nobody on the page).
func ReadTeamWeek(ctx context.Context, db schooldirectory.Querier, people []TeamPerson, start, now time.Time,
	fy, who string) (TeamWeek, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	w := TeamWeek{Start: start, End: start.AddDate(0, 0, 6), Today: today, FY: fy, Who: "everyone"}
	keyOf := map[string]string{}
	var ids, own []string
	for _, p := range people {
		for _, id := range p.IDs {
			keyOf[id] = p.Key
			ids = append(ids, id)
			if p.Me {
				own = append(own, id)
			}
		}
		if p.Key == who {
			w.Who = who
		}
	}
	listedWeek, listedLate, marks, acts, err := w.readListed(ctx, db, ids, keyOf, now)
	if err != nil {
		return TeamWeek{}, err
	}
	stats := map[string]*teamStats{}
	for _, p := range people {
		stats[p.Key] = &teamStats{TeamPerson: p}
	}
	for _, l := range listedWeek {
		s := stats[l.person]
		s.planned++
		if !l.state.open {
			s.closed++
		}
		if d := activityDay(l.a); !l.state.done && d.Before(today) {
			s.behind++
		}
		if l.state.action == "verify" {
			s.awaiting++
		}
	}
	for _, l := range listedLate {
		stats[l.person].late++
	}
	for _, p := range people {
		w.people = append(w.people, *stats[p.Key])
	}
	weekRows, lateRows := listedWeek, listedLate
	if w.Who == "everyone" {
		w.everyone = true
		for _, s := range w.people {
			w.shown.planned += s.planned
			w.shown.closed += s.closed
			w.shown.behind += s.behind
			w.shown.awaiting += s.awaiting
		}
	} else {
		w.shown = *stats[w.Who]
		weekRows, lateRows = mine(listedWeek, w.Who), mine(listedLate, w.Who)
	}
	var open []teamListed
	for _, l := range weekRows {
		if l.state.open {
			open = append(open, l)
		}
	}
	if err := w.readLeave(ctx, db, people); err != nil {
		return TeamWeek{}, err
	}
	return w, w.fillTables(ctx, db, lateRows, open, marks, acts, own, people)
}

func mine(ls []teamListed, key string) []teamListed {
	var out []teamListed
	for _, l := range ls {
		if l.person == key {
			out = append(out, l)
		}
	}
	return out
}

// activityDay is activity_day: the planned date, else the scheduled day.
func activityDay(a *activity) *time.Time {
	if d := date(a.plannedDate); d != nil {
		return d
	}
	return day(a.scheduledDate)
}

// readListed is _activities read into the two lists: this week's work, and
// last week's the officer still has to complete (not completed with its
// Salesforce ID, which waits in the lead's Completion Reviews).
func (w *TeamWeek) readListed(ctx context.Context, db schooldirectory.Querier, ids []string, keyOf map[string]string,
	now time.Time) (week, late []teamListed, marks map[string]completion, acts map[string]*activity, err error) {
	if len(ids) == 0 {
		return nil, nil, nil, nil, nil
	}
	from, to := w.Start.AddDate(0, 0, -7).Format(time.DateOnly), w.End.Format(time.DateOnly)
	found, err := idsWhere(ctx, db, `SELECT a.id FROM activity a WHERE a.deleted_at IS NULL
AND a.responsible_staff_id = ANY($1) AND a.delivery_type IS DISTINCT FROM 'partner'
AND NOT COALESCE(a.status = ANY($2), false)
AND ((a.planned_date BETWEEN $3 AND $4) OR (a.planned_date IS NULL AND `+localDay+` BETWEEN $3 AND $4))
ORDER BY a.planned_date ASC, a.scheduled_date ASC, a.id ASC`, ids, rules.Week.ReleasedStatuses, from, to)
	if err != nil || len(found) == 0 {
		return nil, nil, nil, nil, err
	}
	loaded, err := readActivities(ctx, db, found)
	if err != nil {
		return nil, nil, nil, nil, err
	}
	kinds, err := evidenceKinds(ctx, db, loaded)
	if err != nil {
		return nil, nil, nil, nil, err
	}
	marks = completions(loaded, now.In(kampala), kinds)
	acts = map[string]*activity{}
	for _, a := range loaded {
		acts[a.id] = a
	}
	for _, id := range found {
		a := acts[id]
		if a == nil {
			continue
		}
		key, ok := keyOf[str(a.staffID)]
		if !ok {
			continue
		}
		d := activityDay(a)
		if d == nil {
			continue
		}
		s := weekStatus(a.status, d, w.Today, marks[a.id])
		if key == "me" && s.key == "awaiting_you" {
			// The lead's own completion waits on nobody's verification here.
			s.action = "none"
		}
		l := teamListed{a: a, state: s, person: key}
		switch {
		case !d.Before(w.Start):
			week = append(week, l)
		case s.open && d.Before(w.Today) && !(s.key == "awaiting_you" && marks[a.id].salesforce != ""):
			late = append(late, l)
		}
	}
	return week, late, marks, acts, nil
}

// readLeave is _leave over everyone on the page, written as the drawn tab
// reads it: each person's spans on Everyone, the person's own on theirs.
func (w *TeamWeek) readLeave(ctx context.Context, db schooldirectory.Querier, people []TeamPerson) error {
	solo := Week{Start: w.Start, End: w.End}
	for _, p := range people {
		if p.StaffID == "" || (!w.everyone && p.Key != w.Who) {
			continue
		}
		spans, err := solo.readLeave(ctx, db, p.StaffID)
		if err != nil {
			return err
		}
		for _, s := range spans {
			if w.everyone {
				s = p.Name + " (" + s + ")"
			}
			w.leave = append(w.leave, s)
		}
	}
	return nil
}

// fillTables builds the drawn rows: "What needs you now"'s rows, each with
// the week's status and the one thing it asks of the lead.
func (w *TeamWeek) fillTables(ctx context.Context, db schooldirectory.Querier, late, open []teamListed,
	marks map[string]completion, acts map[string]*activity, own []string, people []TeamPerson) error {
	var counts [2][3]int
	for _, l := range late {
		counts[0][tableIndex(l.a.activityType)]++
	}
	for _, l := range open {
		counts[1][tableIndex(l.a.activityType)]++
	}
	for _, c := range counts {
		for _, n := range c {
			if n > rules.Week.RowsPerPage {
				w.Paged = true
				return nil
			}
		}
	}
	all := append(append([]teamListed{}, late...), open...)
	if len(all) == 0 {
		return nil
	}
	list := make([]*activity, 0, len(all))
	ids := make([]string, 0, len(all))
	for _, l := range all {
		list = append(list, l.a)
		ids = append(ids, l.a.id)
	}
	rows, err := pastDueRows(ctx, db, list, marks, own)
	if err != nil {
		return err
	}
	sent, err := reminderSentOn(ctx, db, ids)
	if err != nil {
		return err
	}
	first := map[string]string{}
	for _, p := range people {
		first[p.Key] = p.first()
	}
	sendUntil := MondayOf(w.Today).AddDate(0, 0, 6)
	build := func(l teamListed) *weekRow {
		r := rows[l.a.id]
		r.status = l.state.label
		if r.isOwn && l.state.key == "awaiting_you" {
			r.status = rules.Week.OwnAwaitingLabel
		}
		d := r.plannedDay
		row := &weekRow{pastDueRow: r, overdue: d != nil && d.Before(w.Today) && l.state.open, action: "none"}
		if l.person != "me" {
			row.sendName = first[l.person]
		}
		switch {
		case r.isOwn:
			if l.state.action == "send" {
				row.action = "own"
			}
		case l.state.action == "verify":
			row.action = "verify"
		case l.state.action == "send" && d != nil && !d.After(sendUntil):
			row.action = "send"
			if on, ok := sent[l.a.id]; ok {
				row.action, row.sentOn = "sent", on
			}
		}
		return row
	}
	for _, l := range late {
		w.overdue[tableIndex(l.a.activityType)] = append(w.overdue[tableIndex(l.a.activityType)], build(l))
	}
	for _, l := range open {
		w.due[tableIndex(l.a.activityType)] = append(w.due[tableIndex(l.a.activityType)], build(l))
	}
	return nil
}

// reminderSentOn is reminder_sent_on: the day each activity's live overdue
// reminder was sent, "Tue 17 Nov".
func reminderSentOn(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	rows, err := db.Query(ctx, `SELECT context_id, max(created_at) FROM notification
WHERE source_event_type = 'pl_activity_overdue_reminder' AND context_id = ANY($1) AND resolved_at IS NULL
AND created_at IS NOT NULL GROUP BY context_id`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: reminders: %w", err)
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var id string
		var at time.Time
		if err := rows.Scan(&id, &at); err != nil {
			return nil, fmt.Errorf("myplan: reminders: %w", err)
		}
		out[id] = weekDay(at.In(kampala))
	}
	return out, rows.Err()
}

func (w TeamWeek) query(who string, week time.Time, show string) string {
	q := []string{"fy=" + w.FY, "view=week"}
	if !week.Equal(MondayOf(w.Today)) {
		q = append(q, "week="+week.Format(time.DateOnly))
	}
	if who != "" && who != "everyone" {
		q = append(q, "who="+who)
	}
	if show != "" {
		q = append(q, "show="+show)
	}
	return "/dashboard?" + strings.Join(q, "&")
}

// overdueLabel is the overdue list's name.
func (w TeamWeek) overdueLabel() string {
	if w.Start.Equal(MondayOf(w.Today)) {
		return "Overdue from last week"
	}
	previous := w.Start.AddDate(0, 0, -7)
	return fmt.Sprintf("Overdue from the week of %d %s", previous.Day(), previous.Format("Jan"))
}

// TeamWeekBlocks are the lead's week panel's blocks as the feed reads them.
func TeamWeekBlocks(w TeamWeek) []*screensv1.PageBlock {
	solo := Week{Start: w.Start, End: w.End, Today: w.Today}
	head := solo.head(w.query, w.Who)
	head.Subtitle = strings.Replace(head.Subtitle, "Your work this week", "Where you and your officers are working", 1)
	head.Subtitle = strings.Replace(head.Subtitle, "what your partners did", "what the partners did", 1)
	tabs := &screensv1.PageLinkTabs{Scrolls: true, Tabs: []*screensv1.PageLinkTab{
		{Label: "Everyone", Href: w.query("everyone", w.Start, ""), Active: w.everyone}}}
	for _, p := range w.people {
		label := p.Name
		if p.Me {
			label = "Me"
		}
		if n := p.needsYou(); n > 0 {
			label += fmt.Sprintf(" %d", n)
		}
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: label, Href: w.query(p.Key, w.Start, ""), Active: !w.everyone && p.Key == w.Who})
	}
	tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: "Partners", Href: w.query("partners", w.Start, "")})
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: head}},
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
	}
	if len(w.leave) > 0 {
		words := "On approved leave " + strings.Join(w.leave, ", ") + "."
		if w.everyone {
			words = "On approved leave: " + strings.Join(w.leave, "; ") + "."
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Items: []*screensv1.PagePanelItem{panelText(words)}}}})
	}
	who := w.Who
	s := w.shown
	facts := []*screensv1.PageLink{
		{Text: fmt.Sprintf("%d planned this week", s.planned), Href: w.query(who, w.Start, "planned")},
		{Text: fmt.Sprintf("%d verified", s.closed), Href: w.query(who, w.Start, "verified")},
	}
	if !s.Me {
		facts = append(facts, &screensv1.PageLink{Text: fmt.Sprintf("%d awaiting your verification", s.awaiting), Href: w.query(who, w.Start, "awaiting")})
	}
	facts = append(facts, &screensv1.PageLink{Text: fmt.Sprintf("%d past their day, not completed", s.behind), Href: w.query(who, w.Start, "behind")})
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{linksItem(facts...)}}}})
	blocks = append(blocks, w.sectionBlocks(w.overdueLabel(), w.overdue, true)...)
	return append(blocks, w.sectionBlocks("Due this week", w.due, false)...)
}

// sectionBlocks is one list under its heading: an empty overdue list is its
// heading and one line; the week's list draws every table's band.
func (w TeamWeek) sectionBlocks(label string, tables [3][]*weekRow, overdue bool) []*screensv1.PageBlock {
	count := len(tables[0]) + len(tables[1]) + len(tables[2])
	if overdue && count == 0 {
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: fmt.Sprintf("%s 0", label),
			Items: []*screensv1.PagePanelItem{panelText("Nothing " + strings.ToLower(label) + ".")}}}}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Section{Section: fmt.Sprintf("%s %d", label, count)}}}
	prefix, empty := "", "None left this week"
	if overdue {
		prefix, empty = "Overdue ", "None overdue"
	}
	titles := map[string]string{}
	for _, t := range rules.Week.Tables {
		titles[t[0]] = t[1]
	}
	blocks = append(blocks, weekTable(prefix+titles["visits"], empty, !overdue, tables[0],
		columns("School ID", "School Name", "Activity", "Planned Date", "Completed Date", "Executor", "Purpose of Visit",
			"Focus Intervention", "Cost", "Salesforce ID", "Status", "Actions"), weekVisitCells)...)
	blocks = append(blocks, weekTable(prefix+titles["trainings"], empty, !overdue, tables[1],
		columns("School ID", "School / Cluster", "Cluster Planned From", "Executor", "Training Name", "Planned Date",
			"Completed Date", "SSA Intervention", "Participants", "Cost", "Salesforce ID", "Status", "Actions"), weekTrainingCells)...)
	return append(blocks, weekTable(prefix+titles["meetings"], empty, !overdue, tables[2],
		columns("Cluster Name", "District", "Planned Date", "Completed Date", "Executor", "Purpose (Meeting Topic)",
			"SSA Intervention", "Participants", "Cost", "Salesforce ID", "Status", "Actions"), weekMeetingCells)...)
}

// ResponsibleWithWork is which of ids own work of their own delivery, not
// released, dated from..to (_others_with_work).
func ResponsibleWithWork(ctx context.Context, db schooldirectory.Querier, ids []string, from, to time.Time) ([]string, error) {
	return idsWhere(ctx, db, `SELECT DISTINCT a.responsible_staff_id FROM activity a WHERE a.deleted_at IS NULL
AND a.responsible_staff_id = ANY($1) AND a.delivery_type IS DISTINCT FROM 'partner'
AND NOT COALESCE(a.status = ANY($2), false)
AND ((a.planned_date BETWEEN $3 AND $4) OR (a.planned_date IS NULL AND `+localDay+` BETWEEN $3 AND $4))`,
		ids, rules.Week.ReleasedStatuses, from.Format(time.DateOnly), to.Format(time.DateOnly))
}
