package schoolprofile

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The Overview of one school: engine.build's figures for the year and
// period, drawn as partials/profiles/_sections.html's overview section and
// the insight rail (apps.analytics.profile_rail).

// ivRow is one intervention's two years (year_comparison.intervention_comparison).
type ivRow struct {
	key, label        string
	current, previous *float64
	verdict           change
}

// comparison is the school's SSA by intervention and overall.
type comparison struct {
	rows              []ivRow
	current, previous *float64
	// The schools with a confirmed record in the year and the year before.
	schools, previousSchools int
}

// interventionComparison reads the school's latest confirmed record of the
// year and of the year before: each intervention's score, and the overall
// (the record's average, else the mean of its scores).
func (s *Service) interventionComparison(ctx context.Context, schoolID, fy string) (comparison, error) {
	before := previousFY(fy)
	rows, err := s.db.Query(ctx, `
SELECT DISTINCT ON (r.fy) r.id, r.fy, r.average_score
FROM ssa_record r
WHERE r.school_id = $1 AND r.fy = ANY($2) AND r.deleted_at IS NULL AND r.verification_status = ANY($3)
ORDER BY r.fy, r.date_of_ssa DESC, r.created_at DESC, r.id DESC`, schoolID, []string{fy, before}, rules.SSACurrentStatuses)
	if err != nil {
		return comparison{}, fmt.Errorf("schoolprofile: reading SSA records: %w", err)
	}
	type record struct {
		year    string
		average *float64
	}
	records := map[string]record{}
	ids := []string{}
	for rows.Next() {
		var id string
		var r record
		if err := rows.Scan(&id, &r.year, &r.average); err != nil {
			rows.Close()
			return comparison{}, err
		}
		records[id] = r
		ids = append(ids, id)
	}
	rows.Close()
	byYear := map[string]map[string][]*float64{fy: {}, before: {}}
	perRecord := map[string][]*float64{}
	if len(ids) > 0 {
		rows, err := s.db.Query(ctx, `SELECT ssa_record_id, intervention, score FROM ssa_score WHERE ssa_record_id = ANY($1)`, ids)
		if err != nil {
			return comparison{}, fmt.Errorf("schoolprofile: reading SSA scores: %w", err)
		}
		for rows.Next() {
			var id, intervention string
			var score *float64
			if err := rows.Scan(&id, &intervention, &score); err != nil {
				rows.Close()
				return comparison{}, err
			}
			if score == nil {
				continue
			}
			v := *score
			year := records[id].year
			byYear[year][intervention] = append(byYear[year][intervention], &v)
			perRecord[id] = append(perRecord[id], &v)
		}
		rows.Close()
	}
	overall := func(year string) *float64 {
		values := []*float64{}
		for id, r := range records {
			if r.year != year {
				continue
			}
			if r.average != nil {
				values = append(values, r.average)
			} else {
				values = append(values, pyMean(perRecord[id]))
			}
		}
		return pyMean(values)
	}
	out := comparison{current: overall(fy), previous: overall(before)}
	for _, r := range records {
		if r.year == fy {
			out.schools++
		} else {
			out.previousSchools++
		}
	}
	for _, key := range rules.Engine.InterventionOrder {
		out.rows = append(out.rows, ivRow{
			key: key, label: rules.SSAInterventions[key],
			current: pyMean(byYear[fy][key]), previous: pyMean(byYear[before][key]),
		})
	}
	return out, nil
}

// work is the year's work at the school (and its cluster's sessions) that
// is in somebody's plan (engine._activities), for the period.
type work struct {
	visits, trainings, meetings        figures
	projectOverdue                     int
	visitsHere, trainingsHere, anyHere int
	teachers, leaders                  int // at completed in-school trainings
	trainedHere                        bool
	groupTeachers, groupLeaders        int
	groupTrained                       bool
	meetingTeachers, meetingLeaders    int
	onlinePlanned, onlineDone          int
	onlineInvited, onlineAttended      int
	focus                              map[string][2]int // planned, done
	awaitingPartner                    bool
}

type figures struct{ planned, completed, overdue int }

// activityScope is engine._activities as SQL: work at the school, or a
// session of one of clusterIDs, this year, in the plan, in the period.
func activityScope(sc school, clusterIDs []string, l lens, args *[]any) string {
	*args = append(*args, sc.ID, clusterIDs, l.fy, rules.Engine.NotInPlanStatuses)
	n := len(*args)
	return fmt.Sprintf(`(a.school_id = $%d OR (a.school_id IS NULL AND a.cluster_id = ANY($%d))) AND a.fy = $%d
  AND a.deleted_at IS NULL AND NOT (a.status = ANY($%d)) AND %s`, n-3, n-2, n-1, n, l.window.sql(args))
}

func (s *Service) work(ctx context.Context, sc school, l lens, now time.Time) (work, error) {
	w := work{focus: map[string][2]int{}}
	allClusters, liveClusters, err := s.clusterSets(ctx, sc)
	if err != nil {
		return w, err
	}
	today := now.In(kampala)
	day := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)

	args := []any{}
	where := activityScope(sc, allClusters, l, &args)
	args = append(args, rules.Engine.CompletedWorkStatuses, rules.Engine.NotStartedStatuses, day,
		rules.Engine.VisitTypes, rules.Engine.TrainingTypes, rules.Engine.MeetingTypes)
	k := len(args)
	done, waiting := fmt.Sprintf("a.status = ANY($%d)", k-5), fmt.Sprintf("a.status = ANY($%d)", k-4)
	past := fmt.Sprintf(`(a.planned_date < $%[1]d::date OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date < $%[1]d::date))`, k-3)
	kind := func(i int) string { return fmt.Sprintf("a.activity_type = ANY($%d)", k-3+i) }
	count := func(filter string) string { return "COUNT(a.id) FILTER (WHERE " + filter + ")" }
	cols := []string{}
	for i := 1; i <= 3; i++ {
		cols = append(cols, count(kind(i)), count(kind(i)+" AND "+done), count(kind(i)+" AND "+waiting+" AND "+past))
	}
	cols = append(cols, count(waiting+" AND "+past+" AND a.project_id IS NOT NULL"),
		count("a.school_id IS NOT NULL AND "+kind(1)), count("a.school_id IS NOT NULL AND "+kind(2)), count("a.school_id IS NOT NULL"))
	if err := s.db.QueryRow(ctx, "SELECT "+strings.Join(cols, ", ")+" FROM activity a WHERE "+where, args...).Scan(
		&w.visits.planned, &w.visits.completed, &w.visits.overdue,
		&w.trainings.planned, &w.trainings.completed, &w.trainings.overdue,
		&w.meetings.planned, &w.meetings.completed, &w.meetings.overdue,
		&w.projectOverdue, &w.visitsHere, &w.trainingsHere, &w.anyHere); err != nil {
		return w, fmt.Errorf("schoolprofile: counting the year's work: %w", err)
	}

	// People trained (engine.people): at the school's completed trainings,
	// and by the register of completed group trainings and meetings.
	args = []any{sc.ID, rules.Engine.CompletedWorkStatuses, rules.Engine.TrainingTypes, l.fy}
	inWindow := l.window.sql(&args)
	if err := s.db.QueryRow(ctx, `
SELECT COALESCE(SUM(a.teachers_attended), 0), COALESCE(SUM(a.leaders_attended), 0), COUNT(a.id) > 0
FROM activity a WHERE a.status = ANY($2) AND a.school_id = $1 AND a.activity_type = ANY($3) AND a.fy = $4
  AND a.deleted_at IS NULL AND `+inWindow, args...).Scan(&w.teachers, &w.leaders, &w.trainedHere); err != nil {
		return w, fmt.Errorf("schoolprofile: reading trainings delivered: %w", err)
	}
	args = []any{sc.ID, rules.Engine.CompletedWorkStatuses, l.fy, rules.Engine.TrainingTypes, rules.Engine.MeetingTypes}
	inWindow = l.window.sql(&args)
	if err := s.db.QueryRow(ctx, `
SELECT COALESCE(SUM(c.teachers) FILTER (WHERE a.activity_type = ANY($4)), 0),
  COALESCE(SUM(c.leaders) FILTER (WHERE a.activity_type = ANY($4)), 0),
  COUNT(c.activity_id) FILTER (WHERE a.activity_type = ANY($4)) > 0,
  COALESCE(SUM(c.teachers) FILTER (WHERE a.activity_type = ANY($5)), 0),
  COALESCE(SUM(c.leaders) FILTER (WHERE a.activity_type = ANY($5)), 0)
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
WHERE c.school_id = $1 AND c.attended AND a.status = ANY($2) AND a.school_id IS NULL AND a.fy = $3 AND a.deleted_at IS NULL
  AND `+inWindow, args...).Scan(&w.groupTeachers, &w.groupLeaders, &w.groupTrained, &w.meetingTeachers, &w.meetingLeaders); err != nil {
		return w, fmt.Errorf("schoolprofile: reading the register: %w", err)
	}
	// The register of the school's attendance above; the online channel
	// counts every row of the register, invited or attended.
	if err := s.registerCounts(ctx, sc, l, &w); err != nil {
		return w, err
	}

	// The records' work (profile_records._work): the live cluster's.
	args = []any{}
	where = activityScope(sc, liveClusters, l, &args)
	args = append(args, rules.Engine.TrainingTypes, rules.Engine.CompletedWorkStatuses)
	k = len(args)
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT COUNT(a.id) FILTER (WHERE a.activity_type = ANY($%[1]d) AND a.programme_delivery_mode = 'online'),
  COUNT(a.id) FILTER (WHERE a.activity_type = ANY($%[1]d) AND a.programme_delivery_mode = 'online' AND a.status = ANY($%[2]d))
FROM activity a WHERE `, k-1, k)+where, args...).Scan(&w.onlinePlanned, &w.onlineDone); err != nil {
		return w, fmt.Errorf("schoolprofile: reading online trainings: %w", err)
	}
	args = []any{}
	where = activityScope(sc, liveClusters, l, &args)
	args = append(args, rules.Engine.CompletedWorkStatuses)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT a.focus_intervention, COUNT(a.id), COUNT(a.id) FILTER (WHERE a.status = ANY($%d))
FROM activity a WHERE a.focus_intervention IS NOT NULL AND a.focus_intervention <> '' AND `, len(args))+where+`
GROUP BY 1`, args...)
	if err != nil {
		return w, fmt.Errorf("schoolprofile: reading the work by intervention: %w", err)
	}
	for rows.Next() {
		var key string
		var planned, completed int
		if err := rows.Scan(&key, &planned, &completed); err != nil {
			rows.Close()
			return w, err
		}
		w.focus[key] = [2]int{planned, completed}
	}
	rows.Close()

	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment WHERE school_id = $1 AND status = ANY($2))`,
		sc.ID, rules.Gate.UnscheduledHandoverStatuses).Scan(&w.awaitingPartner); err != nil {
		return w, fmt.Errorf("schoolprofile: reading hand-overs: %w", err)
	}
	return w, nil
}

// clusterSets are the school's cluster as the engine reads its work (by its
// id, live or not) and as the records read it (_work: the live cluster).
func (s *Service) clusterSets(ctx context.Context, sc school) (all, live []string, err error) {
	all, live = []string{}, []string{}
	if sc.ClusterID == "" {
		return all, live, nil
	}
	all = append(all, sc.ClusterID)
	var isLive bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cluster WHERE id = $1 AND deleted_at IS NULL)`, sc.ClusterID).Scan(&isLive); err != nil {
		return nil, nil, fmt.Errorf("schoolprofile: reading the cluster: %w", err)
	}
	if isLive {
		live = append(live, sc.ClusterID)
	}
	return all, live, nil
}

// registerCounts are the register's online invitations and attendance
// (profile_records.channels): every row of the school at a completed online
// training session, invited or attended.
func (s *Service) registerCounts(ctx context.Context, sc school, l lens, w *work) error {
	args := []any{sc.ID, rules.Engine.CompletedWorkStatuses, l.fy, rules.Engine.TrainingTypes}
	inWindow := l.window.sql(&args)
	return s.db.QueryRow(ctx, `
SELECT COUNT(c.activity_id) FILTER (WHERE a.programme_delivery_mode = 'online' AND c.invited),
  COUNT(c.activity_id) FILTER (WHERE a.programme_delivery_mode = 'online' AND c.attended)
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
WHERE c.school_id = $1 AND a.status = ANY($2) AND a.school_id IS NULL AND a.fy = $3 AND a.deleted_at IS NULL
  AND a.activity_type = ANY($4) AND `+inWindow, args...).Scan(&w.onlineInvited, &w.onlineAttended)
}

// pick is the best performing or the struggling intervention, and what
// chose it.
type pick struct {
	row   ivRow
	basis string
}

// picks is engine._intervention_picks.
func picks(rows []ivRow) (best, struggling *pick) {
	measured := []ivRow{}
	for _, r := range rows {
		if r.current != nil {
			measured = append(measured, r)
		}
	}
	if len(measured) == 0 {
		return nil, nil
	}
	changeOr0 := func(r ivRow) float64 {
		if r.verdict.delta == nil {
			return 0
		}
		return *r.verdict.delta
	}
	// Python's max and min keep the first of equals.
	better := func(a, b [2]float64) bool { return a[0] > b[0] || (a[0] == b[0] && a[1] > b[1]) }
	worse := func(a, b [2]float64) bool { return a[0] < b[0] || (a[0] == b[0] && a[1] < b[1]) }
	choose := func(list []ivRow, key func(ivRow) [2]float64, beats func(a, b [2]float64) bool) ivRow {
		chosen := list[0]
		for _, r := range list[1:] {
			if beats(key(r), key(chosen)) {
				chosen = r
			}
		}
		return chosen
	}
	byChange := func(r ivRow) [2]float64 { return [2]float64{changeOr0(r), *r.current} }
	byScore := func(r ivRow) [2]float64 { return [2]float64{*r.current, changeOr0(r)} }
	improved := []ivRow{}
	for _, r := range measured {
		if r.verdict.status == "improved" {
			improved = append(improved, r)
		}
	}
	if len(improved) > 0 {
		best = &pick{row: choose(improved, byChange, better), basis: "change"}
	} else {
		best = &pick{row: choose(measured, byScore, better), basis: "score"}
	}
	others, declined := []ivRow{}, []ivRow{}
	for _, r := range measured {
		if r.key != best.row.key {
			others = append(others, r)
			if r.verdict.status == "declined" {
				declined = append(declined, r)
			}
		}
	}
	if len(others) == 0 {
		return best, nil
	}
	if len(declined) > 0 {
		return best, &pick{row: choose(declined, byChange, worse), basis: "change"}
	}
	return best, &pick{row: choose(others, byScore, worse), basis: "score"}
}

func (s *Service) overviewTab(ctx context.Context, r btReader, sc school, l lens, now time.Time) ([]*screensv1.PageBlock, error) {
	d := r.doors
	book, err := s.ruleBook(ctx)
	if err != nil {
		return nil, err
	}
	cmp, err := s.interventionComparison(ctx, sc.ID, l.fy)
	if err != nil {
		return nil, err
	}
	for i := range cmp.rows {
		cmp.rows[i].verdict = book.interventionChange(cmp.rows[i].key, cmp.rows[i].previous, cmp.rows[i].current)
	}
	overall := book.overallChange(cmp.previous, cmp.current)
	scores, err := s.schoolYearScores(ctx, []string{sc.ID}, l.fy)
	if err != nil {
		return nil, err
	}
	mine := scores[sc.ID]
	schoolVerdict := book.overallChange(mine.previous, mine.current)
	w, err := s.work(ctx, sc, l, now)
	if err != nil {
		return nil, err
	}
	stories, err := s.storyList(ctx, sc, l)
	if err != nil {
		return nil, err
	}
	before := previousFY(l.fy)
	was, hasWas, nowEnrolment, hasNow, err := s.enrolmentYears(ctx, sc.ID, l.fy, before)
	if err != nil {
		return nil, err
	}
	learning, err := s.learning(ctx, sc.ID, l.fy, before)
	if err != nil {
		return nil, err
	}
	var clusterLive bool
	if sc.ClusterID != "" {
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cluster WHERE id = $1 AND deleted_at IS NULL)`, sc.ClusterID).Scan(&clusterLive); err != nil {
			return nil, err
		}
	}

	need := rules.Engine.Requirements[sc.Type]
	label, previousLabel := fyLabel(l.fy), fyLabel(before)
	records := l.records()
	tabURL := func(section, show string) string {
		u := l.href() + "tab=" + section + "&fy=" + l.fy
		if show != "" {
			u += "&show=" + show
		}
		return u
	}

	// ── Portfolio and attention ────────────────────────────────────────────
	assessed, assessable := 0, 0
	if need.TakesSSA {
		assessable = 1
		if mine.current != nil {
			assessed = 1
		}
	}
	noSSA := need.TakesSSA && mine.current == nil
	unplanned := w.anyHere == 0
	declined := schoolVerdict.status == "declined"
	interventionsDeclined := 0
	for _, r := range cmp.rows {
		if r.verdict.status == "declined" {
			interventionsDeclined++
		}
	}
	type line struct {
		count           int
		one, many, when string
		tab, show, what string
	}
	flag := func(b bool) int {
		if b {
			return 1
		}
		return 0
	}
	lines := []line{
		{flag(noSSA), "school has no confirmed SSA", "schools have no confirmed SSA", "in " + label, "schools", "no_ssa", ""},
		{flag(unplanned), "school has nothing planned", "schools have nothing planned", "in " + label, "schools", "unplanned", ""},
		{flag(declined), "school's SSA declined", "schools' SSA declined", "since " + previousLabel, "schools", "declined", ""},
		{flag(declined && clusterLive), "cluster's SSA declined", "clusters' SSA declined", "since " + previousLabel, "clusters", "", ""},
		{interventionsDeclined, "SSA intervention declined", "SSA interventions declined", "since " + previousLabel, "ssa", "", ""},
		{flag(need.Trainings > 0 && w.trainingsHere == 0), "school due a training has none in the plan", "schools due a training have none in the plan", "in " + label, "schools", "no_training", ""},
		{flag(need.Visits > 0 && w.visitsHere == 0), "school due a visit has none in the plan", "schools due a visit have none in the plan", "in " + label, "schools", "no_visit", ""},
		{flag(w.awaitingPartner), "school is waiting for a partner's date", "schools are waiting for a partner's date", "", "schools", "awaiting_partner", ""},
		{w.meetings.overdue, "cluster meeting is past its date and not held", "cluster meetings are past their date and not held", "", "activities", "", "meetings_overdue"},
		{w.visits.overdue, "visit is past its date and not done", "visits are past their date and not done", "", "activities", "", "visits_overdue"},
		{w.trainings.overdue, "training is past its date and not delivered", "trainings are past their date and not delivered", "", "activities", "", "trainings_overdue"},
		{w.projectOverdue, "project activity is past its date and not done", "project activities are past their date and not done", "", "activities", "", "project_overdue"},
	}
	attention := []*screensv1.PageLink{}
	for _, ln := range lines {
		if ln.count == 0 {
			continue
		}
		words := ln.many
		if ln.count == 1 {
			words = ln.one
		}
		href := tabURL(ln.tab, ln.show)
		if ln.what != "" {
			href = records + ln.what
		}
		attention = append(attention, &screensv1.PageLink{
			Text: strings.TrimSpace(intcomma(ln.count) + " " + words + " " + ln.when), Href: href,
		})
	}

	// ── Strips ─────────────────────────────────────────────────────────────
	enrolment := 0
	if sc.Enrollment != nil {
		enrolment = *sc.Enrollment
	}
	ssaHelper := "previous 0"
	if cmp.previous != nil {
		ssaHelper = "previous " + twoPlaces(*cmp.previous)
	}
	if overall.delta != nil {
		ssaHelper += " · " + signedTwoPlaces(*overall.delta)
	}
	currentScore := 0.0
	if cmp.current != nil {
		currentScore = *cmp.current
	}
	growth, compared := "0%", 0
	if hasWas && hasNow {
		compared = 1
		if was != 0 {
			g := pyRound(100*float64(nowEnrolment-was)/float64(was), 1)
			growth = pyFloat(g) + "%"
			if g > 0 {
				growth = "+" + growth
			}
		}
	}
	results, learnCompared, learnImproved := "0%", 0, 0
	if learning.after != nil {
		results = pyFloat(*learning.after) + "%"
	}
	if learning.before != nil && learning.after != nil {
		learnCompared = 1
		if pyRound(*learning.after-*learning.before, 1) > 0 {
			learnImproved = 1
		}
	}
	approved, waiting := 0, 0
	for _, st := range stories {
		if st.state == rules.Engine.StoryStatuses.Approved {
			approved++
		}
		for _, wait := range rules.Engine.StoryStatuses.Waiting {
			if st.state == wait {
				waiting++
			}
		}
	}
	schoolsTrained := flag(w.trainedHere || w.groupTrained)
	performance := strip("Performance And Impact",
		kpi{label: "Enrolment", value: intcomma(enrolment), link: records + "enrolment", helper: "learners on the school record"},
		kpi{label: "SSA Score", value: twoPlaces(currentScore), link: tabURL("ssa", ""), helper: ssaHelper},
		kpi{label: "Schools Assessed", value: intcomma(assessed), link: records + "ssa", helper: "of " + intcomma(assessable) + " in " + label},
		kpi{label: "Teachers Trained", value: intcomma(w.teachers + w.groupTeachers), link: records + "teachers_trained",
			helper: intcomma(w.teachers) + " in school · " + intcomma(w.groupTeachers) + " at group trainings"},
		kpi{label: "School Leaders Trained", value: intcomma(w.leaders + w.groupLeaders), link: records + "leaders_trained",
			helper: intcomma(w.leaders) + " in school · " + intcomma(w.groupLeaders) + " at group trainings"},
		kpi{label: "Enrolment Growth", value: growth, link: records + "enrolment_growth",
			helper: intcomma(compared) + " school" + plural(compared) + " with both years"},
		kpi{label: "Learning Results", value: results, link: records + "learning",
			helper: intcomma(learnCompared) + " school" + plural(learnCompared) + " compared · " + intcomma(learnImproved) + " improved"},
		kpi{label: "Change Stories", value: intcomma(len(stories)), link: records + "stories",
			helper: intcomma(approved) + " approved · " + intcomma(waiting) + " with a reviewer"},
	)
	rate := 0
	if w.onlineInvited > 0 {
		rate = int(math.RoundToEven(float64(w.onlineAttended) * 100 / float64(w.onlineInvited)))
	}
	operations := strip("Operations",
		kpi{label: "Visits Completed", value: intcomma(w.visits.completed), link: records + "visits_done",
			helper: "of " + intcomma(w.visits.planned) + " in the plan · " + intcomma(need.Visits) + " expected"},
		kpi{label: "Trainings Completed", value: intcomma(w.trainings.completed), link: records + "trainings_done",
			helper: "of " + intcomma(w.trainings.planned) + " in the plan · " + intcomma(schoolsTrained) + " school" + plural(schoolsTrained) + " trained"},
		kpi{label: "Online Trainings", value: intcomma(w.onlineDone), link: records + "trainings_online",
			helper: "of " + intcomma(w.onlinePlanned) + " in the plan · " + strconv.Itoa(rate) + "% attendance"},
		kpi{label: "Cluster Meetings Held", value: intcomma(w.meetings.completed), link: records + "meetings_done",
			helper: "of " + intcomma(w.meetings.planned) + " in the plan"},
		kpi{label: "At Cluster Meetings", value: intcomma(w.meetingTeachers + w.meetingLeaders), link: records + "at_meetings",
			helper: intcomma(w.meetingTeachers) + " teachers · " + intcomma(w.meetingLeaders) + " leaders"},
		kpi{label: "Nothing Planned", value: intcomma(flag(unplanned)), link: tabURL("", "unplanned"), helper: "schools with no activity in " + label},
	)
	blocks := []*screensv1.PageBlock{performance, operations}
	if d.Loans {
		finance, err := s.financeOf(ctx, r, sc)
		if err != nil {
			return nil, err
		}
		blocks = append(blocks, finance.strip(records))
	}

	// ── Best and struggling intervention ──────────────────────────────────
	best, struggling := picks(cmp.rows)
	table := &screensv1.PageTable{
		Title: "Best Performing And Struggling Intervention", Subtitle: previousLabel + " to " + label,
		Columns: []*screensv1.PageColumn{{Label: "Standing"}, {Label: "Intervention"}, {Label: "Previous", Numeric: true},
			{Label: "Current", Numeric: true}, {Label: "Change", Numeric: true}, {Label: "Trend"}, {Label: "Chosen By"},
			{Label: "Supporting Activities", Numeric: true}, {Label: "Recommended"}},
		Footnote: rules.Engine.InterventionMethod,
	}
	for _, slot := range []struct {
		pick           *pick
		standing, tone string
		isBest         bool
	}{{best, "Best performing", "success", true}, {struggling, "Struggling", "danger", false}} {
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: interventionRow(slot.pick, slot.standing, slot.tone, slot.isBest, best != nil, noSSA, w, label, records)})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}})

	// ── The latest stories ─────────────────────────────────────────────────
	if len(stories) > 0 {
		blocks = append(blocks, latestStories(stories, approved, label, records))
	}

	// ── The insight rail ───────────────────────────────────────────────────
	meters := []*screensv1.PageMeter{}
	for _, r := range cmp.rows {
		v := 0.0
		if r.current != nil {
			v = *r.current
		}
		share := math.RoundToEven(v * 100 / 10)
		meters = append(meters, &screensv1.PageMeter{
			Label: r.label, Value: strconv.FormatFloat(v, 'f', 1, 64), Fraction: pyRound(share/100, 4),
			Href: records + "intervention&key=" + url.QueryEscape(r.key),
		})
	}
	previous := 0.0
	if cmp.previous != nil {
		previous = *cmp.previous
	}
	moved := "0.00"
	if overall.delta != nil && *overall.delta != 0 {
		moved = signedTwoPlaces(*overall.delta)
	}
	subtitle := label
	if l.window.label != "" {
		subtitle += " · " + l.window.label
	}
	attentionPart := &screensv1.PageRailPart{Key: "attention", Title: "Needs Attention", Meters: []*screensv1.PageMeter{}, Links: attention}
	if len(attention) == 0 {
		attentionPart.Note = "Nothing needs attention in " + label + "."
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Rail{Rail: &screensv1.PageRail{
		Title: "Profile Insights", Subtitle: subtitle,
		Parts: []*screensv1.PageRailPart{
			{
				Key: "ssa", Title: "SSA Performance", Figure: strconv.FormatFloat(currentScore, 'f', 2, 64), FigureHref: tabURL("ssa", ""),
				FigureNote: "baseline " + strconv.FormatFloat(previous, 'f', 2, 64) + " · " + moved + " since " + previousLabel,
				Meters:     meters, Note: "Each intervention out of 10; a line opens its schools.", Links: []*screensv1.PageLink{},
			},
			attentionPart,
		},
	}}})
	return blocks, nil
}

// interventionRow is partials/profiles/_intervention_row.html.
func interventionRow(p *pick, standing, tone string, isBest, hasBest, noSSA bool, w work, label, records string) []*screensv1.PageCell {
	cells := []*screensv1.PageCell{{Text: standing, Tone: tone}}
	if p == nil {
		text := "No intervention has a confirmed score in " + label + " yet"
		if !isBest && hasBest {
			text = "Only one intervention has a confirmed score in " + label
		}
		recommended := "—"
		if noSSA {
			recommended = "Collect this year's SSA"
		}
		return append(cells, &screensv1.PageCell{Text: text}, &screensv1.PageCell{Text: "0"}, &screensv1.PageCell{Text: "0"},
			&screensv1.PageCell{Text: "0"}, &screensv1.PageCell{Text: "—"}, &screensv1.PageCell{Text: "—"},
			&screensv1.PageCell{Text: "0 / 0"}, &screensv1.PageCell{Text: recommended})
	}
	r := p.row
	link := records + "intervention&key=" + url.QueryEscape(r.key)
	focus := w.focus[r.key]
	changeCell := &screensv1.PageCell{Text: "—"}
	if r.verdict.delta != nil {
		changeCell = &screensv1.PageCell{Text: signedTwoPlaces(*r.verdict.delta), Tone: r.verdict.tone()}
	}
	chosen := "Score this year"
	if p.basis == "change" {
		chosen = "Change since the previous year"
	}
	recommended := "Keep what works"
	switch {
	case isBest:
	case focus[0] == 0:
		recommended = "Plan a visit or a training with this focus"
	case focus[1] > 0:
		recommended = "Follow up what that work found"
	default:
		recommended = "Deliver the work planned for it"
	}
	return append(cells,
		&screensv1.PageCell{Text: r.label, Href: link, Strong: true},
		&screensv1.PageCell{Text: score(r.previous)},
		&screensv1.PageCell{Text: twoPlaces(*r.current), Strong: true},
		changeCell,
		&screensv1.PageCell{Text: r.verdict.label()},
		&screensv1.PageCell{Text: chosen},
		&screensv1.PageCell{Text: intcomma(focus[1]) + " / " + intcomma(focus[0]), Href: link},
		&screensv1.PageCell{Text: recommended})
}

// latestStories is the Overview's "Latest Change Stories": the five newest.
func latestStories(stories []story, approved int, label, records string) *screensv1.PageBlock {
	areas := map[string]int{}
	order := []string{}
	for _, st := range stories {
		area := rules.SSAInterventions[st.area]
		if area == "" {
			area = "No intervention tagged"
		}
		if areas[area] == 0 {
			order = append(order, area)
		}
		areas[area]++
	}
	sortAreas(order, areas)
	parts := []string{}
	for _, a := range order {
		parts = append(parts, intcomma(areas[a])+" "+a)
	}
	table := &screensv1.PageTable{
		Title:    "Latest Change Stories",
		Subtitle: intcomma(len(stories)) + " in " + label + " · " + intcomma(approved) + " approved",
		Columns: []*screensv1.PageColumn{{Label: "Story Date"}, {Label: "Title"}, {Label: "School ID"}, {Label: "School"},
			{Label: "Intervention"}, {Label: "Status"}},
		Footnote: strings.Join(parts, " · ") + ". Only an approved story counts as evidence.",
	}
	for _, st := range stories[:min(5, len(stories))] {
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: jMY(st.day)}, {Text: st.title}, {Text: orDash(st.code)}, {Text: orDash(st.schoolName)},
			{Text: orDash(rules.SSAInterventions[st.area])}, {Text: status(st.state)},
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}
}

// sortAreas orders story areas most first, then by name.
func sortAreas(names []string, counts map[string]int) {
	sort.SliceStable(names, func(i, j int) bool {
		if counts[names[i]] != counts[names[j]] {
			return counts[names[i]] > counts[names[j]]
		}
		return names[i] < names[j]
	})
}
