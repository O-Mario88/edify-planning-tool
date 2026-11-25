package teamtargets

import (
	"math"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// pyRound is Python's round to an integer (half to even).
func pyRound(v float64) int { return int(math.RoundToEven(v)) }

// row is one team member as get_page carries them: _member, and what the
// page adds (portfolio, SF ID compliance, core share, rank, Lead).
type row struct {
	targets.TeamMember
	member               Member
	initials             string
	districts            []string
	districtLabel        string
	schools              []school
	sfCompliance, sfMiss int
	corePct, rank        *int
	leadName             string
}

// team is the page's members and the areas their figures are read over.
type team struct {
	rows        []*row
	areas       []targets.Area // agreed across the whole team
	metricAreas []targets.Area // the category's (all for "overall")
}

// series is team_series: each area's monthly sum across the members.
func (t team) series(achieved bool) targets.Series {
	out := targets.Series{}
	for _, a := range t.areas {
		var s [12]int
		for _, r := range t.rows {
			src := r.Targets
			if achieved {
				src = r.Achieved
			}
			v := src[a.Key]
			for i := range s {
				s[i] += v[i]
			}
		}
		out[a.Key] = s
	}
	return out
}

// weighted is team_wpct: each member's priority-weighted result for the
// months averaged (those with no target left out), and the totals.
func (t team) weighted(months []int) (int, int, int) {
	sum, n, achieved, target := 0, 0, 0, 0
	for _, r := range t.rows {
		pct, a, tg := targets.WeightedPct(r.MetricAreas, r.Targets, r.Achieved, months)
		achieved += a
		target += tg
		if pct != nil {
			sum += *pct
			n++
		}
	}
	if n == 0 {
		return 0, achieved, target
	}
	return pyRound(float64(sum) / float64(n)), achieved, target
}

// raw is raw_pct: the team's summed achievement over its summed target in
// the category's areas.
func (t team) raw(months []int) (int, int, int) {
	tt, ta := t.series(false), t.series(true)
	target, achieved := 0, 0
	for _, a := range t.metricAreas {
		for _, m := range months {
			target += tt[a.Key][m-1]
			achieved += ta[a.Key][m-1]
		}
	}
	if target == 0 {
		return 0, achieved, target
	}
	return pyRound(float64(achieved) / float64(target) * 100), achieved, target
}

// statusIn is whether a member's month status is one of these.
func statusIn(r *row, statuses ...string) bool {
	for _, s := range statuses {
		if r.Status == s {
			return true
		}
	}
	return false
}

func (t team) where(statuses ...string) []*row {
	out := []*row{}
	for _, r := range t.rows {
		if statusIn(r, statuses...) {
			out = append(out, r)
		}
	}
	return out
}
