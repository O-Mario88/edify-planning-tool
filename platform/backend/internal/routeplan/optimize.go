package routeplan

import (
	"fmt"
	"math"
)

// Stop is one school to visit, as the optimizer sees it.
type Stop struct {
	// Visit is the minutes at the school.
	Visit int
	// Appointment is the fixed time, in minutes after midnight, or -1.
	Appointment int
	// Locked keeps the stop at its place in the given order.
	Locked bool
}

// Cost is the travel seconds from stop i to stop j; i is -1 for the day's
// start.
type Cost func(i, j int) int64

// Schedule is an order and its times.
type Schedule struct {
	Order          []int
	Arrive, Depart []int // minutes after midnight, by position
	Travel         []int64
	Conflicts      []string // by position; empty where the stop fits
	TravelSeconds  int64
	Late           int // minutes past appointments and the day, summed
}

// Feasible is how many stops fit.
func (s Schedule) Feasible() int {
	n := 0
	for _, c := range s.Conflicts {
		if c == "" {
			n++
		}
	}
	return n
}

// appointmentGrace is how late an arrival may be and still keep a fixed
// appointment.
const appointmentGrace = 10

// exhaustiveMax is the most free stops tried in every order; past it the
// order is built nearest-first and improved by 2-opt.
const exhaustiveMax = 8

func clock(m int) string { return fmt.Sprintf("%02d:%02d", m/60, m%60) }

// Timed lays the stops out in order from the start time: travel, a wait for
// an appointment that is not due yet, the visit; and says which stops run
// late or past the working day (the day's available field time less the
// engine's buffer).
func Timed(order []int, stops []Stop, cost Cost, start int) Schedule {
	d := Rules.Day
	last := start + d.AvailableMinutes - d.BufferMinutes
	s := Schedule{Order: order}
	t, prev := start, -1
	for _, i := range order {
		sec := cost(prev, i)
		s.TravelSeconds += sec
		s.Travel = append(s.Travel, sec)
		t += int(math.Round(float64(sec) / 60))
		conflict := ""
		if a := stops[i].Appointment; a >= 0 {
			if t < a {
				t = a
			} else if t > a+appointmentGrace {
				conflict = fmt.Sprintf("Arrives %s, after the %s appointment", clock(t), clock(a))
				s.Late += t - a
			}
		}
		s.Arrive = append(s.Arrive, t)
		t += stops[i].Visit
		s.Depart = append(s.Depart, t)
		if conflict == "" && t > last {
			conflict = fmt.Sprintf("Finishes %s, past the working day", clock(t))
			s.Late += t - last
		}
		s.Conflicts = append(s.Conflicts, conflict)
		prev = i
	}
	return s
}

// better is whether a beats b: fewer late minutes first, then less travel.
func better(a, b Schedule) bool {
	if a.Late != b.Late {
		return a.Late < b.Late
	}
	return a.TravelSeconds < b.TravelSeconds
}

// Optimize orders the stops for the least lateness and then the least
// travel. given is the reader's order; locked stops keep their positions in
// it.
func Optimize(given []int, stops []Stop, cost Cost, start int) Schedule {
	slots, free := []int{}, []int{}
	for pos, i := range given {
		if !stops[i].Locked {
			slots = append(slots, pos)
			free = append(free, i)
		}
	}
	place := func(perm []int) []int {
		order := append([]int(nil), given...)
		for k, pos := range slots {
			order[pos] = perm[k]
		}
		return order
	}
	best := Timed(given, stops, cost, start)
	if len(free) <= exhaustiveMax {
		permute(free, func(perm []int) {
			if s := Timed(place(perm), stops, cost, start); better(s, best) {
				best = s
			}
		})
		return best
	}
	perm := nearestFirst(free, cost)
	cur := Timed(place(perm), stops, cost, start)
	for improved := true; improved; {
		improved = false
		for a := 0; a < len(perm)-1; a++ {
			for b := a + 1; b < len(perm); b++ {
				next := append([]int(nil), perm...)
				for x, y := a, b; x < y; x, y = x+1, y-1 {
					next[x], next[y] = next[y], next[x]
				}
				if s := Timed(place(next), stops, cost, start); better(s, cur) {
					perm, cur, improved = next, s, true
				}
			}
		}
	}
	if better(cur, best) {
		return cur
	}
	return best
}

func nearestFirst(free []int, cost Cost) []int {
	left := append([]int(nil), free...)
	out, prev := []int{}, -1
	for len(left) > 0 {
		k := 0
		for j := range left {
			if cost(prev, left[j]) < cost(prev, left[k]) {
				k = j
			}
		}
		prev = left[k]
		out = append(out, prev)
		left = append(left[:k], left[k+1:]...)
	}
	return out
}

// permute calls visit with every order of xs (Heap's algorithm).
func permute(xs []int, visit func([]int)) {
	a := append([]int(nil), xs...)
	var gen func(k int)
	gen = func(k int) {
		if k <= 1 {
			visit(a)
			return
		}
		for i := 0; i < k-1; i++ {
			gen(k - 1)
			if k%2 == 0 {
				a[i], a[k-1] = a[k-1], a[i]
			} else {
				a[0], a[k-1] = a[k-1], a[0]
			}
		}
		gen(k - 1)
	}
	gen(len(a))
}
