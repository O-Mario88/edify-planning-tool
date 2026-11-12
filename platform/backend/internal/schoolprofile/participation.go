package schoolprofile

import (
	"context"
	"fmt"
	"math"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// participationTab is the Participation tab (pi.section "activities"): the
// year's work by kind, training by channel and the cluster meetings
// (partials/profiles/_sections.html, _operations.html), the school's planned
// and completed activities with what the reader may do to each
// (apps.activities.profile_activities), then what visits found and what a
// partner holds (partials/schools/_participation.html). The bar for ticked
// activities comes back beside the blocks.
func (s *Service) participationTab(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, d doors, sc school, l lens, now time.Time) ([]*screensv1.PageBlock, *screensv1.PageSelection, error) {
	today := kampalaDay(now)
	allClusters, liveClusters, err := s.clusterSets(ctx, sc)
	if err != nil {
		return nil, nil, err
	}
	ex, err := s.execution(ctx, sc, allClusters, l, today)
	if err != nil {
		return nil, nil, err
	}
	blocks := []*screensv1.PageBlock{executionTable(ex, l)}
	channels, err := s.channels(ctx, sc, liveClusters, l)
	if err != nil {
		return nil, nil, err
	}
	blocks = append(blocks, channelsTable(channels, l))
	meetings, err := s.meetings(ctx, sc, liveClusters, l, today)
	if err != nil {
		return nil, nil, err
	}
	blocks = append(blocks, meetingsTable(ex.meetings, meetings))

	list, err := s.activityList(ctx, p, scope, d, sc, today)
	if err != nil {
		return nil, nil, err
	}
	blocks = append(blocks, list.block())

	feedback, err := s.visitFeedback(ctx, sc)
	if err != nil {
		return nil, nil, err
	}
	if feedback != nil {
		blocks = append(blocks, feedback)
	}
	support, err := s.partnerSupport(ctx, sc)
	if err != nil {
		return nil, nil, err
	}
	if support != nil {
		blocks = append(blocks, support)
	}
	return blocks, list.selection(), nil
}

// kampalaDay is timezone.localdate(): today on Kampala's calendar, as a
// UTC midnight to compare calendar days with.
func kampalaDay(now time.Time) time.Time {
	t := now.In(kampala)
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// pyRoundInt is Python's round() of a float to a whole number: halves to
// the even neighbour.
func pyRoundInt(x float64) int { return int(math.RoundToEven(x)) }

// ── Visits, trainings and cluster meetings (engine._execution) ──────────────

// kindFigures are one kind of work's figures (engine._execution.figures),
// with what the year asks of the school (engine._expected).
type kindFigures struct {
	planned, completed, notStarted, overdue, byPartner, schools, schoolsDone int
	// At the school itself (engine._work_by_place).
	here, hereDone int
	// What is expected; nil where nothing is (a cluster meeting).
	expected, schoolsDue, planCoverage, coverage *int
}

type executionFigures struct{ visits, trainings, meetings kindFigures }

func (s *Service) execution(ctx context.Context, sc school, clusters []string, l lens, today time.Time) (executionFigures, error) {
	var ex executionFigures
	args := []any{}
	where := activityScope(sc, clusters, l, &args)
	args = append(args, rules.Engine.CompletedWorkStatuses, rules.Engine.NotStartedStatuses, today, sc.ID)
	k := len(args)
	done := fmt.Sprintf("a.status = ANY($%d)", k-3)
	waiting := fmt.Sprintf("a.status = ANY($%d)", k-2)
	past := fmt.Sprintf(`(a.planned_date < $%[1]d::date OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date < $%[1]d::date))`, k-1)
	here := fmt.Sprintf("a.school_id = $%d", k)
	cols := []string{}
	targets := []any{}
	for _, kind := range []struct {
		f     *kindFigures
		types []string
	}{{&ex.visits, rules.Engine.VisitTypes}, {&ex.trainings, rules.Engine.TrainingTypes}, {&ex.meetings, rules.Engine.MeetingTypes}} {
		args = append(args, kind.types)
		of := fmt.Sprintf("a.activity_type = ANY($%d)", len(args))
		count := func(filter string) string { return "COUNT(a.id) FILTER (WHERE " + of + " AND " + filter + ")" }
		cols = append(cols, count("true"), count(done), count(waiting), count(waiting+" AND "+past),
			count("a.delivery_type = 'partner'"),
			"COUNT(DISTINCT a.school_id) FILTER (WHERE "+of+")",
			"COUNT(DISTINCT a.school_id) FILTER (WHERE "+of+" AND "+done+")",
			count(here), count(here+" AND "+done))
		f := kind.f
		targets = append(targets, &f.planned, &f.completed, &f.notStarted, &f.overdue, &f.byPartner, &f.schools, &f.schoolsDone, &f.here, &f.hereDone)
	}
	if err := s.db.QueryRow(ctx, "SELECT "+strings.Join(cols, ", ")+" FROM activity a WHERE "+where, args...).Scan(targets...); err != nil {
		return ex, fmt.Errorf("schoolprofile: counting the work by kind: %w", err)
	}
	// engine._expected for one school: its type's yearly asks.
	need := rules.Engine.Requirements[sc.Type]
	for _, e := range []struct {
		f   *kindFigures
		ask int
	}{{&ex.visits, need.Visits}, {&ex.trainings, need.Trainings}} {
		expected, due, reached, inPlan := 0, 0, 0, 0
		if e.ask != 0 {
			expected, due = e.ask, 1
			if e.f.hereDone > 0 {
				reached = 1
			}
			if e.f.here > 0 {
				inPlan = 1
			}
		}
		e.f.expected, e.f.schoolsDue = &expected, &due
		if due > 0 {
			c, pc := pyRoundInt(float64(reached*100)/float64(due)), pyRoundInt(float64(inPlan*100)/float64(due))
			e.f.coverage, e.f.planCoverage = &c, &pc
		}
	}
	return ex, nil
}

// executionTable is the "profile-execution" table.
func executionTable(ex executionFigures, l lens) *screensv1.PageBlock {
	footnote := "In the plan leaves out work that was cancelled, rejected or deferred. Completed is work verified or closed. " +
		"Past its date is work not yet started whose day has gone. Schools is the schools with that work at the school itself; " +
		"a group training or a cluster meeting is counted as a session. Expected This Year is what each school's type is due " +
		"in the year (a Core school two visits and two trainings from staff and two of each from a partner; a Client, Core " +
		"Trained or Core Graduate school one of each; a Champion none). Schools Due is the schools due any; Coverage is the " +
		"share of them with one completed, Planned Coverage with one in the plan."
	if l.window.label != "" {
		footnote += " The work counted is " + l.window.label + "'s; what is expected is the whole year's."
	}
	table := &screensv1.PageTable{
		Title: "Visits, trainings and cluster meetings", Subtitle: fyLabel(l.fy), Footnote: footnote,
		Columns: columns([][2]string{{"Work", ""}, {"Expected This Year", "num"}, {"In The Plan", "num"}, {"Completed", "num"},
			{"Outstanding", "num"}, {"Upcoming", "num"}, {"Past Its Date", "num"}, {"By Staff", "num"}, {"By Partners", "num"},
			{"Schools", "num"}, {"Schools Completed", "num"}, {"Schools Due", "num"}, {"Planned Coverage", "num"}, {"Coverage", "num"}}),
	}
	optional := func(n *int, suffix string, strong bool) *screensv1.PageCell {
		if n == nil {
			return &screensv1.PageCell{Text: "—"}
		}
		return &screensv1.PageCell{Text: intcomma(*n) + suffix, Strong: strong}
	}
	records := l.records()
	for _, row := range []struct {
		label, what string
		f           kindFigures
	}{{"School visits", "visits", ex.visits}, {"Trainings", "trainings", ex.trainings}, {"Cluster meetings", "meetings", ex.meetings}} {
		f := row.f
		overdue := &screensv1.PageCell{Text: "0"}
		if f.overdue != 0 {
			overdue = &screensv1.PageCell{Text: intcomma(f.overdue), Href: records + row.what + "_overdue", Tone: "danger"}
		}
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: row.label},
			optional(f.expected, "", false),
			{Text: intcomma(f.planned), Href: records + row.what},
			{Text: intcomma(f.completed), Href: records + row.what + "_done"},
			{Text: intcomma(f.planned - f.completed)},
			{Text: intcomma(f.notStarted - f.overdue)},
			overdue,
			{Text: intcomma(f.planned - f.byPartner)},
			{Text: intcomma(f.byPartner)},
			{Text: intcomma(f.schools)},
			{Text: intcomma(f.schoolsDone)},
			optional(f.schoolsDue, "", false),
			optional(f.planCoverage, "%", false),
			optional(f.coverage, "%", true),
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}
}

func columns(cols [][2]string) []*screensv1.PageColumn {
	out := []*screensv1.PageColumn{}
	for _, c := range cols {
		out = append(out, &screensv1.PageColumn{Label: c[0], Numeric: c[1] == "num"})
	}
	return out
}

// ── Training By Channel (profile_records.channels) ──────────────────────────

type channelFigures struct {
	inSchool, inSchoolStaff, inSchoolPartner, inSchoolDone, inSchoolSchools, inSchoolPeople int
	group, groupWaiting, groupDone                                                          int
	online, onlineWaiting, onlineDone                                                       int
	groupInvited, groupAttended, groupPeople                                                int
	onlineInvited, onlineAttended, onlinePeople                                             int
	assigned                                                                                int
}

// online and notOnline split training by its channel; Django's negation of
// the nullable mode keeps a training with none.
const (
	online    = "a.programme_delivery_mode = 'online'"
	notOnline = "a.programme_delivery_mode IS DISTINCT FROM 'online'"
)

func (s *Service) channels(ctx context.Context, sc school, clusters []string, l lens) (channelFigures, error) {
	var c channelFigures
	args := []any{}
	where := activityScope(sc, clusters, l, &args)
	args = append(args, rules.Engine.TrainingTypes, rules.Engine.CompletedWorkStatuses, rules.Engine.NotStartedStatuses)
	k := len(args)
	training, done, waiting := fmt.Sprintf("a.activity_type = ANY($%d)", k-2), fmt.Sprintf("a.status = ANY($%d)", k-1), fmt.Sprintf("a.status = ANY($%d)", k)
	inSchool := "a.school_id IS NOT NULL AND " + notOnline
	group := "a.school_id IS NULL AND " + notOnline
	count := func(filter string) string { return "COUNT(a.id) FILTER (WHERE " + filter + ")" }
	if err := s.db.QueryRow(ctx, "SELECT "+strings.Join([]string{
		count(inSchool),
		count(inSchool + " AND a.delivery_type IS DISTINCT FROM 'partner'"),
		count(inSchool + " AND a.delivery_type = 'partner'"),
		count(inSchool + " AND " + done),
		"COUNT(DISTINCT a.school_id) FILTER (WHERE " + inSchool + " AND " + done + ")",
		"COALESCE(SUM(a.teachers_attended) FILTER (WHERE " + inSchool + " AND " + done + "), 0) + " +
			"COALESCE(SUM(a.leaders_attended) FILTER (WHERE " + inSchool + " AND " + done + "), 0)",
		count(group), count(group + " AND " + waiting), count(group + " AND " + done),
		count(online), count(online + " AND " + waiting), count(online + " AND " + done),
	}, ", ")+" FROM activity a WHERE "+training+" AND "+where, args...).Scan(
		&c.inSchool, &c.inSchoolStaff, &c.inSchoolPartner, &c.inSchoolDone, &c.inSchoolSchools, &c.inSchoolPeople,
		&c.group, &c.groupWaiting, &c.groupDone, &c.online, &c.onlineWaiting, &c.onlineDone); err != nil {
		return c, fmt.Errorf("schoolprofile: counting training by channel: %w", err)
	}

	// The register of the year's completed sessions (engine._sessions).
	args = []any{sc.ID, rules.Engine.CompletedWorkStatuses, l.fy, rules.Engine.TrainingTypes}
	inWindow := l.window.sql(&args)
	people := func(mode string) string {
		return "COALESCE(SUM(c.teachers) FILTER (WHERE " + mode + " AND c.attended), 0) + COALESCE(SUM(c.leaders) FILTER (WHERE " + mode + " AND c.attended), 0)"
	}
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(c.activity_id) FILTER (WHERE `+notOnline+` AND c.invited),
  COUNT(c.activity_id) FILTER (WHERE `+notOnline+` AND c.attended), `+people(notOnline)+`,
  COUNT(c.activity_id) FILTER (WHERE `+online+` AND c.invited),
  COUNT(c.activity_id) FILTER (WHERE `+online+` AND c.attended), `+people(online)+`
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
WHERE c.school_id = $1 AND a.status = ANY($2) AND a.school_id IS NULL AND a.fy = $3 AND a.deleted_at IS NULL
  AND a.activity_type = ANY($4) AND `+inWindow, args...).Scan(
		&c.groupInvited, &c.groupAttended, &c.groupPeople, &c.onlineInvited, &c.onlineAttended, &c.onlinePeople); err != nil {
		return c, fmt.Errorf("schoolprofile: reading the training register: %w", err)
	}
	// A hand-over for training the partner still holds (_handover_queryset).
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(id) FROM partner_assignment
WHERE school_id = $1 AND NOT (status = ANY($2)) AND expected_activity_type = ANY($3)`,
		sc.ID, rules.Engine.HandoverReleasedStatuses, rules.Engine.TrainingTypes).Scan(&c.assigned); err != nil {
		return c, fmt.Errorf("schoolprofile: counting training hand-overs: %w", err)
	}
	return c, nil
}

// attendanceRate is channels.rate: a whole percent, 0 with no invitations.
func attendanceRate(attended, invited int) int {
	if invited == 0 {
		return 0
	}
	return pyRoundInt(float64(attended*100) / float64(invited))
}

func channelsTable(c channelFigures, l lens) *screensv1.PageBlock {
	subtitle := fyLabel(l.fy)
	if l.window.label != "" {
		subtitle += " · " + l.window.label
	}
	records := l.records()
	dash := func() *screensv1.PageCell { return &screensv1.PageCell{Text: "—"} }
	link := func(n int, what string) *screensv1.PageCell {
		return &screensv1.PageCell{Text: intcomma(n), Href: records + what}
	}
	completed := func(n int, what string) *screensv1.PageCell {
		return &screensv1.PageCell{Text: intcomma(n), Href: records + what, Strong: true}
	}
	plain := func(n int) *screensv1.PageCell { return &screensv1.PageCell{Text: intcomma(n)} }
	rate := func(attended, invited int) *screensv1.PageCell {
		return &screensv1.PageCell{Text: intcomma(attendanceRate(attended, invited)) + "%"}
	}
	rows := []*screensv1.PageRow{
		{Cells: []*screensv1.PageCell{{Text: "In-school training"}, link(c.inSchool, "trainings_in_school"), plain(c.inSchoolStaff),
			link(c.assigned, "handovers"), link(c.inSchoolPartner, "trainings_partner"), plain(c.inSchool - c.inSchoolDone),
			completed(c.inSchoolDone, "trainings_in_school_done"), plain(c.inSchoolSchools), dash(), dash(),
			link(c.inSchoolPeople, "teachers_trained")}},
		{Cells: []*screensv1.PageCell{{Text: "Group training"}, link(c.group, "trainings_group"), dash(), dash(), dash(),
			plain(c.groupWaiting), completed(c.groupDone, "trainings_group_done"), plain(c.groupAttended),
			plain(c.groupInvited), rate(c.groupAttended, c.groupInvited), link(c.groupPeople, "teachers_trained")}},
		{Cells: []*screensv1.PageCell{{Text: "Online training"}, link(c.online, "trainings_online"), dash(), dash(), dash(),
			plain(c.onlineWaiting), completed(c.onlineDone, "trainings_online_done"), plain(c.onlineAttended),
			plain(c.onlineInvited), rate(c.onlineAttended, c.onlineInvited), link(c.onlinePeople, "teachers_trained")}},
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title: "Training By Channel", Subtitle: subtitle, Rows: rows,
		Columns: columns([][2]string{{"Channel", ""}, {"In The Plan", "num"}, {"Planned By Staff", "num"},
			{"Assigned To A Partner", "num"}, {"Dated By A Partner", "num"}, {"Still To Come", "num"}, {"Completed", "num"},
			{"Schools Attending", "num"}, {"Schools Invited", "num"}, {"Attendance", "num"}, {"Teachers And Leaders", "num"}}),
		Footnote: "Assigned To A Partner is a hand-over for training the partner still holds, dated or not; Dated By A Partner " +
			"is the in-school trainings a partner has put in the plan. Attendance is the schools recorded as attending of those " +
			"invited to completed sessions; an in-school training has no invitation list. The three channels' In The Plan add " +
			"up to the Trainings line above.",
	}}}
}

// ── Cluster Meetings (profile_records.meetings) ─────────────────────────────

type meetingKind struct {
	label         string
	planned, held int
}

type meetingFigures struct {
	kinds                      []meetingKind
	invited, attended, schools int
	next                       []string // "Cluster E, 5 Dec"
}

func (s *Service) meetings(ctx context.Context, sc school, clusters []string, l lens, today time.Time) (meetingFigures, error) {
	m := meetingFigures{}
	args := []any{}
	where := activityScope(sc, clusters, l, &args)
	args = append(args, rules.Engine.MeetingTypes, rules.Engine.CompletedWorkStatuses)
	k := len(args)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT a.meeting_kind, COUNT(a.id), COUNT(a.id) FILTER (WHERE a.status = ANY($%d))
FROM activity a WHERE a.activity_type = ANY($%d) AND `, k, k-1)+where+`
GROUP BY a.meeting_kind ORDER BY a.meeting_kind`, args...)
	if err != nil {
		return m, fmt.Errorf("schoolprofile: reading meetings by kind: %w", err)
	}
	for rows.Next() {
		var kind *string
		var mk meetingKind
		if err := rows.Scan(&kind, &mk.planned, &mk.held); err != nil {
			rows.Close()
			return m, err
		}
		mk.label = "Meeting"
		if kind != nil {
			if lb, ok := rules.Participation.MeetingKinds[*kind]; ok {
				mk.label = lb
			}
		}
		m.kinds = append(m.kinds, mk)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return m, err
	}

	args = []any{sc.ID, rules.Engine.CompletedWorkStatuses, l.fy, rules.Engine.MeetingTypes}
	inWindow := l.window.sql(&args)
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(c.activity_id) FILTER (WHERE c.invited), COUNT(c.activity_id) FILTER (WHERE c.attended),
  COUNT(DISTINCT c.school_id) FILTER (WHERE c.attended)
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
WHERE c.school_id = $1 AND a.status = ANY($2) AND a.school_id IS NULL AND a.fy = $3 AND a.deleted_at IS NULL
  AND a.activity_type = ANY($4) AND `+inWindow, args...).Scan(&m.invited, &m.attended, &m.schools); err != nil {
		return m, fmt.Errorf("schoolprofile: reading the meeting register: %w", err)
	}

	// The next meetings: not started and not past. Django's negation of the
	// past keeps a meeting with no day at all.
	args = []any{}
	where = activityScope(sc, clusters, l, &args)
	args = append(args, rules.Engine.MeetingTypes, rules.Engine.NotStartedStatuses, today)
	k = len(args)
	next, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT COALESCE(cl.name, ''), a.planned_date, a.scheduled_date
FROM activity a LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.activity_type = ANY($%[1]d) AND a.status = ANY($%[2]d)
  AND NOT ((a.planned_date < $%[3]d::date AND a.planned_date IS NOT NULL)
    OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date < $%[3]d::date AND a.scheduled_date IS NOT NULL))
  AND `, k-2, k-1, k)+where+`
ORDER BY a.planned_date, a.scheduled_date, a.id LIMIT 5`, args...)
	if err != nil {
		return m, fmt.Errorf("schoolprofile: reading the next meetings: %w", err)
	}
	defer next.Close()
	for next.Next() {
		var name string
		var planned, scheduled *time.Time
		if err := next.Scan(&name, &planned, &scheduled); err != nil {
			return m, err
		}
		if name == "" {
			name = "Meeting"
		}
		// profile_records._day: the planned day, else the scheduled
		// moment's own (UTC) date.
		day := ""
		switch {
		case planned != nil:
			day = jM(*planned)
		case scheduled != nil:
			day = jM(scheduled.UTC())
		}
		m.next = append(m.next, name+", "+day)
	}
	return m, next.Err()
}

// jM is Django's |date:"j M" ("5 Dec").
func jM(day time.Time) string { return fmt.Sprintf("%d %s", day.Day(), day.Format("Jan")) }

func meetingsTable(f kindFigures, m meetingFigures) *screensv1.PageBlock {
	footnote := fmt.Sprintf("%s school%s represented · %s of %s invitations attended · %d%% attendance.",
		intcomma(m.schools), plural(m.schools), intcomma(m.attended), intcomma(m.invited), attendanceRate(m.attended, m.invited))
	if len(m.next) > 0 {
		footnote += " Next: " + strings.Join(m.next, " · ") + "."
	}
	rows := []*screensv1.PageRow{}
	for _, k := range m.kinds {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: k.label}, {Text: intcomma(k.planned)}, {Text: intcomma(k.held)}}})
	}
	if len(rows) == 0 {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: "All meetings"}, {Text: "0"}, {Text: "0"}}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title: "Cluster Meetings",
		Subtitle: fmt.Sprintf("%s in the plan · %s held · %s still to come · %s past their date",
			intcomma(f.planned), intcomma(f.completed), intcomma(f.notStarted-f.overdue), intcomma(f.overdue)),
		Columns:  columns([][2]string{{"Meeting Type", ""}, {"In The Plan", "num"}, {"Held", "num"}}),
		Rows:     rows,
		Footnote: footnote,
	}}}
}
