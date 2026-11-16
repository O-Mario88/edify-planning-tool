package routeplan

import (
	"context"
	"fmt"
	"slices"
	"testing"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
)

// line puts stops on a line: travel is |x_i - x_j| minutes.
func line(xs []int, start int) Cost {
	return func(i, j int) int64 {
		from := start
		if i >= 0 {
			from = xs[i]
		}
		d := xs[j] - from
		if d < 0 {
			d = -d
		}
		return int64(d * 60)
	}
}

func stops(n int) []Stop {
	out := make([]Stop, n)
	for i := range out {
		out[i] = Stop{Visit: 30, Appointment: -1}
	}
	return out
}

func TestTheFastestOrderWalksTheLine(t *testing.T) {
	xs := []int{40, 10, 30, 20}
	s := Optimize([]int{0, 1, 2, 3}, stops(4), line(xs, 0), 8*60)
	if !slices.Equal(s.Order, []int{1, 3, 2, 0}) || s.TravelSeconds != 40*60 {
		t.Errorf("order %v, travel %d", s.Order, s.TravelSeconds)
	}
	if s.Arrive[0] != 8*60+10 || s.Depart[0] != 8*60+40 || s.Feasible() != 4 {
		t.Errorf("times %v %v", s.Arrive, s.Depart)
	}
}

func TestALockedStopKeepsItsPlace(t *testing.T) {
	xs := []int{40, 10, 30, 20}
	st := stops(4)
	st[0].Locked = true
	s := Optimize([]int{0, 1, 2, 3}, st, line(xs, 0), 8*60)
	if s.Order[0] != 0 {
		t.Errorf("locked stop moved: %v", s.Order)
	}
}

func TestAnAppointmentIsKeptBeforeTravelIsSaved(t *testing.T) {
	xs := []int{10, 20}
	st := stops(2)
	st[1].Appointment = 8*60 + 15 // the far school expects us early
	s := Optimize([]int{0, 1}, st, line(xs, 0), 8*60)
	if !slices.Equal(s.Order, []int{1, 0}) || s.Conflicts[0] != "" {
		t.Errorf("order %v conflicts %v", s.Order, s.Conflicts)
	}
	early := Timed([]int{0}, []Stop{{Visit: 30, Appointment: 9 * 60}}, line([]int{10}, 0), 8*60)
	if early.Arrive[0] != 9*60 {
		t.Errorf("an early arrival waits for the appointment: %d", early.Arrive[0])
	}
}

func TestADayThatDoesNotFitSaysWhichStopsRunOver(t *testing.T) {
	xs := []int{60, 120, 180, 240, 300}
	st := stops(5)
	for i := range st {
		st[i].Visit = 60
	}
	s := Timed([]int{0, 1, 2, 3, 4}, st, line(xs, 0), 8*60)
	if s.Feasible() >= 5 || s.Conflicts[4] == "" || s.Conflicts[0] != "" {
		t.Errorf("conflicts %v", s.Conflicts)
	}
}

func TestLongDaysAreImprovedNotEnumerated(t *testing.T) {
	xs := []int{90, 10, 70, 30, 50, 20, 80, 40, 60, 100}
	s := Optimize([]int{0, 1, 2, 3, 4, 5, 6, 7, 8, 9}, stops(10), line(xs, 0), 6*60)
	if s.TravelSeconds != 100*60 {
		t.Errorf("travel %d, want the straight walk of 100 min", s.TravelSeconds/60)
	}
}

// tableRouter answers the matrix with one figure and the route through the
// chosen order with another, as OSRM's table and route services can.
type tableRouter struct{ table, route int64 }

func (r tableRouter) Name() string { return "test" }
func (r tableRouter) Matrix(_ context.Context, p []LatLng) ([][]Leg, error) {
	out := make([][]Leg, len(p))
	for i := range out {
		out[i] = make([]Leg, len(p))
		for j := range out[i] {
			out[i][j] = Leg{Meters: 1000, Seconds: r.table, OK: true}
		}
	}
	return out, nil
}
func (r tableRouter) Route(_ context.Context, p []LatLng) (Route, error) {
	legs := make([]Leg, len(p)-1)
	for i := range legs {
		legs[i] = Leg{Meters: 1200, Seconds: r.route, OK: true}
	}
	return Route{Legs: legs, Path: p}, nil
}

func TestArrivalsFollowTheLegsShown(t *testing.T) {
	s := &Service{router: tableRouter{table: 300, route: 420}}
	pins := []school{}
	for i, at := range []LatLng{{0.35, 32.75}, {0.36, 32.76}, {0.37, 32.77}} {
		pins = append(pins, school{at: at, pin: &routesv1.SchoolPin{
			SchoolId: fmt.Sprint("s", i), Name: fmt.Sprint("School ", i), LocationStatus: LocationVerified}})
	}
	it, _ := s.build(context.Background(), trip{schools: pins, mode: ModeAsGiven})
	if len(it.Stops) != 3 {
		t.Fatalf("%d stops", len(it.Stops))
	}
	minutes := func(c string) int {
		var h, m int
		_, _ = fmt.Sscanf(c, "%d:%d", &h, &m)
		return h*60 + m
	}
	for k := 1; k < len(it.Stops); k++ {
		leg := it.Stops[k].Leg
		want := minutes(it.Stops[k-1].Departure) + int(leg.RoadSeconds/60)
		if got := minutes(it.Stops[k].Arrival); got != want {
			t.Errorf("stop %d arrives %s; the stop before leaves %s and the leg shown is %d s",
				k+1, it.Stops[k].Arrival, it.Stops[k-1].Departure, leg.RoadSeconds)
		}
	}
	last := it.Stops[len(it.Stops)-1]
	if got := int(it.Totals.FieldMinutes); got != minutes(last.Departure)-startMinutes() {
		t.Errorf("field minutes %d, the last stop leaves %s", got, last.Departure)
	}
}
