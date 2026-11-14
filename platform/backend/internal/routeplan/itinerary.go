package routeplan

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
)

// Modes an itinerary is built in.
const (
	ModeFastest     = "fastest"
	ModeRecommended = "recommended"
	ModeAsGiven     = "as_given"
)

// startMinutes is the working day's start, in minutes after midnight.
func startMinutes() int {
	h, m, _ := strings.Cut(Rules.Day.Start, ":")
	hh, _ := strconv.Atoi(h)
	mm, _ := strconv.Atoi(m)
	return hh*60 + mm
}

// trip is what an itinerary is built from.
type trip struct {
	schools    []school // in the reader's order
	kinds      map[string]string
	locked     map[string]bool
	start      *LatLng
	startLabel string
	mode       string
}

// measure is the travel between the trip's points: the provider's road
// matrix where it answered, and which pairs it measured.
type measure struct {
	points []LatLng // start first when there is one
	offset int      // 1 with a start, else 0
	road   [][]Leg
}

func (m measure) idx(i int) int {
	if i < 0 {
		return 0
	}
	return i + m.offset
}

// seconds is the travel the optimizer weighs: the road where measured, the
// engine's planning estimate where not, nothing from no start.
func (m measure) seconds(i, j int) int64 {
	if i < 0 && m.offset == 0 {
		return 0
	}
	a, b := m.idx(i), m.idx(j)
	if m.road != nil && m.road[a][b].OK {
		return m.road[a][b].Seconds
	}
	return EstimateSeconds(StraightMeters(m.points[a], m.points[b]))
}

func (s *Service) measure(ctx context.Context, placed []school, start *LatLng) (measure, ProviderNote) {
	m := measure{}
	if start != nil {
		m.points, m.offset = append(m.points, *start), 1
	}
	// Road figures go to each school's entrance when it has one.
	for _, sc := range placed {
		m.points = append(m.points, sc.road())
	}
	if len(m.points) < 2 {
		return m, ProviderNote{}
	}
	road, err := s.router.Matrix(ctx, m.points)
	if err != nil {
		return m, noteFor(err)
	}
	m.road = road
	return m, ProviderNote{}
}

// ProviderNote says why road figures are missing, when they are.
type ProviderNote struct{ Message string }

func noteFor(err error) ProviderNote {
	if errors.Is(err, ErrUnavailable) {
		return ProviderNote{Message: "Road distances are unavailable just now; distances shown are straight lines."}
	}
	return ProviderNote{Message: "Road distances could not be worked out; distances shown are straight lines."}
}

// build lays out the trip as an itinerary.
func (s *Service) build(ctx context.Context, t trip) (*routesv1.Itinerary, ProviderNote) {
	out := &routesv1.Itinerary{Mode: t.mode, StartLabel: t.startLabel, Totals: &routesv1.RouteTotals{}}
	if t.start != nil {
		out.Start = &routesv1.Point{Lat: t.start.Lat, Lng: t.start.Lng}
	}
	placed := []school{}
	for _, sc := range t.schools {
		if sc.placed() {
			placed = append(placed, sc)
		} else {
			out.Unplaced = append(out.Unplaced, sc.pin)
		}
	}
	out.Totals.Selected = int32(len(t.schools))
	if len(placed) == 0 {
		return out, ProviderNote{}
	}
	m, note := s.measure(ctx, placed, t.start)
	stops := make([]Stop, len(placed))
	given := make([]int, len(placed))
	for i, sc := range placed {
		stops[i] = Stop{Visit: Rules.Day.VisitMinutes, Appointment: -1, Locked: t.locked[sc.pin.SchoolId]}
		given[i] = i
	}
	var plan Schedule
	if t.mode == ModeAsGiven {
		plan = Timed(given, stops, m.seconds, startMinutes())
	} else {
		plan = Optimize(given, stops, m.seconds, startMinutes())
	}
	// The road line through the chosen order, for the map.
	ordered := []LatLng{}
	if t.start != nil {
		ordered = append(ordered, *t.start)
	}
	for _, i := range plan.Order {
		ordered = append(ordered, placed[i].road())
	}
	var route Route
	if m.road != nil && len(ordered) > 1 {
		r, err := s.router.Route(ctx, ordered)
		if err == nil {
			route = r
		} else if note.Message == "" {
			note = noteFor(err)
		}
	}
	tot := out.Totals
	tot.RoadComplete = true
	prevLabel, prev := t.startLabel, -1
	for pos, i := range plan.Order {
		sc := placed[i]
		leg := &routesv1.RouteLeg{FromLabel: prevLabel, ToSchoolId: sc.pin.SchoolId}
		if prev >= 0 || t.start != nil {
			a, b := m.idx(prev), m.idx(i)
			leg.StraightLineMeters = StraightMeters(m.points[a], m.points[b])
			leg.EstimateSeconds = EstimateSeconds(leg.StraightLineMeters)
			hop := pos
			if t.start == nil {
				hop = pos - 1
			}
			switch {
			case hop >= 0 && hop < len(route.Legs) && route.Legs[hop].OK:
				leg.RoadAvailable, leg.RoadMeters, leg.RoadSeconds = true, route.Legs[hop].Meters, route.Legs[hop].Seconds
			case m.road != nil && m.road[a][b].OK:
				leg.RoadAvailable, leg.RoadMeters, leg.RoadSeconds = true, m.road[a][b].Meters, m.road[a][b].Seconds
			case m.road != nil:
				leg.RoadStatus = "No road route was found between these schools."
			default:
				leg.RoadStatus = note.Message
			}
			tot.StraightLineMeters += leg.StraightLineMeters
			tot.EstimateSeconds += leg.EstimateSeconds
			if leg.RoadAvailable {
				tot.RoadMeters += leg.RoadMeters
				tot.RoadSeconds += leg.RoadSeconds
			} else {
				tot.RoadComplete = false
			}
		}
		kind := t.kinds[sc.pin.SchoolId]
		if kind == "" {
			kind = "planned"
		}
		stop := &routesv1.ItineraryStop{Order: int32(pos + 1), School: sc.pin, Leg: leg, Arrival: clock(plan.Arrive[pos]),
			Departure: clock(plan.Depart[pos]), VisitMinutes: int32(stops[i].Visit), Locked: stops[i].Locked,
			Fixed: stops[i].Appointment >= 0, Conflict: plan.Conflicts[pos], Kind: kind}
		out.Stops = append(out.Stops, stop)
		tot.VisitMinutes += stop.VisitMinutes
		if stop.Conflict != "" {
			out.Conflicts = append(out.Conflicts, fmt.Sprintf("%s: %s", sc.pin.Name, stop.Conflict))
		}
		prevLabel, prev = sc.pin.Name, i
	}
	if len(placed) == 1 && t.start == nil {
		tot.RoadComplete = false
	}
	for _, p := range Simplify(route.Path, lineTolerance) {
		// The whole line rides on the first leg; the apps draw it once.
		out.Stops[0].Leg.Path = append(out.Stops[0].Leg.Path, &routesv1.Point{Lat: p.Lat, Lng: p.Lng})
	}
	tot.Feasible = int32(plan.Feasible())
	tot.FieldMinutes = int32(plan.Depart[len(plan.Depart)-1] - startMinutes())
	out.Explanation = explain(t.mode, len(placed), m.road != nil, len(out.Conflicts))
	return out, note
}

func explain(mode string, n int, road bool, conflicts int) string {
	by := "road travel time"
	if !road {
		by = "straight-line distance, because road distances are unavailable"
	}
	var s string
	switch mode {
	case ModeAsGiven:
		s = "Your order, timed by " + by + "."
	case ModeRecommended:
		s = fmt.Sprintf("Your %d school%s in the order with the least %s; a nearby eligible school is added only where it fits the day.", n, plural(n), by)
	default:
		s = fmt.Sprintf("Your %d school%s in the order with the least %s.", n, plural(n), by)
	}
	if conflicts == 1 {
		s += " 1 stop does not fit the working day."
	} else if conflicts > 1 {
		s += fmt.Sprintf(" %d stops do not fit the working day.", conflicts)
	}
	return s
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}
