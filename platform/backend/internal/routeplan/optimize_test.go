package routeplan

import (
	"slices"
	"testing"
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
