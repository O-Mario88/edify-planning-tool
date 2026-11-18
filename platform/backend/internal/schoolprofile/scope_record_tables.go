package schoolprofile

import (
	"context"
	"fmt"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The record tables behind the profile's other figures
// (profile_records._enrolment_tables, _learning_tables, _ssa_tables,
// _intervention_tables, _story_tables, _handover_tables, _partner_tables,
// _trained_tables), each a scopeRecordTable drawn as _records.html draws it.

// scopeRecordTable is profile_records._table: its key (the page parameter is
// "rec_" and it), title, columns (label, kind), rows of cells already
// worded as _cell.html words them, the sums a closing line carries, and the
// note under it.
type scopeRecordTable struct {
	key, title, footer string
	columns            [][2]string
	rows               [][]*screensv1.PageCell
	total              []string
}

// block is the table fifty records a page; the sums close every page.
func (t scopeRecordTable) block(l lens) *screensv1.PageBlock {
	subtitle := intcomma(len(t.rows)) + " record" + plural(len(t.rows)) + " · " + fyLabel(l.fy)
	if l.window.label != "" {
		subtitle += " · " + l.window.label
	}
	out := &screensv1.PageTable{Title: t.title, Subtitle: subtitle}
	if len(t.rows) == 0 {
		out.EmptyMessage = "No record yet: the figure is 0."
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: out}}
	}
	for _, c := range t.columns {
		out.Columns = append(out.Columns, &screensv1.PageColumn{Label: c[0], Numeric: c[1] == "num"})
	}
	page := tablepager.Paginate(len(t.rows), tablePageSize, l.query, "rec_"+t.key)
	for _, cells := range t.rows[page.Start:page.End] {
		out.Rows = append(out.Rows, &screensv1.PageRow{Cells: cells})
	}
	if t.total != nil {
		cells := []*screensv1.PageCell{}
		for _, v := range t.total {
			cells = append(cells, &screensv1.PageCell{Text: v, Strong: true})
		}
		out.Rows = append(out.Rows, &screensv1.PageRow{Cells: cells})
	}
	out.Footnote = t.footer
	if page.Pager != nil {
		out.Pager, out.Footnote = page.Pager, page.Pager.Summary
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: out}}
}

// Cells as _cell.html words them.
func recText(text, href string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: orDash(text), Href: href}
}

func recDate(day *time.Time, href string) *screensv1.PageCell {
	if day == nil {
		return &screensv1.PageCell{Text: "—", Href: href}
	}
	return &screensv1.PageCell{Text: jMY(*day), Href: href}
}

func recNum(n int) *screensv1.PageCell { return &screensv1.PageCell{Text: intcomma(n)} }

func recOpt(n *int, tone string) *screensv1.PageCell {
	if n == nil {
		return &screensv1.PageCell{Text: "—", Tone: tone}
	}
	return &screensv1.PageCell{Text: intcomma(*n), Tone: tone}
}

func recScore(v *float64) *screensv1.PageCell { return &screensv1.PageCell{Text: score(v)} }

func recSchool(x scopeSchool) []*screensv1.PageCell {
	return []*screensv1.PageCell{recText(x.code, ""), recText(x.name, "/schools/"+x.id)}
}

// enrolmentTable is _enrolment_tables: each school's recorded enrolment in
// the year and the one before; with comparedOnly only the schools with both.
func (s *Service) enrolmentTable(ctx context.Context, pr *scopeProfile, l lens, comparedOnly bool) (scopeRecordTable, error) {
	before := previousFY(l.fy)
	rows, err := s.db.Query(ctx, `
SELECT school_id, fy, enrollment FROM school_enrollment_history
WHERE school_id = ANY($1) AND fy = ANY($2) ORDER BY school_id, fy, recorded_at`, idsOf(pr.schools), []string{l.fy, before})
	if err != nil {
		return scopeRecordTable{}, fmt.Errorf("schoolprofile: reading the enrolment history: %w", err)
	}
	years := map[string]map[string]int{}
	for rows.Next() {
		var school, year string
		var n int
		if err := rows.Scan(&school, &year, &n); err != nil {
			rows.Close()
			return scopeRecordTable{}, err
		}
		if years[school] == nil {
			years[school] = map[string]int{}
		}
		years[school][year] = n
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return scopeRecordTable{}, err
	}
	title := "Enrolment"
	if comparedOnly {
		title = "Enrolment growth"
	}
	t := scopeRecordTable{key: "enrolment", title: title + ": school by school",
		columns: [][2]string{{"School ID", ""}, {"School", ""}, {fyLabel(before), "num"}, {fyLabel(l.fy), "num"}, {"Change", "num"}, {"On Profile", "num"}},
		footer: "A school is compared only with a figure recorded in both years. On Profile is the enrolment the school's record " +
			"holds now; the profile's Enrolment figure is these added up."}
	for _, x := range pr.schools {
		var was, now, change *int
		if v, ok := years[x.id][before]; ok {
			was = &v
		}
		if v, ok := years[x.id][l.fy]; ok {
			now = &v
		}
		if comparedOnly && (was == nil || now == nil) {
			continue
		}
		tone := ""
		if was != nil && now != nil {
			c := *now - *was
			change = &c
			switch {
			case c > 0:
				tone = "success"
			case c < 0:
				tone = "danger"
			}
		}
		var onProfile *int
		if x.hasEnrolment {
			v := x.enrolment
			onProfile = &v
		}
		t.rows = append(t.rows, append(recSchool(x), recOpt(was, ""), recOpt(now, ""), recOpt(change, tone), recOpt(onProfile, "")))
	}
	return t, nil
}

// learningTable is _learning_tables: every learning assessment of the
// scope's schools in the year and the one before.
func (s *Service) learningTable(ctx context.Context, pr *scopeProfile, l lens) (scopeRecordTable, error) {
	t := scopeRecordTable{key: "learning", title: "Learning results: the assessments",
		columns: [][2]string{{"Date", "date"}, {"School ID", ""}, {"School", ""}, {"Assessment", ""}, {"Subject · Class", ""},
			{"Learners Tested", "num"}, {"Mean Score", "num"}, {"Verification", ""}},
		footer: "The profile's figure reads confirmed results only, and compares a school only when it has them in both years."}
	rows, err := s.db.Query(ctx, `
SELECT r.school_id, COALESCE(sc.name, ''), COALESCE(sc.school_id, ''), r.assessed_on, COALESCE(r.assessment_type, ''),
  COALESCE(r.subject, ''), COALESCE(r.grade_level, ''), r.learners_tested, r.mean_score::float8, r.max_score::float8,
  COALESCE(r.verification_status, '')
FROM impact_learning_result r LEFT JOIN school sc ON sc.id = r.school_id
WHERE r.school_id = ANY($1) AND r.fy = ANY($2) AND r.deleted_at IS NULL
ORDER BY r.assessed_on DESC, sc.name, r.id`, idsOf(pr.schools), []string{l.fy, previousFY(l.fy)})
	if err != nil {
		return t, fmt.Errorf("schoolprofile: reading the learning results: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var school, name, code, kind, subject, grade, status string
		var on *time.Time
		var learners *int
		var mean, maximum *float64
		if err := rows.Scan(&school, &name, &code, &on, &kind, &subject, &grade, &learners, &mean, &maximum, &status); err != nil {
			return t, err
		}
		share := &screensv1.PageCell{Text: "—"}
		if mean != nil && maximum != nil && *maximum != 0 {
			share.Text = pyFloat(pyRound(*mean*100 / *maximum, 1)) + "%"
		}
		both := subject
		if grade != "" {
			if both != "" {
				both += " · "
			}
			both += grade
		}
		t.rows = append(t.rows, []*screensv1.PageCell{recDate(on, ""), recText(code, ""), recText(name, "/schools/"+school),
			recText(recordStatus(kind), ""), recText(both, ""), recOpt(learners, ""), share, recText(recordStatus(status), "")})
	}
	return t, rows.Err()
}

// ssaTable is _ssa_tables: every confirmed SSA record of the scope's
// schools in the year, newest first.
func (s *Service) ssaTable(ctx context.Context, pr *scopeProfile, l lens) (scopeRecordTable, error) {
	label, previousLabel := fyLabel(l.fy), fyLabel(previousFY(l.fy))
	t := scopeRecordTable{key: "ssa", title: "Confirmed SSA records, " + label,
		columns: [][2]string{{"Date Of SSA", "date"}, {"School ID", ""}, {"School", ""}, {"Average Score", "num"},
			{"Previous (" + previousLabel + ")", "num"}, {"Verification", ""}, {"Collected By", ""}},
		footer: "The profile's average is the mean of each school's latest confirmed record of the year, so a school assessed twice counts once."}
	rows, err := s.db.Query(ctx, `
SELECT r.school_id, COALESCE(sc.name, ''), COALESCE(sc.school_id, ''), r.date_of_ssa, r.average_score::float8,
  COALESCE(r.verification_status, ''), COALESCE(r.collector_type, '')
FROM ssa_record r LEFT JOIN school sc ON sc.id = r.school_id
WHERE r.school_id = ANY($1) AND r.fy = $2 AND r.deleted_at IS NULL AND r.verification_status = ANY($3)
ORDER BY r.date_of_ssa DESC, sc.name, r.id`, idsOf(pr.schools), l.fy, rules.SSACurrentStatuses)
	if err != nil {
		return t, fmt.Errorf("schoolprofile: reading the SSA records: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var school, name, code, status, collector string
		var on *time.Time
		var average *float64
		if err := rows.Scan(&school, &name, &code, &on, &average, &status, &collector); err != nil {
			return t, err
		}
		t.rows = append(t.rows, []*screensv1.PageCell{recDate(on, ""), recText(code, ""), recText(name, "/schools/"+school+"?tab=ssa"),
			recScore(average), recScore(pr.scores[school].previous), recText(recordStatus(status), ""), recText(recordStatus(collector), "")})
	}
	return t, rows.Err()
}

// interventionTables is _intervention_tables: each school's score for the
// intervention in both years and the change, then the year's work naming it.
func (s *Service) interventionTables(ctx context.Context, pr *scopeProfile, l lens, key string, today time.Time) ([]scopeRecordTable, *screensv1.PageBlock, bool, error) {
	label, ok := rules.SSAInterventions[key]
	if !ok {
		return nil, nil, true, nil
	}
	before := previousFY(l.fy)
	rows, err := s.db.Query(ctx, `
SELECT x.school_id, x.fy, sc.score::float8
FROM (SELECT DISTINCT ON (r.school_id, r.fy) r.id, r.school_id, r.fy FROM ssa_record r
  WHERE r.school_id = ANY($1) AND r.fy = ANY($2) AND r.deleted_at IS NULL AND r.verification_status = ANY($3)
  ORDER BY r.school_id, r.fy, r.date_of_ssa DESC, r.created_at DESC, r.id DESC) x
JOIN ssa_score sc ON sc.ssa_record_id = x.id AND sc.intervention = $4 AND sc.score IS NOT NULL`,
		idsOf(pr.schools), []string{l.fy, before}, rules.SSACurrentStatuses, key)
	if err != nil {
		return nil, nil, true, fmt.Errorf("schoolprofile: reading the intervention's scores: %w", err)
	}
	scores := map[string]*yearScore{}
	for rows.Next() {
		var school, year string
		var v float64
		if err := rows.Scan(&school, &year, &v); err != nil {
			rows.Close()
			return nil, nil, true, err
		}
		if scores[school] == nil {
			scores[school] = &yearScore{}
		}
		v = pyRound(v, 2)
		if year == l.fy {
			scores[school].current = &v
		} else {
			scores[school].previous = &v
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, true, err
	}
	t := scopeRecordTable{key: "intervention-schools", title: label + ": school by school",
		columns: [][2]string{{"School ID", ""}, {"School", ""}, {"Previous (" + fyLabel(before) + ")", "num"},
			{"Current (" + fyLabel(l.fy) + ")", "num"}, {"Change", "num"}, {"Status", ""}},
		footer: "A school with no confirmed score for this intervention in either year is not listed."}
	for _, x := range pr.schools {
		score := scores[x.id]
		if score == nil {
			continue
		}
		verdict := pr.book.interventionChange(key, score.previous, score.current)
		changeCell := &screensv1.PageCell{Text: "—", Tone: verdict.tone()}
		if verdict.delta != nil {
			changeCell.Text = signedTwoPlaces(*verdict.delta)
		}
		t.rows = append(t.rows, append(recSchool(x), recScore(score.previous), recScore(score.current), changeCell,
			&screensv1.PageCell{Text: orDash(verdict.label())}))
	}
	// The work that named it: the work records' table over the work whose
	// focus or purpose is the intervention.
	args := []any{}
	live := make([]string, 0, len(pr.clusters))
	for id := range pr.clusters {
		live = append(live, id)
	}
	where := scopeWork(idsOf(pr.schools), live, l.fy, l.window, &args)
	args = append(args, key)
	work, err := s.workRecordsWhere(ctx, where+fmt.Sprintf(" AND (a.focus_intervention = $%[1]d OR a.purpose_intervention = $%[1]d)", len(args)), args)
	if err != nil {
		return nil, nil, true, err
	}
	block, err := s.workTable(ctx, l, "intervention-work", label+": the work that named it", work)
	return []scopeRecordTable{t}, block, true, err
}

// storyTable is _story_tables: the year's stories about the scope's
// schools and clusters, newest first; a draft is its author's own.
func (s *Service) storyTable(ctx context.Context, pr *scopeProfile, l lens, approvedOnly bool) (scopeRecordTable, error) {
	title := "Most Significant Change stories"
	if approvedOnly {
		title += ": approved"
	}
	t := scopeRecordTable{key: "stories", title: title,
		columns: [][2]string{{"Story Date", "date"}, {"Title", ""}, {"School ID", ""}, {"School", ""}, {"Intervention", ""},
			{"Outcome Area", ""}, {"Status", ""}, {"Evidence", ""}},
		footer: "Only an approved story counts as evidence."}
	end, err := yearEnd(l.fy)
	if err != nil {
		return t, err
	}
	live := make([]string, 0, len(pr.clusters))
	for id := range pr.clusters {
		live = append(live, id)
	}
	st := rules.Engine.StoryStatuses
	rows, err := s.db.Query(ctx, `
SELECT m.story_date, COALESCE(m.title, ''), COALESCE(m.school_id, ''), COALESCE(sc.name, ''), COALESCE(sc.school_id, ''),
  COALESCE(m.intervention, ''), COALESCE(m.outcome_area, ''), COALESCE(m.status, ''), COALESCE(m.evidence_uri, '') <> ''
FROM mscs_story m LEFT JOIN school sc ON sc.id = m.school_id
WHERE (m.school_id = ANY($1) OR (m.school_id IS NULL AND m.cluster_id = ANY($2)))
  AND m.story_date >= $3 AND m.story_date < $4 AND m.status IS DISTINCT FROM $5 AND (NOT $6 OR m.status = $7)
ORDER BY m.story_date DESC, m.created_at DESC, m.id`, idsOf(pr.schools), live,
		time.Date(end-1, time.October, 1, 0, 0, 0, 0, time.UTC), time.Date(end, time.October, 1, 0, 0, 0, 0, time.UTC),
		st.Draft, approvedOnly, st.Approved)
	if err != nil {
		return t, fmt.Errorf("schoolprofile: reading the profile's stories: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var on *time.Time
		var title, school, name, code, intervention, area, status string
		var evidence bool
		if err := rows.Scan(&on, &title, &school, &name, &code, &intervention, &area, &status, &evidence); err != nil {
			return t, err
		}
		href := ""
		if school != "" {
			href = "/schools/" + school
		}
		statusCell := recText(recordStatus(status), "")
		if status == st.Approved {
			statusCell.Tone = "success"
		}
		yes := "No"
		if evidence {
			yes = "Yes"
		}
		t.rows = append(t.rows, []*screensv1.PageCell{recDate(on, ""), recText(title, ""), recText(code, ""), recText(name, href),
			recText(rules.SSAInterventions[intervention], ""), recText(recordStatus(area), ""), statusCell, recText(yes, "")})
	}
	return t, rows.Err()
}

// handoverTable is _handover_tables: the hand-overs at the scope's schools
// not taken back, at one stage.
func (s *Service) handoverTable(ctx context.Context, pr *scopeProfile, stage string) (scopeRecordTable, error) {
	title, filter := "Hand-overs a partner holds", "TRUE"
	args := []any{idsOf(pr.schools), rules.Engine.HandoverReleasedStatuses}
	switch stage {
	case "awaiting":
		args = append(args, rules.Gate.UnscheduledHandoverStatuses)
		title, filter = "Awaiting the partner's date", "pa.status = ANY($3)"
	case "dated":
		args = append(args, rules.Gate.UnscheduledHandoverStatuses, rules.Engine.HandoverCompletedStatus)
		title, filter = "Dated by the partner", "NOT (pa.status = ANY($3)) AND pa.status IS DISTINCT FROM $4"
	case "completed":
		args = append(args, rules.Engine.HandoverCompletedStatus)
		title, filter = "Completed by the partner", "pa.status = $3"
	}
	t := scopeRecordTable{key: "handovers", title: title,
		columns: [][2]string{{"Assigned On", "date"}, {"School ID", ""}, {"School", ""}, {"Partner", ""}, {"Work", ""},
			{"Partner's Date", "date"}, {"Status", ""}}}
	rows, err := s.db.Query(ctx, `
SELECT pa.created_at, COALESCE(pa.school_id, ''), COALESCE(sc.name, ''), COALESCE(sc.school_id, ''), COALESCE(pa.partner_id, ''),
  COALESCE(p.name, ''), COALESCE(pa.expected_activity_type, ''), pa.scheduled_date, COALESCE(pa.scheduled_activity_id, ''),
  COALESCE(pa.status, '')
FROM partner_assignment pa LEFT JOIN school sc ON sc.id = pa.school_id LEFT JOIN partner p ON p.id = pa.partner_id
WHERE pa.school_id = ANY($1) AND NOT (pa.status = ANY($2)) AND `+filter+`
ORDER BY pa.created_at DESC, pa.id`, args...)
	if err != nil {
		return t, fmt.Errorf("schoolprofile: reading the profile's hand-overs: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var created *time.Time
		var school, name, code, partner, partnerName, kind, activity, status string
		var scheduled *time.Time
		if err := rows.Scan(&created, &school, &name, &code, &partner, &partnerName, &kind, &scheduled, &activity, &status); err != nil {
			return t, err
		}
		var assigned *time.Time
		if created != nil {
			// created_at.date(): the stored moment's own (UTC) day.
			d := created.UTC()
			d = time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, time.UTC)
			assigned = &d
		}
		dated := ""
		if activity != "" {
			dated = "/activities/" + activity
		}
		work := rules.Engine.Scope.ActivityTypeLabels[kind]
		if work == "" {
			work = recordStatus(kind)
		}
		t.rows = append(t.rows, []*screensv1.PageCell{recDate(assigned, ""), recText(code, ""), recText(name, "/schools/"+school),
			recText(partnerName, "/partners/"+partner), recText(work, ""), recDate(scheduled, dated), recText(recordStatus(status), "")})
	}
	return t, rows.Err()
}

// partnerTable is _partner_tables: each Partner holding a hand-over at the
// scope's schools, with its schools and hand-overs.
func (s *Service) partnerTable(ctx context.Context, pr *scopeProfile) (scopeRecordTable, error) {
	t := scopeRecordTable{key: "partners", title: "Partners serving these schools",
		columns: [][2]string{{"Partner", ""}, {"Schools", "num"}, {"Hand-overs", "num"}}}
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(pa.partner_id, ''), COALESCE(p.name, ''), count(DISTINCT pa.school_id), count(pa.id)
FROM partner_assignment pa LEFT JOIN partner p ON p.id = pa.partner_id
WHERE pa.school_id = ANY($1) AND NOT (pa.status = ANY($2))
GROUP BY pa.partner_id, p.name ORDER BY p.name, pa.partner_id`, idsOf(pr.schools), rules.Engine.HandoverReleasedStatuses)
	if err != nil {
		return t, fmt.Errorf("schoolprofile: reading the profile's partners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		var schools, handovers int
		if err := rows.Scan(&id, &name, &schools, &handovers); err != nil {
			return t, err
		}
		t.rows = append(t.rows, []*screensv1.PageCell{recText(name, "/partners/"+id), recNum(schools), recNum(handovers)})
	}
	return t, rows.Err()
}

func yearEnd(fy string) (int, error) {
	var end int
	if _, err := fmt.Sscanf(fy, "%d", &end); err != nil {
		return 0, fmt.Errorf("schoolprofile: the year %q", fy)
	}
	return end, nil
}

// trainedTables is _trained_tables: the completed sessions that recorded
// teachers or school leaders for the scope's schools, first (for trainings)
// the schools' own in-school trainings, then the register of group
// sessions, each closing with its sums.
func (s *Service) trainedTables(ctx context.Context, pr *scopeProfile, l lens, key, title string, types []string) ([]scopeRecordTable, error) {
	out := []scopeRecordTable{}
	live := make([]string, 0, len(pr.clusters))
	for id := range pr.clusters {
		live = append(live, id)
	}
	ids := idsOf(pr.schools)
	if sameStrings(types, rules.Engine.TrainingTypes) {
		args := []any{}
		where := scopeWork(ids, live, l.fy, l.window, &args)
		args = append(args, rules.Engine.CompletedWorkStatuses, types)
		n := len(args)
		rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT a.id, COALESCE(tc.display_name, ''), COALESCE(a.activity_type, ''), COALESCE(a.school_id, ''), COALESCE(sc.name, ''),
  COALESCE(sc.school_id, ''), COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0),
  a.actual_delivery_date, a.planned_date, a.scheduled_date
FROM activity a LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
WHERE %s AND a.status = ANY($%d) AND a.school_id IS NOT NULL AND a.activity_type = ANY($%d)
ORDER BY a.planned_date DESC, a.id`, where, n-1, n), args...)
		if err != nil {
			return nil, fmt.Errorf("schoolprofile: reading the trainings delivered: %w", err)
		}
		t := scopeRecordTable{key: key + "-in-school", title: title + ": in-school trainings",
			columns: [][2]string{{"Date", "date"}, {"Training", ""}, {"School ID", ""}, {"School", ""}, {"Teachers", "num"}, {"School Leaders", "num"}}}
		teachers, leaders := 0, 0
		for rows.Next() {
			var id, course, kind, school, name, code string
			var tc, lc int
			var actual, planned, scheduled *time.Time
			if err := rows.Scan(&id, &course, &kind, &school, &name, &code, &tc, &lc, &actual, &planned, &scheduled); err != nil {
				rows.Close()
				return nil, err
			}
			label := course
			if label == "" {
				label = activityTypeLabel(kind)
			}
			teachers, leaders = teachers+tc, leaders+lc
			t.rows = append(t.rows, []*screensv1.PageCell{recDate(recordDay(actual, planned, scheduled), ""), recText(label, "/activities/"+id),
				recText(code, ""), recText(name, "/schools/"+school), recNum(tc), recNum(lc)})
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		t.total = []string{"Total", "", "", "", intcomma(teachers), intcomma(leaders)}
		out = append(out, t)
	}
	args := []any{ids, types}
	sessions := sessionsIn(l.fy, l.window, &args)
	rows, err := s.db.Query(ctx, `
SELECT c.activity_id, COALESCE(a.activity_type, ''), COALESCE(a.programme_delivery_mode, ''), COALESCE(tc.display_name, ''),
  a.actual_delivery_date, a.planned_date, COALESCE(a.cluster_id, ''), COALESCE(cl.name, ''), c.school_id, COALESCE(sc.name, ''),
  COALESCE(sc.school_id, ''), COALESCE(c.teachers, 0), COALESCE(c.leaders, 0)
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN school sc ON sc.id = c.school_id
LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
WHERE c.school_id = ANY($1) AND c.attended AND a.activity_type = ANY($2) AND `+sessions+`
ORDER BY a.planned_date DESC, sc.name, c.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the session register: %w", err)
	}
	t := scopeRecordTable{key: key + "-register", title: title + ": the attendance register",
		columns: [][2]string{{"Date", "date"}, {"Session", ""}, {"Cluster", ""}, {"School ID", ""}, {"School", ""},
			{"Teachers", "num"}, {"School Leaders", "num"}}}
	teachers, leaders := 0, 0
	for rows.Next() {
		var activity, kind, mode, course, cluster, clusterName, school, name, code string
		var actual, planned *time.Time
		var tc, lc int
		if err := rows.Scan(&activity, &kind, &mode, &course, &actual, &planned, &cluster, &clusterName, &school, &name, &code, &tc, &lc); err != nil {
			rows.Close()
			return nil, err
		}
		label := course
		if label == "" {
			label = activityTypeLabel(kind)
		}
		if mode == rules.Engine.Scope.OnlineMode {
			label += " (online)"
		}
		day := actual
		if day == nil {
			day = planned
		}
		clusterHref := ""
		if cluster != "" {
			clusterHref = "/clusters/" + cluster
		}
		teachers, leaders = teachers+tc, leaders+lc
		t.rows = append(t.rows, []*screensv1.PageCell{recDate(day, ""), recText(label, "/activities/"+activity),
			recText(clusterName, clusterHref), recText(code, ""), recText(name, "/schools/"+school), recNum(tc), recNum(lc)})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	t.total = []string{"Total", "", "", "", "", intcomma(teachers), intcomma(leaders)}
	return append(out, t), nil
}

// recordDay is profile_records._day: the delivery day, else the planned
// one, else the scheduled moment's own (UTC) day.
func recordDay(actual, planned, scheduled *time.Time) *time.Time {
	switch {
	case actual != nil:
		return actual
	case planned != nil:
		return planned
	case scheduled != nil:
		d := scheduled.UTC()
		d = time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, time.UTC)
		return &d
	}
	return nil
}

// activityTypeLabel is profile_records._type_label.
func activityTypeLabel(kind string) string {
	if label := rules.Engine.Scope.ActivityTypeLabels[kind]; label != "" {
		return label
	}
	return recordStatus(kind)
}

func sameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// caseTable is _case_tables: every Business Transformation case of the
// scope's schools, newest first.
func (s *Service) caseTable(ctx context.Context, pr *scopeProfile) (scopeRecordTable, error) {
	t := scopeRecordTable{key: "cases", title: "Business Transformation cases",
		columns: [][2]string{{"Opened", "date"}, {"School ID", ""}, {"School", ""}, {"Status", ""}}}
	rows, err := s.db.Query(ctx, `
SELECT b.created_at, COALESCE(b.school_id, ''), COALESCE(sc.name, ''), COALESCE(sc.school_id, ''), COALESCE(b.status, '')
FROM bt_case b LEFT JOIN school sc ON sc.id = b.school_id
WHERE b.school_id = ANY($1) AND b.deleted_at IS NULL ORDER BY b.created_at DESC, b.id`, idsOf(pr.schools))
	if err != nil {
		return t, fmt.Errorf("schoolprofile: reading the profile's cases: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var created *time.Time
		var school, name, code, status string
		if err := rows.Scan(&created, &school, &name, &code, &status); err != nil {
			return t, err
		}
		t.rows = append(t.rows, []*screensv1.PageCell{recDate(recordDay(nil, nil, created), ""), recText(code, ""),
			recText(name, "/schools/"+school), recText(recordStatus(status), "")})
	}
	return t, rows.Err()
}

// loanTable is _loan_tables: each loan of the scope's schools the reader
// may read in the loan register (scoped_loans), by school.
func (s *Service) loanTable(ctx context.Context, r btReader, pr *scopeProfile) (scopeRecordTable, error) {
	t := scopeRecordTable{key: "loans", title: "School loans",
		columns: [][2]string{{"Disbursed On", "date"}, {"School ID", ""}, {"School", ""}, {"Lender", ""}, {"Purpose", ""},
			{"Approved", "num"}, {"Disbursed", "num"}, {"Status", ""}}}
	readable, err := s.readableLoanSchools(ctx, r, idsOf(pr.schools))
	if err != nil || len(readable) == 0 {
		return t, err
	}
	rows, err := s.db.Query(ctx, `
SELECT l.disbursement_date, l.school_id, COALESCE(sc.name, ''), COALESCE(sc.school_id, ''), COALESCE(m.name, ''),
  COALESCE(p.label, ''), l.approved_amount::float8, l.disbursed_amount::float8, COALESCE(l.status, '')
FROM bt_mfi_loan l
LEFT JOIN school sc ON sc.id = l.school_id
LEFT JOIN bt_mfi_organization m ON m.id = l.mfi_id
LEFT JOIN bt_loan_purpose p ON p.id = l.purpose_id
WHERE l.school_id = ANY($1) AND l.deleted_at IS NULL AND l.status IS DISTINCT FROM 'canceled'
ORDER BY sc.name, l.disbursement_date DESC, l.created_at DESC`, readable)
	if err != nil {
		return t, fmt.Errorf("schoolprofile: reading the profile's loans: %w", err)
	}
	defer rows.Close()
	money := func(v *float64) *screensv1.PageCell {
		if v == nil {
			return &screensv1.PageCell{Text: "—"}
		}
		whole := 0
		if f, err := fmt.Sscanf(floatformat(*v, 0), "%d", &whole); f != 1 || err != nil {
			whole = 0
		}
		return &screensv1.PageCell{Text: "UGX " + intcomma(whole)}
	}
	tones := map[string]string{"repaid": "success", "active": "info", "disbursed": "info", "defaulted": "danger"}
	for rows.Next() {
		var on *time.Time
		var school, name, code, lender, purpose, status string
		var approved, disbursed *float64
		if err := rows.Scan(&on, &school, &name, &code, &lender, &purpose, &approved, &disbursed, &status); err != nil {
			return t, err
		}
		tone, ok := tones[status]
		if !ok {
			tone = "neutral"
		}
		t.rows = append(t.rows, []*screensv1.PageCell{recDate(on, ""), recText(code, ""), recText(name, "/schools/"+school),
			recText(lender, ""), recText(purpose, ""), money(approved), money(disbursed),
			{Text: orDash(label(rules.BT.LoanStatuses, status)), Tone: tone}})
	}
	return t, rows.Err()
}
