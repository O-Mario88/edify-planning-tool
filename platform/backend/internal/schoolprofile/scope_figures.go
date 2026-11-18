package schoolprofile

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"time"
)

// The figures of a profile of many schools, each read once for the whole
// scope (profile_intelligence.build, people, students, finance and
// profile_records.stories and channels).

// handovers is the scope's hand-overs still with a Partner, by where each
// stands, and the Partners holding them.
type handovers struct {
	assigned, awaiting, completed, partners int
	// awaitingSchools are the schools with a hand-over waiting for a
	// Partner's date.
	awaitingSchools map[string]bool
}

func (h handovers) scheduled() int { return h.assigned - h.awaiting - h.completed }

func (s *Service) scopeHandovers(ctx context.Context, ids []string, partner string) (handovers, error) {
	h := handovers{awaitingSchools: map[string]bool{}}
	if err := s.db.QueryRow(ctx, `
SELECT count(*) FILTER (WHERE NOT (pa.status = ANY($2))),
  count(*) FILTER (WHERE NOT (pa.status = ANY($2)) AND pa.status = ANY($3)),
  count(*) FILTER (WHERE NOT (pa.status = ANY($2)) AND pa.status = $4),
  count(DISTINCT pa.partner_id) FILTER (WHERE NOT (pa.status = ANY($2)))
FROM partner_assignment pa WHERE pa.school_id = ANY($1) AND ($5 = '' OR pa.partner_id = $5)`,
		ids, rules.Engine.HandoverReleasedStatuses, rules.Gate.UnscheduledHandoverStatuses,
		rules.Engine.HandoverCompletedStatus, partner).Scan(&h.assigned, &h.awaiting, &h.completed, &h.partners); err != nil {
		return h, fmt.Errorf("schoolprofile: reading the profile's hand-overs: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT DISTINCT pa.school_id FROM partner_assignment pa
WHERE pa.school_id = ANY($1) AND pa.status = ANY($2) AND ($3 = '' OR pa.partner_id = $3)`,
		ids, rules.Gate.UnscheduledHandoverStatuses, partner)
	if err != nil {
		return h, fmt.Errorf("schoolprofile: reading the hand-overs waiting: %w", err)
	}
	for rows.Next() {
		var school string
		if err := rows.Scan(&school); err != nil {
			rows.Close()
			return h, err
		}
		h.awaitingSchools[school] = true
	}
	rows.Close()
	return h, rows.Err()
}

// scopeProjectIDs is the projects working at the scope's schools
// (engine._projects' rows), by name.
func (s *Service) scopeProjectIDs(ctx context.Context, ids []string) ([]string, error) {
	rows, err := s.db.Query(ctx, `
SELECT p.id FROM project_school_assignment psa JOIN project p ON p.id = psa.project_id
WHERE psa.school_id = ANY($1) GROUP BY p.id, p.name ORDER BY p.name, p.id`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the profile's projects: %w", err)
	}
	out := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		out = append(out, id)
	}
	rows.Close()
	return out, rows.Err()
}

// peopleTrained is engine.people.
type peopleTrained struct {
	teachersInSchool, leadersInSchool, teachersGroup, leadersGroup int
	teachersAtMeetings, leadersAtMeetings, schoolsAtMeetings       int
	schoolsTrained                                                 int
}

func (p peopleTrained) teachers() int { return p.teachersInSchool + p.teachersGroup }
func (p peopleTrained) leaders() int  { return p.leadersInSchool + p.leadersGroup }

func (s *Service) scopePeople(ctx context.Context, ids []string, fy string, w window) (peopleTrained, error) {
	var p peopleTrained
	trained := map[string]bool{}
	args := []any{ids, rules.Engine.CompletedWorkStatuses, rules.Engine.TrainingTypes, fy}
	inWindow := w.sql(&args)
	rows, err := s.db.Query(ctx, `
SELECT a.school_id, COALESCE(sum(a.teachers_attended), 0), COALESCE(sum(a.leaders_attended), 0)
FROM activity a WHERE a.status = ANY($2) AND a.school_id = ANY($1) AND a.activity_type = ANY($3) AND a.fy = $4
  AND a.deleted_at IS NULL AND `+inWindow+` GROUP BY a.school_id`, args...)
	if err != nil {
		return p, fmt.Errorf("schoolprofile: reading trainings delivered: %w", err)
	}
	for rows.Next() {
		var school string
		var t, l int
		if err := rows.Scan(&school, &t, &l); err != nil {
			rows.Close()
			return p, err
		}
		p.teachersInSchool += t
		p.leadersInSchool += l
		trained[school] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return p, err
	}
	args = []any{ids, rules.Engine.TrainingTypes, rules.Engine.MeetingTypes}
	where := sessionsIn(fy, w, &args)
	rows, err = s.db.Query(ctx, `
SELECT c.school_id, a.activity_type = ANY($2), a.activity_type = ANY($3),
  COALESCE(sum(c.teachers), 0), COALESCE(sum(c.leaders), 0)
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
WHERE c.school_id = ANY($1) AND c.attended AND `+where+`
GROUP BY c.school_id, 2, 3`, args...)
	if err != nil {
		return p, fmt.Errorf("schoolprofile: reading the session register: %w", err)
	}
	meetingSchools := map[string]bool{}
	for rows.Next() {
		var school string
		var training, meeting bool
		var t, l int
		if err := rows.Scan(&school, &training, &meeting, &t, &l); err != nil {
			rows.Close()
			return p, err
		}
		if training {
			p.teachersGroup += t
			p.leadersGroup += l
			trained[school] = true
		}
		if meeting {
			p.teachersAtMeetings += t
			p.leadersAtMeetings += l
			meetingSchools[school] = true
		}
	}
	rows.Close()
	p.schoolsTrained, p.schoolsAtMeetings = len(trained), len(meetingSchools)
	return p, rows.Err()
}

// learners is engine.students: enrolment and learning results this year
// against last, like for like (apps.clusters.outcomes).
type learners struct {
	enrolmentCompared, enrolmentBefore, enrolmentAfter int
	learningCompared, learningImproved                 int
	learningAfter                                      *float64
}

// enrolmentGrowth is EnrolmentSummary.growth_pct.
func (l learners) enrolmentGrowth() *float64 {
	if l.enrolmentCompared == 0 || l.enrolmentBefore == 0 {
		return nil
	}
	v := pyRound(100*float64(l.enrolmentAfter-l.enrolmentBefore)/float64(l.enrolmentBefore), 1)
	return &v
}

func (s *Service) scopeLearners(ctx context.Context, ids []string, fy string) (learners, error) {
	var out learners
	before := previousFY(fy)
	yearly := map[string]map[string]int{}
	rows, err := s.db.Query(ctx, `
SELECT h.school_id, h.fy, h.enrollment FROM school_enrollment_history h
WHERE h.school_id = ANY($1) AND h.fy = ANY($2)`, ids, []string{fy, before})
	if err != nil {
		return out, fmt.Errorf("schoolprofile: reading the enrolment history: %w", err)
	}
	for rows.Next() {
		var school, year string
		var n int
		if err := rows.Scan(&school, &year, &n); err != nil {
			rows.Close()
			return out, err
		}
		if yearly[school] == nil {
			yearly[school] = map[string]int{}
		}
		yearly[school][year] = n
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return out, err
	}
	for _, id := range ids {
		figures := yearly[id]
		was, okWas := figures[before]
		now, okNow := figures[fy]
		if okWas && okNow {
			out.enrolmentCompared++
			out.enrolmentBefore += was
			out.enrolmentAfter += now
		}
	}
	// The confirmed class results, weighted by the learners tested.
	rows, err = s.db.Query(ctx, `
SELECT l.school_id, l.fy, l.mean_score::float8, l.max_score::float8, COALESCE(l.learners_tested, 0)
FROM impact_learning_result l
WHERE l.deleted_at IS NULL AND l.school_id = ANY($1) AND l.fy = ANY($2) AND l.max_score > 0
  AND l.mean_score IS NOT NULL AND l.verification_status = 'confirmed'`, ids, []string{fy, before})
	if err != nil {
		return out, fmt.Errorf("schoolprofile: reading the learning results: %w", err)
	}
	type bucket struct{ weighted, learners float64 }
	totals := map[[2]string]*bucket{}
	for rows.Next() {
		var school, year string
		var mean, maximum float64
		var weight int
		if err := rows.Scan(&school, &year, &mean, &maximum, &weight); err != nil {
			rows.Close()
			return out, err
		}
		if weight == 0 {
			continue
		}
		b := totals[[2]string{school, year}]
		if b == nil {
			b = &bucket{}
			totals[[2]string{school, year}] = b
		}
		b.weighted += mean / maximum * 100 * float64(weight)
		b.learners += float64(weight)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return out, err
	}
	pct := func(school, year string) *float64 {
		b := totals[[2]string{school, year}]
		if b == nil {
			return nil
		}
		v := pyRound(b.weighted/b.learners, 1)
		return &v
	}
	afters := []float64{}
	for _, id := range ids {
		was, now := pct(id, before), pct(id, fy)
		if was == nil || now == nil {
			continue
		}
		out.learningCompared++
		afters = append(afters, *now)
		if pyRound(*now-*was, 1) > 0 {
			out.learningImproved++
		}
	}
	if len(afters) > 0 {
		v := pyRound(pySum(afters)/float64(len(afters)), 1)
		out.learningAfter = &v
	}
	return out, nil
}

// storyCounts is profile_records.stories' counts: the year's stories about
// the scope's schools and clusters, a draft its author's own.
type storyCounts struct{ total, approved, waiting int }

func (s *Service) scopeStories(ctx context.Context, ids, clusters []string, fy string) (storyCounts, error) {
	var c storyCounts
	end, err := strconv.Atoi(fy)
	if err != nil {
		return c, fmt.Errorf("schoolprofile: reading the profile's stories: the year %q", fy)
	}
	start := time.Date(end-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	stop := time.Date(end, time.October, 1, 0, 0, 0, 0, time.UTC)
	st := rules.Engine.StoryStatuses
	err = s.db.QueryRow(ctx, `
SELECT count(*), count(*) FILTER (WHERE m.status = $5), count(*) FILTER (WHERE m.status = ANY($6))
FROM mscs_story m
WHERE (m.school_id = ANY($1) OR (m.school_id IS NULL AND m.cluster_id = ANY($2)))
  AND m.story_date >= $3 AND m.story_date < $4 AND m.status IS DISTINCT FROM $7`,
		ids, clusters, start, stop, st.Approved, st.Waiting, st.Draft).Scan(&c.total, &c.approved, &c.waiting)
	if err != nil {
		return c, fmt.Errorf("schoolprofile: reading the profile's stories: %w", err)
	}
	return c, nil
}

// execution is engine._execution's figures for one kind of work.
type execution struct{ planned, completed, overdue int }

// scopeExecution is engine._execution: the visits, trainings and cluster
// meetings in the plan, done and past their day; and the project work past
// its day.
func (s *Service) scopeExecution(ctx context.Context, ids, clusters []string, fy string, w window, day time.Time) (visits, trainings, meetings execution, projectOverdue int, err error) {
	args := []any{}
	where := scopeWork(ids, clusters, fy, w, &args)
	args = append(args, rules.Engine.CompletedWorkStatuses, rules.Engine.NotStartedStatuses, day,
		rules.Engine.VisitTypes, rules.Engine.TrainingTypes, rules.Engine.MeetingTypes)
	k := len(args)
	done, waiting := fmt.Sprintf("a.status = ANY($%d)", k-5), fmt.Sprintf("a.status = ANY($%d)", k-4)
	past := fmt.Sprintf(`(a.planned_date < $%[1]d::date OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date < $%[1]d::date))`, k-3)
	kind := func(i int) string { return fmt.Sprintf("a.activity_type = ANY($%d)", k-3+i) }
	count := func(filter string) string { return "count(a.id) FILTER (WHERE " + filter + ")" }
	cols := ""
	for i := 1; i <= 3; i++ {
		cols += count(kind(i)) + ", " + count(kind(i)+" AND "+done) + ", " + count(kind(i)+" AND "+waiting+" AND "+past) + ", "
	}
	cols += count(waiting + " AND " + past + " AND a.project_id IS NOT NULL")
	err = s.db.QueryRow(ctx, "SELECT "+cols+" FROM activity a WHERE "+where, args...).Scan(
		&visits.planned, &visits.completed, &visits.overdue,
		&trainings.planned, &trainings.completed, &trainings.overdue,
		&meetings.planned, &meetings.completed, &meetings.overdue, &projectOverdue)
	if err != nil {
		err = fmt.Errorf("schoolprofile: counting the profile's work: %w", err)
	}
	return
}

// onlineWork is profile_records.channels' online channel: the online
// trainings in the plan and done, and the attendance at completed ones.
type onlineWork struct{ planned, completed, rate int }

func (s *Service) scopeOnline(ctx context.Context, ids, clusters []string, fy string, w window) (onlineWork, error) {
	var o onlineWork
	args := []any{}
	where := scopeWork(ids, clusters, fy, w, &args)
	args = append(args, rules.Engine.TrainingTypes, rules.Engine.CompletedWorkStatuses, rules.Engine.Scope.OnlineMode)
	k := len(args)
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(a.id) FILTER (WHERE a.activity_type = ANY($%[1]d) AND a.programme_delivery_mode = $%[3]d),
  count(a.id) FILTER (WHERE a.activity_type = ANY($%[1]d) AND a.programme_delivery_mode = $%[3]d AND a.status = ANY($%[2]d))
FROM activity a WHERE `+where, k-2, k-1, k), args...).Scan(&o.planned, &o.completed); err != nil {
		return o, fmt.Errorf("schoolprofile: counting online trainings: %w", err)
	}
	args = []any{ids, rules.Engine.TrainingTypes, rules.Engine.Scope.OnlineMode}
	sessions := sessionsIn(fy, w, &args)
	var invited, attended int
	if err := s.db.QueryRow(ctx, `
SELECT count(c.activity_id) FILTER (WHERE c.invited), count(c.activity_id) FILTER (WHERE c.attended)
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
WHERE c.school_id = ANY($1) AND a.activity_type = ANY($2) AND a.programme_delivery_mode = $3 AND `+sessions,
		args...).Scan(&invited, &attended); err != nil {
		return o, fmt.Errorf("schoolprofile: reading online attendance: %w", err)
	}
	if invited > 0 {
		o.rate = int(pyRound(float64(attended)*100/float64(invited), 0))
	}
	return o, nil
}

// scopeFinance is profile_intelligence.finance for many schools: the loans
// the reader may read in the loan register (scoped_loans), and every case
// at the schools.
func (s *Service) scopeFinance(ctx context.Context, r btReader, ids []string) (btFinance, error) {
	var f btFinance
	readable, err := s.readableLoanSchools(ctx, r, ids)
	if err != nil {
		return f, err
	}
	if len(readable) > 0 {
		if err := s.db.QueryRow(ctx, `
SELECT count(l.id), count(DISTINCT l.school_id), count(DISTINCT l.school_id) FILTER (WHERE l.status = ANY($2)),
  COALESCE(sum(l.disbursed_amount) FILTER (WHERE l.status = ANY($2)), 0)::float8,
  count(l.id) FILTER (WHERE COALESCE(p.is_edtech, false))
FROM bt_mfi_loan l LEFT JOIN bt_loan_purpose p ON p.id = l.purpose_id
WHERE l.school_id = ANY($1) AND l.deleted_at IS NULL AND l.status IS DISTINCT FROM 'canceled'`,
			readable, rules.BT.FundedLoanStatuses).Scan(&f.loans, &f.loanSchools, &f.fundedSchools, &f.disbursed, &f.edtech); err != nil {
			return f, fmt.Errorf("schoolprofile: reading the profile's loans: %w", err)
		}
	}
	if err := s.db.QueryRow(ctx, `
SELECT count(id), count(id) FILTER (WHERE status = ANY($2)), count(DISTINCT school_id)
FROM bt_case WHERE school_id = ANY($1) AND deleted_at IS NULL`, ids, rules.BT.OpenCaseStatuses).Scan(&f.cases, &f.openCases, &f.caseSchools); err != nil {
		return f, fmt.Errorf("schoolprofile: reading the profile's cases: %w", err)
	}
	return f, nil
}

// readableLoanSchools is scoped_loans over the scope's schools: the ones
// whose loans the reader may read.
func (s *Service) readableLoanSchools(ctx context.Context, r btReader, ids []string) ([]string, error) {
	if !slices.Contains(rules.BT.UgandaWideRoles, r.role()) && r.role() != "CCEO" {
		return nil, nil
	}
	sq := r.scope
	switch {
	case sq.CountryScope && sq.Country == "", sq.SummaryOnly && !sq.CountryScope && !sq.RegionScope:
		return ids, nil
	case sq.CountryScope:
		rows, err := s.db.Query(ctx, `
SELECT s.id FROM school s WHERE s.id = ANY($1) AND (
  EXISTS (SELECT 1 FROM region r WHERE r.id = s.region_id AND r.country = $2)
  OR (s.region_id IS NULL AND (
    s.account_owner_id IN (SELECT id FROM staff_profile WHERE country = $2 AND deleted_at IS NULL)
    OR s.account_owner_id IS NULL OR s.account_owner_id = ''
    OR s.account_owner_id IN (SELECT id FROM staff_profile WHERE (country IS NULL OR country = '') AND deleted_at IS NULL))))`,
			ids, sq.Country)
		if err != nil {
			return nil, fmt.Errorf("schoolprofile: reading the schools' country: %w", err)
		}
		out := []string{}
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				rows.Close()
				return nil, err
			}
			out = append(out, id)
		}
		rows.Close()
		return out, rows.Err()
	case sq.RegionScope:
		return nil, nil
	}
	out := []string{}
	for _, id := range ids {
		if slices.Contains(sq.SchoolIDs, id) {
			out = append(out, id)
		}
	}
	return out, nil
}
