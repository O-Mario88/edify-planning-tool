package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// The Core School tab (partials/schools/_core_school.html): the school's row
// of Core School Intelligence (apps.core_schools.intelligence.performance),
// its recorded recommendations, and Champion readiness by the official rule
// (champion_services.ChampionEligibilityService). The page reader keeps the
// figures, the panels' lines and their links; the sentence explaining the
// trajectory is read as its link alone.

// corePerformance is CoreSchoolPerformance, the parts the tab draws.
type corePerformance struct {
	trajectory string
	ssaChange  *float64
	hasCurrent bool

	hasPlan                                                   bool
	visitsDone, visitsTarget, trainingsDone, trainingsTarget  int
	split                                                     visitgate.CoreSplit
	handoversAssigned, handoversScheduled, handoversCompleted int
	invited, attended                                         int
	teachers, leaders                                         *int
	enrolBefore, enrolAfter                                   *int
	learnBefore, learnAfter                                   *float64
	champion                                                  string
	metrics                                                   *championMetrics
}

type championMetrics struct {
	latestAvg, lowestScore     float64
	lowestIntervention         string
	totalSlots, completedSlots int
	eligible                   bool
}

func (s *Service) coreTab(ctx context.Context, scope schooldirectory.Scope, d doors, sc school, l lens, now time.Time) ([]*screensv1.PageBlock, error) {
	perf, err := s.corePerformance(ctx, sc, l.fy, schooldirectory.OperationalFY(now))
	if err != nil {
		return nil, err
	}
	ct := rules.CoreTab
	ssaHref := l.href() + "tab=ssa&fy=" + l.fy

	// The strip.
	changeText := ""
	if perf.ssaChange != nil {
		changeText = signedFloat(*perf.ssaChange) + " · "
	}
	packageValue, packageHelper := "No package", "No Core plan this year"
	if perf.hasPlan {
		packageValue = perf.packageLabel()
		packageHelper = fmt.Sprintf("Visits %d/%d · Trainings %d/%d", perf.visitsDone, perf.visitsTarget, perf.trainingsDone, perf.trainingsTarget)
	}
	rate := perf.attendanceRate()
	rateValue := "—"
	if rate != nil {
		rateValue = strconv.Itoa(*rate) + "%"
	}
	blocks := []*screensv1.PageBlock{strip("Performance overview",
		kpi{label: "SSA Trajectory", value: label(ct.TrajectoryLabels, perf.trajectory), link: ssaHref, helper: changeText + "scores on the SSA tab"},
		kpi{label: "Package", value: packageValue, helper: packageHelper},
		kpi{label: "Session Attendance", value: rateValue, helper: fmt.Sprintf("%d of %d invitations", perf.attended, perf.invited)},
		kpi{label: "Teacher Attendances", value: dashInt(perf.teachers), helper: "Headcounts · " + dashInt(perf.leaders) + " leader attendances"},
		kpi{label: "Champion Readiness", value: perf.champion, helper: "Edify's Champion rule"},
	)}

	blocks = append(blocks, corePanel("", corePanelLink("Each intervention's scores are on the SSA tab.", ssaHref, false)))
	blocks = append(blocks, perf.packagePanel(l), perf.participationPanel(rate), perf.outcomesPanel())

	recs, err := s.coreRecommendations(ctx, sc)
	if err != nil {
		return nil, err
	}
	mayAct := slices.Contains(ct.CountryWriteRoles, scope.Role) || slices.Contains(scope.OwnSchoolIDs, sc.ID)
	blocks = append(blocks, recommendationBlocks(recs, mayAct, sc)...)
	blocks = append(blocks, perf.championPanel(d, sc))
	blocks = append(blocks, corePanel("", corePanelLink("Core School Oversight",
		"/core-schools-oversight/?fy="+l.fy+"&q="+strings.ReplaceAll(url.PathEscape(sc.SchoolID), "%2F", "/"), false)))
	return blocks, nil
}

func corePanel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: title, Badges: []*screensv1.PageBadge{}, Items: pairedItems(items)}}}
}

func corePanelLink(text, href string, isDrawer bool) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
		{Text: text, Href: href, Drawer: isDrawer}}}}}
}

func (c corePerformance) packagePanel(l lens) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	if c.hasPlan {
		items = append(items, text(fmt.Sprintf("Visits %d of %d · Trainings %d of %d", c.visitsDone, c.visitsTarget, c.trainingsDone, c.trainingsTarget)))
		if c.split.HasPackage {
			sp := c.split
			items = append(items, text(fmt.Sprintf("Staff: %d visits, %d trainings · Partner: %d visits, %d trainings",
				sp.StaffVisits, sp.StaffTrainings, sp.PartnerHeldVisits(), sp.PartnerHeldTrainings())))
		}
	} else {
		items = append(items, text("No Core plan for "+fyLabel(l.fy)+"."))
	}
	items = append(items, text(fmt.Sprintf("Partner hand-overs: %d not yet scheduled · %d scheduled · %d completed",
		c.handoversAssigned, c.handoversScheduled, c.handoversCompleted)))
	return corePanel("Package and Support", items...)
}

func (c corePerformance) participationPanel(rate *int) *screensv1.PageBlock {
	sessions := fmt.Sprintf("Cluster sessions: %d attended of %d invited", c.attended, c.invited)
	if rate != nil {
		sessions += fmt.Sprintf(" (%d%%)", *rate)
	}
	return corePanel("Participation", text(sessions),
		text("Teacher attendances "+dashInt(c.teachers)+" · Leader attendances "+dashInt(c.leaders)+" (headcounts, not unique people)"))
}

func (c corePerformance) outcomesPanel() *screensv1.PageBlock {
	enrolment := "Enrolment: " + dashInt(c.enrolBefore) + " → " + dashInt(c.enrolAfter)
	if c.enrolBefore != nil && c.enrolAfter != nil {
		change := *c.enrolAfter - *c.enrolBefore
		sign := ""
		if change > 0 {
			sign = "+"
		}
		enrolment += " (" + sign + strconv.Itoa(change)
		if *c.enrolBefore != 0 {
			enrolment += ", " + pyFloat(pyRound(100*float64(change)/float64(*c.enrolBefore), 1)) + "%"
		}
		enrolment += ")"
	}
	learning := "Learning results (share of marks): " + dashFloat(c.learnBefore) + " → " + dashFloat(c.learnAfter)
	if c.learnBefore != nil && c.learnAfter != nil {
		learning += " (" + signedFloat(pyRound(*c.learnAfter-*c.learnBefore, 1)) + " pts)"
	}
	return corePanel("Outcomes", text(enrolment), text(learning))
}

// recommendationBlocks is the Recommended Support card: a sentence where
// nothing is open, else a section heading and each record's lines, with
// Plan support for someone who may act on the school (may_write_school).
func recommendationBlocks(recs []coreRecommendation, mayAct bool, sc school) []*screensv1.PageBlock {
	ct := rules.CoreTab
	if len(recs) == 0 {
		return []*screensv1.PageBlock{corePanel("Recommended Support", text("No open recommendation. They are recorded from the school's confirmed SSA."))}
	}
	items := []*screensv1.PagePanelItem{}
	for _, r := range recs {
		head := label(rules.SSAInterventions, r.intervention)
		if r.score != nil {
			head += " (" + floatformat(*r.score, 1)
			if r.band != "" {
				head += ", " + r.band
			}
			head += ")"
		}
		items = append(items, text(collapse(head)))
		if reason := collapse(r.reason); reason != "" {
			items = append(items, text(reason))
		}
		if state := collapse(label(ct.RecommendationStates, r.state)); state != "" {
			items = append(items, text(state))
		}
		if mayAct && slices.Contains(ct.RecommendationLiveStates, r.state) {
			items = append(items, corePanelLink("Plan support", "/planning/schedule-modal?school_id="+sc.ID, true))
		}
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Section{Section: "Recommended Support"}},
		corePanel("", items...),
	}
}

// championPanel is the Champion readiness card: the official rule's three
// checks, and the review for a Potential Champion.
func (c corePerformance) championPanel(d doors, sc school) *screensv1.PageBlock {
	m := c.metrics
	verdict := func(met bool) string {
		switch {
		case m == nil:
			return "Not judged"
		case met:
			return "Met"
		}
		return "Not met"
	}
	first, second, third := "Latest SSA average 8.0 or more", "No intervention below 7.0", "All package visits and trainings done"
	if m != nil {
		first += " (now " + floatformat(m.latestAvg, 1) + ")"
		second += " (lowest " + floatformat(m.lowestScore, 1) + ", " + m.lowestIntervention + ")"
		third += fmt.Sprintf(" (%d of %d)", m.completedSlots, m.totalSlots)
	}
	lines := []*screensv1.PageLink{
		{Text: verdict(m != nil && m.latestAvg >= 8.0) + ": " + first},
		{Text: verdict(m != nil && m.lowestScore >= 7.0) + ": " + second},
		{Text: verdict(m != nil && m.totalSlots != 0 && m.completedSlots >= m.totalSlots) + ": " + third},
	}
	items := []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: lines}}}}
	if m == nil {
		items = append(items, text("The rule needs a confirmed SSA and a Core plan to judge this school."))
	}
	items = append(items, text("Readiness is a recommendation. A school becomes a Champion only through the Champion review."))
	if c.champion == rules.CoreTab.Champion.Potential && d.CoreSchools {
		items = append(items, corePanelLink("Open Champion review", "/core-schools/"+sc.SchoolID+"/champion-review", true))
	}
	return corePanel("Champion Readiness: "+c.champion, items...)
}

func dashInt(n *int) string {
	if n == nil {
		return "—"
	}
	return strconv.Itoa(*n)
}

func dashFloat(f *float64) string {
	if f == nil {
		return "—"
	}
	return pyFloat(*f)
}

// signedFloat is "{% if x > 0 %}+{% endif %}{{ x }}" for a float.
func signedFloat(x float64) string {
	if x > 0 {
		return "+" + pyFloat(x)
	}
	return pyFloat(x)
}

// packageLabel is CoreSchoolPerformance.package_label for a school with a
// plan: the share of the package done, each kind capped at its target.
func (c corePerformance) packageLabel() string {
	target := c.visitsTarget + c.trainingsTarget
	if target == 0 {
		return "None%"
	}
	done := min(c.visitsDone, c.visitsTarget) + min(c.trainingsDone, c.trainingsTarget)
	return strconv.Itoa(pyRoundInt(100*float64(done)/float64(target))) + "%"
}

func (c corePerformance) attendanceRate() *int {
	if c.invited == 0 {
		return nil
	}
	r := pyRoundInt(100 * float64(c.attended) / float64(c.invited))
	return &r
}

// corePerformance is intelligence.performance for one school.
func (s *Service) corePerformance(ctx context.Context, sc school, fy, operational string) (corePerformance, error) {
	perf := corePerformance{trajectory: "not_comparable", champion: rules.CoreTab.Champion.Insufficient}
	steps := []func(context.Context, school, string, string, *corePerformance) error{
		s.coreSSA, s.corePackage, s.coreHandovers, s.coreParticipation, s.coreOutcomes, s.coreChampion,
	}
	for _, step := range steps {
		if err := step(ctx, sc, fy, operational, &perf); err != nil {
			return perf, err
		}
	}
	return perf, nil
}

// coreSSA is _read_ssa: whether the school has an SSA this year, and its
// trajectory over the comparable pairs of its latest confirmed records of
// the year and the year before (impact_engine.improvement_rows,
// change_rules.school_verdicts).
func (s *Service) coreSSA(ctx context.Context, sc school, fy, _ string, perf *corePerformance) error {
	years, err := s.schoolYearScores(ctx, []string{sc.ID}, fy)
	if err != nil {
		return err
	}
	perf.hasCurrent = years[sc.ID].current != nil

	after, err := s.latestConfirmed(ctx, sc.ID, fy)
	if err != nil || after == nil {
		return err
	}
	prior, err := s.latestConfirmed(ctx, sc.ID, previousFY(fy))
	if err != nil || prior == nil {
		return err
	}
	if int(after.day.Sub(prior.day).Hours()/24) < rules.Engine.MinIntervalDays {
		return nil
	}
	scores := map[string]map[string]float64{prior.id: {}, after.id: {}}
	rows, err := s.db.Query(ctx, `SELECT ssa_record_id, intervention, score FROM ssa_score WHERE ssa_record_id = ANY($1) AND score IS NOT NULL`,
		[]string{prior.id, after.id})
	if err != nil {
		return fmt.Errorf("schoolprofile: reading SSA scores: %w", err)
	}
	for rows.Next() {
		var id, intervention string
		var v float64
		if err := rows.Scan(&id, &intervention, &v); err != nil {
			rows.Close()
			return err
		}
		scores[id][intervention] = v
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	var country string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(r.country, '') FROM school s LEFT JOIN region r ON r.id = s.region_id WHERE s.id = $1`,
		sc.ID).Scan(&country); err != nil {
		return fmt.Errorf("schoolprofile: reading the school's country: %w", err)
	}
	book, err := s.ruleBook(ctx)
	if err != nil {
		return err
	}
	deltas, interventions := []float64{}, []string{}
	for _, code := range rules.Engine.InterventionOrder {
		b, okB := scores[prior.id][code]
		a, okA := scores[after.id][code]
		if !okB || !okA {
			continue
		}
		c := between(b, a, book.ruleIn(code, country))
		deltas = append(deltas, *c.delta)
		interventions = append(interventions, code)
	}
	if len(deltas) == 0 {
		return nil
	}
	mean := pyRound(pySum(deltas)/float64(len(deltas)), 4)
	rule, _ := book.schoolRuleIn(interventions, country)
	if c := between(0, mean, rule); c.status != "not_comparable" {
		perf.trajectory = c.status
		change := pyRound(mean, 1)
		perf.ssaChange = &change
	}
	return nil
}

type confirmedRecord struct {
	id  string
	day time.Time
}

// latestConfirmed is impact_engine._latest_confirmed_records for one school
// and year: the record and its UTC date.
func (s *Service) latestConfirmed(ctx context.Context, schoolID, fy string) (*confirmedRecord, error) {
	var r confirmedRecord
	err := s.db.QueryRow(ctx, `
SELECT id, (date_of_ssa AT TIME ZONE 'UTC')::date FROM ssa_record
WHERE school_id = $1 AND fy = $2 AND deleted_at IS NULL AND verification_status = 'confirmed'
ORDER BY date_of_ssa DESC, created_at DESC LIMIT 1`, schoolID, fy).Scan(&r.id, &r.day)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the latest SSA: %w", err)
	}
	return &r, nil
}

// corePackage is _read_package: the year's plan, as the plan records its
// completion, and the package's split.
func (s *Service) corePackage(ctx context.Context, sc school, fy, operational string, perf *corePerformance) error {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(visits_completed, 0), COALESCE(visits_target, 0), COALESCE(trainings_completed, 0), COALESCE(trainings_target, 0)
FROM core_plan WHERE school_id = ANY($1) AND fy = $2`, []string{sc.ID, sc.SchoolID}, fy)
	if err != nil {
		return fmt.Errorf("schoolprofile: reading the year's Core plan: %w", err)
	}
	for rows.Next() {
		perf.hasPlan = true
		var vd, vt, td, tt int32
		if err := rows.Scan(&vd, &vt, &td, &tt); err != nil {
			rows.Close()
			return err
		}
		perf.visitsDone, perf.visitsTarget, perf.trainingsDone, perf.trainingsTarget = int(vd), int(vt), int(td), int(tt)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	perf.split, err = visitgate.SplitOf(ctx, s.db, rules.Gate,
		visitgate.School{ID: sc.ID, Code: sc.SchoolID, Name: sc.Name, Type: sc.Type}, fy, operational)
	return err
}

// coreHandovers is _read_handovers: the hand-overs made in the year.
func (s *Service) coreHandovers(ctx context.Context, sc school, fy, _ string, perf *corePerformance) error {
	year, err := strconv.Atoi(fy)
	if err != nil {
		return nil
	}
	ct := rules.CoreTab
	start := time.Date(year-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(year, time.October, 1, 0, 0, 0, 0, time.UTC)
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(id) FILTER (WHERE status = ANY($4)), COUNT(id) FILTER (WHERE status = ANY($5)), COUNT(id) FILTER (WHERE status = $6)
FROM partner_assignment WHERE school_id = $1 AND created_at >= $2 AND created_at < $3`,
		sc.ID, start, end, ct.HandoverUnscheduled, ct.HandoverScheduled, ct.HandoverCompleted).Scan(
		&perf.handoversAssigned, &perf.handoversScheduled, &perf.handoversCompleted); err != nil {
		return fmt.Errorf("schoolprofile: counting the year's hand-overs: %w", err)
	}
	return nil
}

// addHeadcount is intelligence._add: a missing figure stays missing until
// one is recorded.
func addHeadcount(current **int, value *int32) {
	if value == nil {
		return
	}
	n := int(*value)
	if *current != nil {
		n += **current
	}
	*current = &n
}

// coreParticipation is _read_participation: the register of the year's
// delivered cluster sessions, and the school's own delivered trainings, as
// headcounts.
func (s *Service) coreParticipation(ctx context.Context, sc school, fy, _ string, perf *corePerformance) error {
	ct := rules.CoreTab
	rows, err := s.db.Query(ctx, `
SELECT c.invited, c.attended, c.teachers, c.leaders
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
WHERE c.school_id = $1 AND a.deleted_at IS NULL AND a.activity_type = ANY($2) AND a.status = ANY($3) AND a.fy = $4`,
		sc.ID, ct.ClusterSessionTypes, ct.DeliveredStatuses, fy)
	if err != nil {
		return fmt.Errorf("schoolprofile: reading the session register: %w", err)
	}
	for rows.Next() {
		var invited, attended bool
		var teachers, leaders *int32
		if err := rows.Scan(&invited, &attended, &teachers, &leaders); err != nil {
			rows.Close()
			return err
		}
		if invited {
			perf.invited++
			if attended {
				perf.attended++
			}
		}
		if attended {
			addHeadcount(&perf.teachers, teachers)
			addHeadcount(&perf.leaders, leaders)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	rows, err = s.db.Query(ctx, `
SELECT teachers_attended, leaders_attended FROM activity
WHERE school_id = $1 AND deleted_at IS NULL AND activity_type = ANY($2) AND NOT (activity_type = ANY($3))
  AND status = ANY($4) AND fy = $5`, sc.ID, ct.TrainingTypes, ct.ClusterSessionTypes, ct.DeliveredStatuses, fy)
	if err != nil {
		return fmt.Errorf("schoolprofile: reading the school's trainings: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var teachers, leaders *int32
		if err := rows.Scan(&teachers, &leaders); err != nil {
			return err
		}
		addHeadcount(&perf.teachers, teachers)
		addHeadcount(&perf.leaders, leaders)
	}
	return rows.Err()
}

// coreOutcomes is _read_outcomes: enrolment and learning results in the year
// and the year before, each year on its own.
func (s *Service) coreOutcomes(ctx context.Context, sc school, fy, _ string, perf *corePerformance) error {
	before := previousFY(fy)
	rows, err := s.db.Query(ctx, `SELECT fy, enrollment FROM school_enrollment_history WHERE school_id = $1 AND fy = ANY($2)`,
		sc.ID, []string{fy, before})
	if err != nil {
		return fmt.Errorf("schoolprofile: reading enrolment: %w", err)
	}
	for rows.Next() {
		var year string
		var n *int32
		if err := rows.Scan(&year, &n); err != nil {
			rows.Close()
			return err
		}
		if year == fy {
			perf.enrolAfter = intOf(n)
		} else {
			perf.enrolBefore = intOf(n)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	// clusters.outcomes._school_scores: confirmed results with a mark and a
	// maximum, weighted by the learners tested.
	type sums struct{ weighted, learners float64 }
	totals := map[string]*sums{}
	rows, err = s.db.Query(ctx, `
SELECT fy, mean_score::float8, max_score::float8, COALESCE(learners_tested, 0) FROM impact_learning_result
WHERE school_id = $1 AND fy = ANY($2) AND deleted_at IS NULL AND verification_status = 'confirmed'
  AND mean_score IS NOT NULL AND max_score > 0`, sc.ID, []string{fy, before})
	if err != nil {
		return fmt.Errorf("schoolprofile: reading learning results: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var year string
		var mean, maximum float64
		var tested int32
		if err := rows.Scan(&year, &mean, &maximum, &tested); err != nil {
			return err
		}
		if tested == 0 {
			continue
		}
		t := totals[year]
		if t == nil {
			t = &sums{}
			totals[year] = t
		}
		t.weighted += mean / maximum * 100 * float64(tested)
		t.learners += float64(tested)
	}
	if err := rows.Err(); err != nil {
		return err
	}
	pct := func(year string) *float64 {
		t := totals[year]
		if t == nil {
			return nil
		}
		v := pyRound(t.weighted/t.learners, 1)
		return &v
	}
	perf.learnAfter, perf.learnBefore = pct(fy), pct(before)
	return nil
}

// coreChampion is _read_champion with ChampionEligibilityService.scan's
// inputs for one school: its Core profile, its live package (the running
// year's, else its newest) and its confirmed SSAs.
func (s *Service) coreChampion(ctx context.Context, sc school, _, operational string, perf *corePerformance) error {
	ch := rules.CoreTab.Champion
	if sc.Type == "champion" {
		perf.champion = ch.Champion
	}
	if sc.SchoolID == "" {
		return nil
	}
	var stored *string
	hasProfile := true
	err := s.db.QueryRow(ctx, `SELECT champion_status FROM core_school_profile WHERE school_id = $1 LIMIT 1`, sc.SchoolID).Scan(&stored)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		hasProfile = false
	case err != nil:
		return fmt.Errorf("schoolprofile: reading the Core profile: %w", err)
	}
	if hasProfile {
		if perf.metrics, err = s.championMetrics(ctx, sc, operational); err != nil {
			return err
		}
	}
	m := perf.metrics
	switch {
	case sc.Type == "champion" || (stored != nil && slices.Contains(ch.StoredChampion, *stored)):
		perf.champion = ch.Champion
	case !perf.hasPlan || !perf.hasCurrent:
		perf.champion = ch.Insufficient
	case m != nil && m.eligible:
		perf.champion = ch.Potential
	case (m != nil && m.latestAvg >= ch.LatestAvg) || perf.trajectory == "improved":
		perf.champion = ch.Progressing
	default:
		perf.champion = ch.NotYet
	}
	return nil
}

func (s *Service) championMetrics(ctx context.Context, sc school, operational string) (*championMetrics, error) {
	ct := rules.CoreTab
	// The school as the scan reads it: a live school with this School ID.
	var live bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school WHERE school_id = $1 AND deleted_at IS NULL)`, sc.SchoolID).Scan(&live); err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the school: %w", err)
	}
	if !live {
		return nil, nil
	}
	var total, completed int
	err := s.db.QueryRow(ctx, `
SELECT COUNT(sl.id) FILTER (WHERE sl.activity_type = ANY($3)),
  COUNT(sl.id) FILTER (WHERE sl.activity_type = ANY($3) AND sl.status = ANY($4))
FROM core_plan p LEFT JOIN core_activity_slot sl ON sl.core_plan_id = p.id
WHERE p.school_id = $1 AND NOT (p.status = ANY($2))
GROUP BY p.id, p.fy ORDER BY (p.fy = $5) DESC, p.fy DESC LIMIT 1`,
		sc.SchoolID, rules.Gate.Core.PlanClosedStatuses, ct.PackageWorkKinds, ct.SlotDoneStatuses, operational).Scan(&total, &completed)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the package's slots: %w", err)
	}
	var latestID string
	var latestAvg *float64
	err = s.db.QueryRow(ctx, `
SELECT r.id, r.average_score::float8 FROM ssa_record r JOIN school s ON s.id = r.school_id
WHERE s.school_id = $1 AND r.deleted_at IS NULL AND r.verification_status = 'confirmed'
ORDER BY r.date_of_ssa DESC, r.created_at DESC LIMIT 1`, sc.SchoolID).Scan(&latestID, &latestAvg)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the latest confirmed SSA: %w", err)
	}
	m := &championMetrics{totalSlots: total, completedSlots: completed, lowestIntervention: "None"}
	if latestAvg != nil {
		m.latestAvg = *latestAvg
	}
	rows, err := s.db.Query(ctx, `SELECT score::float8, intervention FROM ssa_score WHERE ssa_record_id = $1`, latestID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the latest SSA's scores: %w", err)
	}
	defer rows.Close()
	found := false
	for rows.Next() {
		var score *float64
		var intervention string
		if err := rows.Scan(&score, &intervention); err != nil {
			return nil, err
		}
		v := 0.0
		if score != nil {
			v = *score
		}
		if !found || v < m.lowestScore {
			m.lowestScore, m.lowestIntervention, found = v, intervention, true
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	m.eligible = m.latestAvg >= 8.0 && m.lowestScore >= 7.0 && completed >= ct.PackageWorkSlots
	return m, nil
}

type coreRecommendation struct {
	intervention, band, reason, state string
	score                             *float64
}

// coreRecommendations is intelligence.recommendations for one school: its
// records still open or planned, by rank.
func (s *Service) coreRecommendations(ctx context.Context, sc school) ([]coreRecommendation, error) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(intervention, ''), score::float8, COALESCE(score_band, ''), COALESCE(reason, ''), COALESCE(state, '')
FROM ssa_recommendation WHERE school_id = $1 AND state = ANY($2) ORDER BY rank, intervention`,
		sc.ID, rules.CoreTab.RecommendationShownStates)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading SSA recommendations: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (coreRecommendation, error) {
		var r coreRecommendation
		err := row.Scan(&r.intervention, &r.score, &r.band, &r.reason, &r.state)
		return r, err
	})
}
