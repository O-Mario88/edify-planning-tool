package routeplan

import (
	"context"
	"sort"
	"time"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// Suggestion limits: the straight-line shortlist the gate is asked about,
// and the suggestions measured by road and shown.
const (
	shortlist = 15
	shown     = 5
)

type candidate struct {
	sc       school
	gate     visitgate.Gate
	added    int64 // metres or seconds of the cheapest insertion
	addedSec int64
	measure  string
}

// insertion is the cheapest place to slot point x into the route through
// pts (in order), weighed by cost, and what it adds by cost and by length.
// Road figures need not add up exactly (a detour can measure shorter than
// the direct leg), so nothing is ever reported as saved: the least added is 0.
func insertion(pts []LatLng, x LatLng, cost, length func(a, b LatLng) int64) (int64, int64) {
	if len(pts) == 0 {
		return 0, 0
	}
	added := func(f func(a, b LatLng) int64, at int) int64 {
		switch {
		case at == 0:
			return f(x, pts[0])
		case at == len(pts):
			return f(pts[len(pts)-1], x)
		}
		return f(pts[at-1], x) + f(x, pts[at]) - f(pts[at-1], pts[at])
	}
	best := 0
	for at := 1; at <= len(pts); at++ {
		if added(cost, at) < added(cost, best) {
			best = at
		}
	}
	return max(0, added(cost, best)), max(0, added(length, best))
}

// suggest is Schools Near My Route: the reader's schools near the day's
// stops that the existing visit rules let them schedule, cheapest to add
// first, each with what it adds and why. Schools the rules refuse are not
// offered.
func (s *Service) suggest(ctx context.Context, p auth.Principal, route *routesv1.Itinerary, planned []school, now time.Time, district, cluster string) ([]*routesv1.Suggestion, error) {
	pts := []LatLng{}
	for _, st := range route.GetStops() {
		if pt := st.GetSchool().GetPoint(); pt != nil {
			pts = append(pts, LatLng{pt.Lat, pt.Lng})
		}
	}
	except := []string{}
	for _, sc := range planned {
		except = append(except, sc.pin.SchoolId)
	}
	near, err := nearby(ctx, s.db, p, now, pts, except, district, cluster)
	if err != nil {
		return nil, err
	}
	straight := func(a, b LatLng) int64 { return StraightMeters(a, b) }
	cands := make([]candidate, len(near))
	for i, sc := range near {
		_, meters := insertion(pts, sc.at, straight, straight)
		cands[i] = candidate{sc: sc, added: meters, measure: "straight_line"}
	}
	sort.SliceStable(cands, func(i, j int) bool { return cands[i].added < cands[j].added })
	fy := schooldirectory.OperationalFY(now)
	rules := schoolprofile.GateRules()
	eligible := []candidate{}
	for _, c := range cands[:min(len(cands), shortlist)] {
		g, err := visitgate.Of(ctx, s.db, rules, visitgate.School{ID: c.sc.pin.SchoolId, Code: c.sc.pin.Code, Name: c.sc.pin.Name,
			Type: typeOf(c.sc)}, fy, fy)
		if err != nil {
			return nil, err
		}
		if g.StaffCanSchedule {
			c.gate = g
			eligible = append(eligible, c)
		}
	}
	eligible = eligible[:min(len(eligible), shown)]
	s.byRoad(ctx, pts, eligible)
	sort.SliceStable(eligible, func(i, j int) bool {
		if a, b := !eligible[i].gate.HasSSA, !eligible[j].gate.HasSSA; a != b {
			return a
		}
		return eligible[i].addedSec < eligible[j].addedSec
	})
	used := route.GetTotals().GetFieldMinutes()
	out := []*routesv1.Suggestion{}
	for _, c := range eligible {
		pin := c.sc.pin
		pin.Status = "suggested"
		label, reason := "Eligible", "Eligible for a support visit this financial year, near your planned schools."
		if !c.gate.HasSSA {
			label, reason = "High Priority", "No confirmed SSA this financial year; eligible for a support visit, near your planned schools."
		}
		fits := int64(used)+c.addedSec/60+int64(Rules.Day.VisitMinutes) <= int64(Rules.Day.AvailableMinutes-Rules.Day.BufferMinutes)
		if !fits {
			reason += " Adding it would run past the working day."
		}
		out = append(out, &routesv1.Suggestion{School: pin, AddedMeters: c.added, AddedSeconds: c.addedSec, Measure: c.measure,
			Reason: reason, Label: label, Eligible: true, FitsDay: fits})
	}
	return out, nil
}

// byRoad re-measures the insertions by road, in one matrix over the stops
// and the candidates; where the provider is unavailable the straight-line
// figures stand, labelled as such, with the engine's planning estimate.
func (s *Service) byRoad(ctx context.Context, pts []LatLng, cands []candidate) {
	for i := range cands {
		cands[i].addedSec = EstimateSeconds(cands[i].added)
	}
	if len(cands) == 0 || len(pts) == 0 {
		return
	}
	all := append([]LatLng(nil), pts...)
	index := map[LatLng]int{}
	for i, x := range pts {
		index[x] = i
	}
	for _, c := range cands {
		index[c.sc.at] = len(all)
		all = append(all, c.sc.at)
	}
	m, err := s.router.Matrix(ctx, all)
	if err != nil {
		return
	}
	for i := range cands {
		ok := true
		look := func(a, b LatLng) Leg {
			l := m[index[a]][index[b]]
			ok = ok && l.OK
			return l
		}
		secs, meters := insertion(pts, cands[i].sc.at, func(a, b LatLng) int64 { return look(a, b).Seconds },
			func(a, b LatLng) int64 { return look(a, b).Meters })
		if ok {
			cands[i].added, cands[i].addedSec, cands[i].measure = meters, secs, "road"
		}
	}
}

// typeOf is the school's type value for the gate (the pin carries its words).
func typeOf(sc school) string {
	for k, v := range Rules.SchoolTypes {
		if v == sc.pin.Category {
			return k
		}
	}
	return sc.pin.Category
}
