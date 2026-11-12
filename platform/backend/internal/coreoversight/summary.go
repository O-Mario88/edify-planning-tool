package coreoversight

import (
	"slices"
	"strings"
)

// summary is intelligence.summarise: a group's figures, each with the
// schools it rests on. A rate is its totals' ratio, never a mean of rates.
type summary struct {
	schools, withCurrentSSA                   int
	avgLatest, avgChange                      *float64
	compared, improved, declined, notCompared int
	withPlan, packageComplete                 int
	visitsDone, visitsTarget                  int
	trainingsDone, trainingsTarget            int
	invited, attended                         int
	attendanceRate                            *int
	teachers, leaders                         int
	enrolCompared                             int
	enrolGrowthPct                            *float64
	readiness                                 map[string]int
	needsAttention                            int
}

// meanOne is intelligence._mean: the mean to one place of the figures there
// are, nil of none.
func meanOne(values []float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	return ptr(pyRound(pySum(values)/float64(len(values)), 1))
}

func summarise(rows []*school) summary {
	s := summary{schools: len(rows), readiness: map[string]int{}}
	latest, changes := []float64{}, []float64{}
	enrolChange, enrolBefore := 0, 0
	for _, r := range rows {
		if r.hasCurrentSSA() {
			s.withCurrentSSA++
			latest = append(latest, *r.ssaNow)
		}
		if r.trajectory != rules.Change.NotComparable {
			s.compared++
			switch r.trajectory {
			case rules.Change.Improved:
				s.improved++
			case rules.Change.Declined:
				s.declined++
			}
			if r.ssaChange != nil {
				changes = append(changes, *r.ssaChange)
			}
		}
		if r.hasPlan {
			s.withPlan++
			if done := r.packageComplete(); done != nil && *done {
				s.packageComplete++
			}
			s.visitsDone += min(r.visitsDone, r.visitsTarget)
			s.visitsTarget += r.visitsTarget
			s.trainingsDone += min(r.trainingsDone, r.trainingsTarget)
			s.trainingsTarget += r.trainingsTarget
		}
		s.invited += r.invited
		s.attended += r.attended
		if r.teachers != nil {
			s.teachers += *r.teachers
		}
		if r.leaders != nil {
			s.leaders += *r.leaders
		}
		if change := r.enrolChange(); change != nil {
			s.enrolCompared++
			enrolChange += *change
			enrolBefore += *r.enrolBefore
		}
		s.readiness[r.champion]++
		if slices.ContainsFunc(r.attention, func(reason string) bool { return reason != rules.Attention.Candidate }) {
			s.needsAttention++
		}
	}
	s.notCompared = len(rows) - s.compared
	s.avgLatest, s.avgChange = meanOne(latest), meanOne(changes)
	if s.invited > 0 {
		s.attendanceRate = ptr(pyRoundInt(float64(100*s.attended) / float64(s.invited)))
	}
	if s.enrolCompared > 0 && enrolBefore != 0 {
		s.enrolGrowthPct = ptr(pyRound(float64(100*enrolChange)/float64(enrolBefore), 1))
	}
	return s
}

// group is one of intelligence.groups: a label, its schools, its summary.
type group struct {
	label string
	rows  []*school
	sum   summary
}

// groupLabel is intelligence._group_label.
func groupLabel(r *school, by string) string {
	value := map[string]string{"cceo": r.owner, "district": r.district, "sub_region": r.subRegion, "cluster": r.cluster}[by]
	if value == "" {
		return "Not recorded"
	}
	return value
}

// groups is intelligence.groups: each school in its own group, largest
// first, then by label.
func groups(rows []*school, by string) []group {
	buckets := map[string][]*school{}
	order := []string{}
	for _, r := range rows {
		label := groupLabel(r, by)
		if _, seen := buckets[label]; !seen {
			order = append(order, label)
		}
		buckets[label] = append(buckets[label], r)
	}
	out := make([]group, 0, len(order))
	for _, label := range order {
		out = append(out, group{label: label, rows: buckets[label], sum: summarise(buckets[label])})
	}
	slices.SortStableFunc(out, func(a, b group) int {
		if len(a.rows) != len(b.rows) {
			return len(b.rows) - len(a.rows)
		}
		return strings.Compare(a.label, b.label)
	})
	return out
}
