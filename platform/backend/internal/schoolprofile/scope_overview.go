package schoolprofile

import (
	"context"
	"fmt"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// scopeProfile is profile_intelligence.build for a scope, with the reads
// profile_context adds for the Overview.
type scopeProfile struct {
	scope          scopeOf
	schools        []scopeSchool
	clusters       map[string]string
	clustered      int
	subCounties    int
	cmp            comparison
	overall        change
	scores         map[string]yearScore
	verdicts       map[string]change
	schoolWork     map[string]*placeWork
	clusterWork    map[string]*placeWork
	handovers      handovers
	projects       []string
	people         peopleTrained
	learners       learners
	stories        storyCounts
	visits         execution
	trainings      execution
	meetings       execution
	projectOverdue int
	online         onlineWork
	unplanned      int
	assessed       int
	assessable     int
	visitsExpected int
	finance        *btFinance
	staff, leads   []person
	book           ruleBook
	focus          map[string][2]int
	planned        map[string]bool
}

func (s *Service) readScopeProfile(ctx context.Context, r btReader, sc scopeOf, l lens, now time.Time) (*scopeProfile, error) {
	pr := &scopeProfile{scope: sc}
	var err error
	if pr.schools, err = s.readScopeSchools(ctx, sc); err != nil {
		return nil, err
	}
	ids := idsOf(pr.schools)
	clusterIDs := clusterIDsOf(pr.schools)
	if pr.clusters, err = s.liveClusters(ctx, clusterIDs); err != nil {
		return nil, err
	}
	subCounties, owners := map[string]bool{}, []string{}
	for _, x := range pr.schools {
		if pr.clusters[x.cluster] != "" {
			pr.clustered++
		}
		if x.subCounty != "" {
			subCounties[x.subCounty] = true
		}
		if x.owner != "" && !contains(owners, x.owner) {
			owners = append(owners, x.owner)
		}
	}
	pr.subCounties = len(subCounties)
	book, err := s.ruleBook(ctx)
	if err != nil {
		return nil, err
	}
	pr.book = book
	if pr.cmp, err = s.scopeComparison(ctx, ids, l.fy); err != nil {
		return nil, err
	}
	for i := range pr.cmp.rows {
		pr.cmp.rows[i].verdict = book.interventionChange(pr.cmp.rows[i].key, pr.cmp.rows[i].previous, pr.cmp.rows[i].current)
	}
	pr.overall = book.overallChange(pr.cmp.previous, pr.cmp.current)
	if pr.scores, err = s.schoolYearScores(ctx, ids, l.fy); err != nil {
		return nil, err
	}
	pr.verdicts = map[string]change{}
	for _, x := range pr.schools {
		score := pr.scores[x.id]
		pr.verdicts[x.id] = book.overallChange(score.previous, score.current)
		need := rules.Engine.Requirements[x.kind]
		if need.TakesSSA {
			pr.assessable++
			if score.current != nil {
				pr.assessed++
			}
		}
		pr.visitsExpected += need.Visits
	}
	if pr.schoolWork, pr.clusterWork, err = s.workByPlace(ctx, ids, clusterIDs, l.fy, l.window); err != nil {
		return nil, err
	}
	if pr.planned, err = s.plannedSchools(ctx, ids, l.fy, l.window); err != nil {
		return nil, err
	}
	for _, x := range pr.schools {
		if !pr.planned[x.id] {
			pr.unplanned++
		}
	}
	if pr.handovers, err = s.scopeHandovers(ctx, ids, ""); err != nil {
		return nil, err
	}
	if pr.projects, err = s.scopeProjectIDs(ctx, ids); err != nil {
		return nil, err
	}
	if pr.people, err = s.scopePeople(ctx, ids, l.fy, l.window); err != nil {
		return nil, err
	}
	if pr.learners, err = s.scopeLearners(ctx, ids, l.fy); err != nil {
		return nil, err
	}
	live := []string{}
	for id := range pr.clusters {
		live = append(live, id)
	}
	if pr.stories, err = s.scopeStories(ctx, ids, live, l.fy); err != nil {
		return nil, err
	}
	if pr.focus, err = s.focusWork(ctx, ids, live, l.fy, l.window); err != nil {
		return nil, err
	}
	if pr.visits, pr.trainings, pr.meetings, pr.projectOverdue, err = s.scopeExecution(ctx, ids, clusterIDs, l.fy, l.window, kampalaDay(now)); err != nil {
		return nil, err
	}
	if pr.online, err = s.scopeOnline(ctx, ids, live, l.fy, l.window); err != nil {
		return nil, err
	}
	if r.doors.Loans {
		f, err := s.scopeFinance(ctx, r, ids)
		if err != nil {
			return nil, err
		}
		pr.finance = &f
	}
	if pr.staff, pr.leads, err = s.holdersOf(ctx, owners); err != nil {
		return nil, err
	}
	return pr, nil
}

// plannedSchools is the scope's schools with work in the plan this year
// (engine.build's planned_ids: the schools' own work, no cluster's).
func (s *Service) plannedSchools(ctx context.Context, ids []string, fy string, w window) (map[string]bool, error) {
	args := []any{}
	where := scopeWork(ids, []string{}, fy, w, &args)
	rows, err := s.db.Query(ctx, `SELECT DISTINCT a.school_id FROM activity a WHERE a.school_id IS NOT NULL AND `+where, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the schools planned: %w", err)
	}
	out := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		out[id] = true
	}
	rows.Close()
	return out, rows.Err()
}

// holdersOf is profile_records._holders: the staff holding the schools
// (their owners, by staff or user id) and the leads they report to, each by
// name.
func (s *Service) holdersOf(ctx context.Context, owners []string) (staff, leads []person, err error) {
	if len(owners) == 0 {
		return nil, nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT sp.id, sp.user_id, COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), 'Unnamed')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, owners)
	if err != nil {
		return nil, nil, fmt.Errorf("schoolprofile: reading the schools' holders: %w", err)
	}
	staffIDs := []string{}
	for rows.Next() {
		var staffID string
		var p person
		if err := rows.Scan(&staffID, &p.id, &p.name); err != nil {
			rows.Close()
			return nil, nil, err
		}
		staffIDs = append(staffIDs, staffID)
		staff = append(staff, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	rows, err = s.db.Query(ctx, `
SELECT DISTINCT sup.user_id, COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), 'Unnamed')
FROM staff_supervisor_assignment a
JOIN staff_profile sup ON sup.id = a.supervisor_id JOIN "user" u ON u.id = sup.user_id
WHERE a.supervisee_id = ANY($1)`, staffIDs)
	if err != nil {
		return nil, nil, fmt.Errorf("schoolprofile: reading the schools' leads: %w", err)
	}
	for rows.Next() {
		var p person
		if err := rows.Scan(&p.id, &p.name); err != nil {
			rows.Close()
			return nil, nil, err
		}
		leads = append(leads, p)
	}
	rows.Close()
	byName(staff)
	byName(leads)
	return staff, leads, rows.Err()
}

// byName orders people by name, casefolded.
func byName(people []person) {
	for i := 1; i < len(people); i++ {
		for j := i; j > 0 && strings.ToLower(people[j].name) < strings.ToLower(people[j-1].name); j-- {
			people[j], people[j-1] = people[j-1], people[j]
		}
	}
}

// scopeLine is partials/profiles/_scope_line.html.
func (pr *scopeProfile) scopeLine(lead string, l lens) string {
	out := ""
	if lead != "" {
		out = lead + " · "
	}
	n, c, j := len(pr.schools), len(pr.clusters), len(pr.projects)
	out += "Portfolio: " + intcomma(n) + " school" + plural(n) + " · " + intcomma(c) + " cluster" + plural(c) +
		" · " + intcomma(j) + " project" + plural(j) + " — " + pr.scope.covers + ", " + fyLabel(l.fy)
	if l.window.label != "" {
		out += " · work in " + l.window.label
	}
	return out
}

// overview is the Overview section of pages/profiles/profile.html for a
// scope that is not a school or a cluster.
func (pr *scopeProfile) overview(l lens) []*screensv1.PageBlock {
	records := l.records()
	tabURL := func(section string) string { return l.href() + "tab=" + section + "&fy=" + l.fy }
	label := fyLabel(l.fy)
	sections := rules.Engine.Scope.SectionsOf[pr.scope.kind]

	// ── Portfolio ──────────────────────────────────────────────────────────
	types := []string{}
	counts := map[string]int{}
	for _, x := range pr.schools {
		counts[x.kind]++
	}
	for _, key := range rules.Engine.Scope.SchoolTypeOrder {
		if counts[key] > 0 {
			types = append(types, intcomma(counts[key])+" "+rules.SchoolTypes[key])
		}
	}
	portfolio := []kpi{{label: "Schools", value: intcomma(len(pr.schools)), link: tabURL("schools"), helper: strings.Join(types, " · ")}}
	if contains(sections, "sub_counties") {
		portfolio = append(portfolio, kpi{label: "Sub-counties", value: intcomma(pr.subCounties), link: tabURL("sub_counties")})
	}
	if contains(sections, "clusters") {
		coverage := 0
		if len(pr.schools) > 0 {
			coverage = pyRoundHalfEven(float64(pr.clustered) * 100 / float64(len(pr.schools)))
		}
		portfolio = append(portfolio, kpi{label: "Clusters", value: intcomma(len(pr.clusters)), link: tabURL("clusters"),
			helper: intcomma(pr.clustered) + " schools in a cluster · " + intcomma(coverage) + "%"})
	}
	enrolment := 0
	for _, x := range pr.schools {
		enrolment += x.enrolment
	}
	h := pr.handovers
	portfolio = append(portfolio,
		kpi{label: "Enrolment", value: intcomma(enrolment), link: records + "enrolment", helper: "learners in these schools"},
		kpi{label: "Partners", value: intcomma(h.partners), link: records + "partners",
			helper: intcomma(h.assigned) + " hand-over" + plural(h.assigned) + " held"},
		kpi{label: "Projects", value: intcomma(len(pr.projects)), link: tabURL("projects")})

	// ── Performance and impact ─────────────────────────────────────────────
	ssaValue, ssaHelper := "0.00", "previous 0"
	if pr.cmp.current != nil {
		ssaValue = twoPlaces(*pr.cmp.current)
	}
	if pr.cmp.previous != nil {
		ssaHelper = "previous " + twoPlaces(*pr.cmp.previous)
	}
	if pr.overall.delta != nil {
		ssaHelper += " · " + signedTwoPlaces(*pr.overall.delta)
	}
	growth := "0%"
	if g := pr.learners.enrolmentGrowth(); g != nil {
		growth = pyFloat(*g) + "%"
		if *g > 0 {
			growth = "+" + growth
		}
	}
	results := "0%"
	if a := pr.learners.learningAfter; a != nil {
		results = pyFloat(*a) + "%"
	}
	p, ln := pr.people, pr.learners
	impact := []kpi{
		{label: "SSA Score", value: ssaValue, link: tabURL("ssa"), helper: ssaHelper},
		{label: "Schools Assessed", value: intcomma(pr.assessed), link: records + "ssa", helper: "of " + intcomma(pr.assessable) + " in " + label},
		{label: "Teachers Trained", value: intcomma(p.teachers()), link: records + "teachers_trained",
			helper: intcomma(p.teachersInSchool) + " in school · " + intcomma(p.teachersGroup) + " at group trainings"},
		{label: "School Leaders Trained", value: intcomma(p.leaders()), link: records + "leaders_trained",
			helper: intcomma(p.leadersInSchool) + " in school · " + intcomma(p.leadersGroup) + " at group trainings"},
		{label: "Enrolment Growth", value: growth, link: records + "enrolment_growth",
			helper: intcomma(ln.enrolmentCompared) + " school" + plural(ln.enrolmentCompared) + " with both years"},
		{label: "Learning Results", value: results, link: records + "learning",
			helper: intcomma(ln.learningCompared) + " school" + plural(ln.learningCompared) + " compared · " + intcomma(ln.learningImproved) + " improved"},
		{label: "Change Stories", value: intcomma(pr.stories.total), link: records + "stories",
			helper: intcomma(pr.stories.approved) + " approved · " + intcomma(pr.stories.waiting) + " with a reviewer"},
	}

	// ── Operations ─────────────────────────────────────────────────────────
	operations := []kpi{
		{label: "Visits Completed", value: intcomma(pr.visits.completed), link: records + "visits_done",
			helper: "of " + intcomma(pr.visits.planned) + " in the plan · " + intcomma(pr.visitsExpected) + " expected"},
		{label: "Trainings Completed", value: intcomma(pr.trainings.completed), link: records + "trainings_done",
			helper: "of " + intcomma(pr.trainings.planned) + " in the plan · " + intcomma(p.schoolsTrained) + " school" + plural(p.schoolsTrained) + " trained"},
		{label: "Online Trainings", value: intcomma(pr.online.completed), link: records + "trainings_online",
			helper: "of " + intcomma(pr.online.planned) + " in the plan · " + intcomma(pr.online.rate) + "% attendance"},
		{label: "Cluster Meetings Held", value: intcomma(pr.meetings.completed), link: records + "meetings_done",
			helper: "of " + intcomma(pr.meetings.planned) + " in the plan"},
		{label: "At Cluster Meetings", value: intcomma(p.teachersAtMeetings + p.leadersAtMeetings), link: records + "at_meetings",
			helper: intcomma(p.teachersAtMeetings) + " teachers · " + intcomma(p.leadersAtMeetings) + " leaders"},
		{label: "Nothing Planned", value: intcomma(pr.unplanned), link: tabURL("schools") + "&show=unplanned",
			helper: "schools with no activity in " + label},
	}
	blocks := []*screensv1.PageBlock{
		strip("Portfolio", portfolio...),
		strip("Performance And Impact", impact...),
		strip("Operations", operations...),
	}
	if pr.finance != nil {
		blocks = append(blocks, pr.finance.strip(records))
	}
	return blocks
}
