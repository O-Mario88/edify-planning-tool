package coreoversight

import (
	"slices"
	"strconv"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusteroversight"
)

// school is intelligence.CoreSchoolPerformance: one Core school's figures
// for the year. A figure the records cannot give is nil, never a zero.
type school struct {
	id, code, name, schoolType, typeLabel string
	district, subRegion                   string
	clusterID, cluster                    string
	ownerID, owner                        string

	ssaNow, ssaBefore, ssaChange *float64
	trajectory                   string
	weakest, weakestLabel        string
	weakestScore                 *float64

	hasPlan                                                   bool
	visitsDone, visitsTarget, trainingsDone, trainingsTarget  int
	handoversAssigned, handoversScheduled, handoversCompleted int

	invited, attended int
	teachers, leaders *int
	enrolBefore       *int
	enrolAfter        *int
	learnBefore       *float64
	learnAfter        *float64
	champion          string
	championScore     *float64
	attention         []string
}

func (s *school) hasCurrentSSA() bool { return s.ssaNow != nil }

func (s *school) trajectoryLabel() string { return rules.TrajectoryLabels[s.trajectory] }

func (s *school) trajectoryTone() string { return rules.TrajectoryTones[s.trajectory] }

// packageComplete is package_complete: nil without a plan.
func (s *school) packageComplete() *bool {
	if !s.hasPlan {
		return nil
	}
	done := s.visitsTarget+s.trainingsTarget > 0 && s.visitsDone >= s.visitsTarget && s.trainingsDone >= s.trainingsTarget
	return &done
}

// packagePct is package_pct: the share of the package done, each kind
// capped at its target; nil without a plan or a target.
func (s *school) packagePct() *int {
	target := s.visitsTarget + s.trainingsTarget
	if !s.hasPlan || target == 0 {
		return nil
	}
	done := min(s.visitsDone, s.visitsTarget) + min(s.trainingsDone, s.trainingsTarget)
	pct := pyRoundInt(float64(100*done) / float64(target))
	return &pct
}

// packageLabel is package_label: f"{package_pct}%", "None%" for a plan with
// no target.
func (s *school) packageLabel() string {
	if !s.hasPlan {
		return "No package"
	}
	pct := s.packagePct()
	if pct == nil {
		return "None%"
	}
	return strconv.Itoa(*pct) + "%"
}

func (s *school) attendanceRate() *int {
	if s.invited == 0 {
		return nil
	}
	rate := pyRoundInt(float64(100*s.attended) / float64(s.invited))
	return &rate
}

func (s *school) enrolChange() *int {
	if s.enrolBefore == nil || s.enrolAfter == nil {
		return nil
	}
	change := *s.enrolAfter - *s.enrolBefore
	return &change
}

// enrolGrowthPct is outcomes._growth_pct.
func (s *school) enrolGrowthPct() *float64 {
	if s.enrolBefore == nil || *s.enrolBefore == 0 || s.enrolAfter == nil {
		return nil
	}
	pct := pyRound(float64(100*(*s.enrolAfter-*s.enrolBefore))/float64(*s.enrolBefore), 1)
	return &pct
}

func (s *school) learnChange() *float64 {
	if s.learnBefore == nil || s.learnAfter == nil {
		return nil
	}
	change := pyRound(*s.learnAfter-*s.learnBefore, 1)
	return &change
}

func previousFY(fy string) string {
	n, err := strconv.Atoi(fy)
	if err != nil {
		return ""
	}
	return strconv.Itoa(n - 1)
}

func ptr[T any](v T) *T { return &v }

// meanTwo is year_comparison._mean: the mean to two places, nil of none.
func meanTwo(values []float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	return ptr(pyRound(pySum(values)/float64(len(values)), 2))
}

// performance is intelligence.performance: each school's figures for fy, in
// the order the schools were read.
func performance(r *records, fy, operational string) []*school {
	out := make([]*school, 0, len(r.Schools))
	byID := map[string]*school{}
	for _, row := range r.Schools {
		s := &school{
			id: row.ID, code: row.Code, name: row.Name, schoolType: row.Type,
			district: row.District, clusterID: row.ClusterID, ownerID: row.OwnerID,
			trajectory: rules.Change.NotComparable, champion: rules.Champion.Insufficient,
		}
		if row.Type != "" {
			s.typeLabel = row.Type
			if label, ok := rules.SchoolTypes[row.Type]; ok {
				s.typeLabel = label
			}
		}
		s.owner = "Unassigned"
		if label, ok := r.Owners[s.ownerID]; ok && s.ownerID != "" {
			s.owner = label
		}
		s.cluster = r.Clusters[s.clusterID]
		if row.SubRegionID != "" {
			s.subRegion = r.SubRegions[row.SubRegionID]
		}
		if _, seen := byID[s.id]; !seen {
			out = append(out, s)
		}
		byID[s.id] = s
	}
	if len(out) == 0 {
		return out
	}
	readSSA(r, byID, fy)
	readPackage(r, byID)
	readParticipation(r, byID)
	readOutcomes(r, byID, fy)
	readChampion(r, out, byID, operational)
	for _, s := range out {
		s.attention = attentionOf(s)
	}
	return out
}

// readSSA is _read_ssa.
func readSSA(r *records, byID map[string]*school, fy string) {
	// school_year_scores: each school's and year's newest record, its own
	// average else the mean of its scores.
	type yearKey struct{ school, fy string }
	latest := map[yearKey]yearRecordRow{}
	order := []yearKey{}
	for _, row := range r.YearRecords {
		key := yearKey{row.SchoolID, row.FY}
		if _, seen := latest[key]; !seen {
			latest[key] = row
			order = append(order, key)
		}
	}
	carried := map[string][]float64{}
	for _, row := range r.YearCarried {
		carried[row.RecordID] = append(carried[row.RecordID], row.Score)
	}
	for _, key := range order {
		row := latest[key]
		s := byID[key.school]
		if s == nil {
			continue
		}
		var value *float64
		if row.Average != nil {
			value = ptr(pyRound(*row.Average, 2))
		} else {
			value = meanTwo(carried[row.ID])
		}
		if key.fy == fy {
			s.ssaNow = value
		} else {
			s.ssaBefore = value
		}
	}

	// school_current_scores' areas: the year's newest record's scores.
	recordOf := map[string]string{}
	for _, row := range r.CurrentRecords {
		if _, seen := recordOf[row.SchoolID]; !seen {
			recordOf[row.SchoolID] = row.ID
		}
	}
	schoolOf := map[string]string{}
	for school, record := range recordOf {
		schoolOf[record] = school
	}
	areas := map[string]map[string]float64{}
	for _, row := range r.CurrentScores {
		school, ok := schoolOf[row.RecordID]
		if !ok {
			continue
		}
		if areas[school] == nil {
			areas[school] = map[string]float64{}
		}
		areas[school][row.Intervention] = pyRound(row.Score, 2)
	}

	// The verdict over the comparable pairs, under the published rules.
	now := make([]clusteroversight.SSAReading, len(r.LatestNow))
	for i, row := range r.LatestNow {
		now[i] = clusteroversight.SSAReading{SchoolID: row.SchoolID, RecordID: row.RecordID, TakenOn: row.TakenOn}
	}
	before := make([]clusteroversight.SSAReading, len(r.LatestBefore))
	for i, row := range r.LatestBefore {
		before[i] = clusteroversight.SSAReading{SchoolID: row.SchoolID, RecordID: row.RecordID, TakenOn: row.TakenOn}
	}
	scores := make([]clusteroversight.SSAScore, len(r.PairScores))
	for i, row := range r.PairScores {
		scores[i] = clusteroversight.SSAScore{RecordID: row.RecordID, Intervention: row.Intervention, Score: row.Score}
	}
	published := make([]clusteroversight.ChangeRule, len(r.ChangeRules))
	for i, row := range r.ChangeRules {
		published[i] = clusteroversight.ChangeRule{Intervention: row.Intervention, Country: row.Country, Direction: row.Direction, Threshold: row.Threshold}
	}
	verdicts := clusteroversight.SchoolVerdicts(now, before, scores, published, r.Countries)

	for id, s := range byID {
		if v, ok := verdicts[id]; ok && v.Classification != rules.Change.NotComparable {
			s.trajectory = v.Classification
			s.ssaChange = ptr(pyRound(v.MeanDelta, 1))
		}
		scored := areas[id]
		if len(scored) == 0 {
			continue
		}
		keys := make([]string, 0, len(scored))
		for key := range scored {
			keys = append(keys, key)
		}
		// min(areas, key=lambda k: (areas[k], k)).
		slices.SortFunc(keys, func(a, b string) int {
			switch {
			case scored[a] < scored[b]:
				return -1
			case scored[a] > scored[b]:
				return 1
			case a < b:
				return -1
			case a > b:
				return 1
			}
			return 0
		})
		s.weakest = keys[0]
		s.weakestLabel = interventionLabel(keys[0])
		s.weakestScore = ptr(scored[keys[0]])
	}
}

// readPackage is _read_package: the year's plan, as the plan records its
// completion. A plan filed under the school's id or its School ID is its,
// the last read speaking for it.
func readPackage(r *records, byID map[string]*school) {
	byKey := map[string]*school{}
	for _, s := range byID {
		byKey[s.id] = s
	}
	for _, s := range byID {
		if s.code != "" {
			byKey[s.code] = s
		}
	}
	for _, plan := range r.Plans {
		s := byKey[plan.SchoolKey]
		if s == nil {
			continue
		}
		s.hasPlan = true
		s.visitsDone, s.visitsTarget = plan.VisitsDone, plan.VisitsTarget
		s.trainingsDone, s.trainingsTarget = plan.TrainingsDone, plan.TrainingsTarget
	}
	for _, row := range r.Handovers {
		if s := byID[row.SchoolID]; s != nil {
			s.handoversAssigned, s.handoversScheduled, s.handoversCompleted = row.Assigned, row.Scheduled, row.Completed
		}
	}
}

// addHeadcount is intelligence._add: a missing figure stays missing until
// one is recorded.
func addHeadcount(current **int, value *int) {
	if value == nil {
		return
	}
	n := *value
	if *current != nil {
		n += **current
	}
	*current = &n
}

// readParticipation is _read_participation.
func readParticipation(r *records, byID map[string]*school) {
	for _, row := range r.Register {
		s := byID[row.SchoolID]
		if s == nil {
			continue
		}
		if row.Invited {
			s.invited++
			if row.Attended {
				s.attended++
			}
		}
		if row.Attended {
			addHeadcount(&s.teachers, row.Teachers)
			addHeadcount(&s.leaders, row.Leaders)
		}
	}
	for _, row := range r.Trainings {
		if s := byID[row.SchoolID]; s != nil {
			addHeadcount(&s.teachers, row.Teachers)
			addHeadcount(&s.leaders, row.Leaders)
		}
	}
}

// readOutcomes is _read_outcomes: enrolment, and the learning score of each
// year (clusters.outcomes._school_scores: the class results as a share of
// the marks available, weighted by the learners tested).
func readOutcomes(r *records, byID map[string]*school, fy string) {
	for _, row := range r.Enrolment {
		s := byID[row.SchoolID]
		if s == nil {
			continue
		}
		if row.FY == fy {
			s.enrolAfter = ptr(row.Enrollment)
		} else {
			s.enrolBefore = ptr(row.Enrollment)
		}
	}
	type bucket struct{ weighted, learners float64 }
	totals := map[[2]string]*bucket{}
	for _, row := range r.Learning {
		if row.Learners == 0 {
			continue
		}
		weight := float64(row.Learners)
		share := float64(row.Mean/row.Max) * 100
		key := [2]string{row.SchoolID, row.FY}
		b := totals[key]
		if b == nil {
			b = &bucket{}
			totals[key] = b
		}
		// Each product rounded before it is added, as Python adds.
		b.weighted += float64(share * weight)
		b.learners += weight
	}
	for key, b := range totals {
		s := byID[key[0]]
		if s == nil {
			continue
		}
		pct := pyRound(b.weighted/b.learners, 1)
		if key[1] == fy {
			s.learnAfter = &pct
		} else if key[1] == previousFY(fy) {
			s.learnBefore = &pct
		}
	}
}

// metrics is ChampionEligibilityService._score_values, the parts the page
// reads.
type metrics struct {
	score     float64
	eligible  bool
	latestAvg float64
}

// scoreValues is the official formula. Each step is rounded on its own (no
// fused multiply-add), as Python computes it.
func scoreValues(earliestAvg, latestAvg float64, latest []float64, slots, completed, closed, clean, ssas int) metrics {
	latestWeighted := float64(float64(latestAvg/10.0) * 40.0)
	delta := latestAvg - earliestAvg
	deltaScore := float64(min(max(float64(delta/3.0), 0.0), 1.0) * 25.0)
	lowest := 0.0
	if len(latest) > 0 {
		lowest = slices.Min(latest)
	}
	balance := float64(float64(min(lowest, 7.0)/7.0) * 15.0)
	pkg := 0.0
	if slots > 0 {
		pkg = float64(completed) / float64(slots)
	}
	packageScore := float64(pkg * 10.0)
	evidence := 1.0
	if closed > 0 {
		evidence = float64(clean) / float64(closed)
	}
	evidenceScore := float64(evidence * 5.0)
	sustain := 2.5
	if ssas >= 2 {
		sustain = 5.0
	}
	total := float64(float64(float64(float64(float64(latestWeighted+deltaScore)+balance)+packageScore)+evidenceScore) + sustain)
	return metrics{
		score:     pyRound(total, 1),
		eligible:  latestAvg >= 8.0 && lowest >= 7.0 && completed >= rules.Champion.PackageWorkSlots,
		latestAvg: latestAvg,
	}
}

// scan is ChampionEligibilityService.scan over the records: each School ID
// the rule can judge (a Core profile, a live plan and a confirmed SSA) and
// its metrics.
func scan(r *records, operational string) map[string]metrics {
	out := map[string]metrics{}
	if len(r.ScanProfiles) == 0 {
		return out
	}
	plans := map[string]scanPlanRow{}
	for _, plan := range r.ScanPlans {
		selected, ok := plans[plan.Code]
		if !ok || (plan.FY == operational && selected.FY != operational) {
			plans[plan.Code] = plan
		}
	}
	ssas := map[string][]scanSSARow{}
	for _, row := range r.ScanSSAs {
		ssas[row.Code] = append(ssas[row.Code], row)
	}
	scores := map[string][]float64{}
	for _, row := range r.ScanScores {
		v := 0.0
		if row.Score != nil {
			v = *row.Score
		}
		scores[row.RecordID] = append(scores[row.RecordID], v)
	}
	schools := map[string]scanSchoolRow{}
	for _, row := range r.ScanSchools {
		schools[row.Code] = row
	}
	orZero := func(v *float64) float64 {
		if v == nil {
			return 0
		}
		return *v
	}
	for _, code := range r.ScanProfiles {
		sc, okSchool := schools[code]
		plan, okPlan := plans[code]
		confirmed := ssas[code]
		if !okSchool || !okPlan || len(confirmed) == 0 {
			continue
		}
		latest := confirmed[len(confirmed)-1]
		out[code] = scoreValues(orZero(confirmed[0].Average), orZero(latest.Average), scores[latest.ID],
			plan.Total, plan.Completed, sc.Closed, sc.Clean, len(confirmed))
	}
	return out
}

// readChampion is _read_champion.
func readChampion(r *records, schools []*school, byID map[string]*school, operational string) {
	ch := rules.Champion
	idOf := map[string]*school{}
	for _, s := range schools {
		if s.code != "" {
			idOf[s.code] = byID[s.id]
		}
	}
	stored := map[string]*string{}
	for _, row := range r.Stored {
		stored[row.Code] = row.Status
	}
	judged := scan(r, operational)
	for _, s := range schools {
		if s.schoolType == ch.ChampionType {
			s.champion = ch.Champion
		}
	}
	for code, s := range idOf {
		m, ok := judged[code]
		if ok {
			s.championScore = ptr(m.score)
		}
		status := stored[code]
		switch {
		case s.schoolType == ch.ChampionType || (status != nil && in(ch.StoredChampion, *status)):
			s.champion = ch.Champion
		case !s.hasPlan || !s.hasCurrentSSA():
			s.champion = ch.Insufficient
		case ok && m.eligible:
			s.champion = ch.Potential
		case (ok && m.latestAvg >= ch.LatestAvg) || s.trajectory == rules.Change.Improved:
			s.champion = ch.Progressing
		default:
			s.champion = ch.NotYet
		}
	}
}

// attentionOf is intelligence._attention.
func attentionOf(s *school) []string {
	a := rules.Attention
	reasons := []string{}
	if s.trajectory == rules.Change.Declined {
		reasons = append(reasons, a.Declined)
	}
	if s.weakestScore != nil && *s.weakestScore < a.CriticalBelow {
		reasons = append(reasons, a.Critical)
	}
	if !s.hasCurrentSSA() {
		reasons = append(reasons, a.NoSSA)
	}
	if s.handoversAssigned != 0 {
		reasons = append(reasons, a.Handover)
	}
	if done := s.packageComplete(); done != nil && !*done {
		reasons = append(reasons, a.Package)
	}
	if s.champion == rules.Champion.Potential {
		reasons = append(reasons, a.Candidate)
	}
	return reasons
}
