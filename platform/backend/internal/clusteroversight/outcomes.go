package clusteroversight

import "strconv"

// enrolment is outcomes.EnrolmentSummary for one cluster, as far as the
// page reads it: like for like, only the schools with a figure in both
// years.
type enrolment struct {
	compared, before, after int
	// grew is how many compared schools' enrolment rose.
	grew int
}

// growthPct is outcomes._growth_pct over the compared schools: nil with
// none compared, or from nothing.
func (e enrolment) growthPct() *float64 {
	if e.compared == 0 || e.before == 0 {
		return nil
	}
	growth := pyRound(float64(100*(e.after-e.before))/float64(e.before), 1)
	return &growth
}

// enrolmentOf is outcomes.enrolment_by_cluster for one cluster's members.
func enrolmentOf(members []string, yearly map[string]map[string]int, fy string) enrolment {
	previous := previousFY(fy)
	out := enrolment{}
	for _, school := range members {
		before, hadBefore := yearly[school][previous]
		after, hasAfter := yearly[school][fy]
		if !hadBefore || !hasAfter {
			continue
		}
		out.compared++
		out.before += before
		out.after += after
		if after-before > 0 {
			out.grew++
		}
	}
	return out
}

// previousFY is str(int(fy) - 1); the page's year is one of its options.
func previousFY(fy string) string {
	year, _ := strconv.Atoi(fy)
	return strconv.Itoa(year - 1)
}

// learning is outcomes.LearningSummary for one cluster, as far as the page
// reads it.
type learning struct {
	compared, improved int
	before, after      *float64
}

// change is LearningSummary.change, in percentage points.
func (l learning) change() *float64 {
	if l.before == nil || l.after == nil {
		return nil
	}
	change := pyRound(*l.after-*l.before, 1)
	return &change
}

// schoolScores is outcomes._school_scores: each school's score for a year,
// the mean of its class results as a share of the marks available, weighted
// by the learners tested. The shares are added in the order the results are
// read, as the page adds them. Keyed by school, then year.
func schoolScores(rows []learningRow) map[string]map[string]float64 {
	type total struct{ weighted, learners float64 }
	totals := map[[2]string]*total{}
	order := [][2]string{}
	for _, row := range rows {
		if row.Learners == 0 {
			continue
		}
		key := [2]string{row.SchoolID, row.FY}
		if totals[key] == nil {
			totals[key] = &total{}
			order = append(order, key)
		}
		totals[key].weighted = addShare(totals[key].weighted, row.Mean, row.Max, float64(row.Learners))
		totals[key].learners += float64(row.Learners)
	}
	out := map[string]map[string]float64{}
	for _, key := range order {
		if out[key[0]] == nil {
			out[key[0]] = map[string]float64{}
		}
		out[key[0]][key[1]] = pyRound(totals[key].weighted/totals[key].learners, 1)
	}
	return out
}

// learningOf is outcomes.learning_by_cluster for one cluster's members.
func learningOf(members []string, scores map[string]map[string]float64, fy string) learning {
	previous := previousFY(fy)
	out := learning{}
	befores, afters := []float64{}, []float64{}
	for _, school := range members {
		before, hadBefore := scores[school][previous]
		after, hasAfter := scores[school][fy]
		if !hadBefore || !hasAfter {
			continue
		}
		out.compared++
		befores, afters = append(befores, before), append(afters, after)
		if pyRound(after-before, 1) > 0 {
			out.improved++
		}
	}
	out.before, out.after = meanOrNil(befores), meanOrNil(afters)
	return out
}

// stories is outcomes.StorySummary for one cluster, as far as the page
// reads it: every story that is not a draft, and the approved among them.
type stories struct{ count, approved int }

// plan is scores._session_plan for one cluster: of the year's meetings and
// group trainings still in the plan, how many were due by today, how many of
// those were delivered, and whether any is planned at all.
type plan struct {
	meetingsDelivered, meetingsDue   int
	trainingsDelivered, trainingsDue int
	meetingPlanned, trainingPlanned  bool
}

func (p *plan) add(row planRow, today string) {
	delivered := in(rules.DeliveredStatuses, row.Status)
	due := delivered || (row.Planned != "" && row.Planned <= today)
	if in(rules.TrainingSessionTypes, row.Type) {
		p.trainingPlanned = true
		if due {
			p.trainingsDue++
		}
		if delivered {
			p.trainingsDelivered++
		}
		return
	}
	p.meetingPlanned = true
	if due {
		p.meetingsDue++
	}
	if delivered {
		p.meetingsDelivered++
	}
}

// ssaNow is workspace._ssa_now for one cluster: the mean over its member
// schools of their latest confirmed record of the year, and the intervention
// they score lowest in.
type ssaNow struct {
	average *float64
	weakest string
	// weakestMean is the weakest intervention's mean; read only with one.
	weakestMean float64
}

// schoolScore is year_comparison.school_current_scores for one school.
type schoolScore struct {
	overall *float64
	// areas are the school's scores in the order they were read.
	areas []scoreRow
}

// currentScores is year_comparison.school_current_scores: each school's
// latest confirmed record of the year, its average (the record's own, else
// the mean of the scores it carries) and every intervention it scored, each
// to two places.
func currentScores(records []yearRecordRow, scores []scoreRow) map[string]schoolScore {
	latest := map[string]yearRecordRow{}
	schoolOf := map[string]string{}
	for _, record := range records {
		if _, seen := latest[record.SchoolID]; !seen {
			latest[record.SchoolID] = record
			schoolOf[record.ID] = record.SchoolID
		}
	}
	areas := map[string][]scoreRow{}
	for _, score := range scores {
		school, ok := schoolOf[score.RecordID]
		if !ok {
			continue
		}
		score.Score = pyRound(score.Score, 2)
		replaced := false
		for i := range areas[school] {
			if areas[school][i].Intervention == score.Intervention {
				areas[school][i], replaced = score, true
			}
		}
		if !replaced {
			areas[school] = append(areas[school], score)
		}
	}
	out := map[string]schoolScore{}
	for school, record := range latest {
		s := schoolScore{areas: areas[school]}
		switch {
		case record.Average != nil:
			average := pyRound(*record.Average, 2)
			s.overall = &average
		case len(s.areas) > 0:
			values := make([]float64, len(s.areas))
			for i, a := range s.areas {
				values[i] = a.Score
			}
			average := pyRound(mean(values), 2)
			s.overall = &average
		}
		out[school] = s
	}
	return out
}

// ssaNowOf is workspace._ssa_now for one cluster's members, in their order.
func ssaNowOf(members []string, scored map[string]schoolScore) ssaNow {
	overalls := []float64{}
	byArea := map[string][]float64{}
	for _, school := range members {
		s, ok := scored[school]
		if !ok {
			continue
		}
		if s.overall != nil {
			overalls = append(overalls, *s.overall)
		}
		for _, a := range s.areas {
			byArea[a.Intervention] = append(byArea[a.Intervention], a.Score)
		}
	}
	out := ssaNow{}
	if len(overalls) > 0 {
		average := pyRound(mean(overalls), 1)
		out.average = &average
	}
	first := true
	for key, values := range byArea {
		m := mean(values)
		if first || m < out.weakestMean || (m == out.weakestMean && key < out.weakest) {
			out.weakest, out.weakestMean, first = key, m, false
		}
	}
	return out
}

// addShare is Python's `acc += mean / maximum * 100 * learners`: the product
// is rounded before it is added. Go may fuse a multiply and an add into one
// step with a single rounding (arm64 does), which Python never does, so the
// product is converted on its own to keep the two apart.
func addShare(acc, mean, maximum, learners float64) float64 {
	return acc + float64(mean/maximum*100*learners)
}
