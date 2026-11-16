package routeplan

import (
	"testing"
	"time"
)

func TestTheFieldDayRunsInOrder(t *testing.T) {
	at := func(h, m int) time.Time { return time.Date(2026, 11, 18, h, m, 0, 0, kampala) }
	d := fieldDay{}
	steps := []struct {
		ev      dayEvent
		now     time.Time
		refused string
	}{
		{dayEvent{kind: "arrive", school: "a"}, at(7, 50), "Start the field day first."},
		{dayEvent{kind: "start"}, at(7, 55), "Save the day's schools or choose them first."},
		{dayEvent{kind: "save", order: []string{"a", "b"}}, at(7, 56), ""},
		{dayEvent{kind: "start", today: false}, at(7, 57), "A field day can only start on its own day."},
		{dayEvent{kind: "start", today: true}, at(8, 0), ""},
		{dayEvent{kind: "leave", school: "a"}, at(8, 5), "Arrive at this school first."},
		{dayEvent{kind: "arrive", school: "z"}, at(8, 6), "That school is not on this field day."},
		{dayEvent{kind: "arrive", school: "a"}, at(8, 10), ""},
		{dayEvent{kind: "arrive", school: "a"}, at(8, 20), ""}, // again: keeps the first time
		{dayEvent{kind: "leave", school: "a"}, at(9, 10), ""},
		{dayEvent{kind: "arrive", school: "b"}, at(9, 20), ""},
		{dayEvent{kind: "save", order: []string{"b", "a"}}, at(9, 25), "The field day has started; its order is kept."},
		{dayEvent{kind: "end"}, at(15, 0), ""},
		{dayEvent{kind: "arrive", school: "b"}, at(15, 5), "This field day has ended."},
		{dayEvent{kind: "dance"}, at(15, 6), "Say start, arrive, leave or end."},
	}
	for i, st := range steps {
		next, refused := d.apply(st.ev, st.now)
		if refused != st.refused {
			t.Fatalf("step %d (%s %s): refused %q, want %q", i, st.ev.kind, st.ev.school, refused, st.refused)
		}
		if refused == "" {
			d = next
		}
	}
	if got := d.stops["a"]; !got.arrived.Equal(at(8, 10)) || !got.left.Equal(at(9, 10)) {
		t.Errorf("stop a: %+v", got)
	}
	if got := d.stops["b"]; got.left == nil || !got.left.Equal(at(15, 0)) {
		t.Errorf("ending the day leaves the open stop at the end: %+v", got)
	}
	if !d.started.Equal(at(8, 0)) || !d.ended.Equal(at(15, 0)) {
		t.Errorf("day: started %v ended %v", d.started, d.ended)
	}
}

func TestStartingKeepsTheOrderItIsGiven(t *testing.T) {
	now := time.Date(2026, 11, 18, 8, 0, 0, 0, kampala)
	d, refused := fieldDay{}.apply(dayEvent{kind: "start", today: true, order: []string{"b", "a"}}, now)
	if refused != "" || len(d.order) != 2 || d.order[0] != "b" || d.saved == nil {
		t.Fatalf("start with an order: %+v, %q", d, refused)
	}
}

func TestASavedOrderIsCheckedBeforeItIsKept(t *testing.T) {
	now := time.Date(2026, 11, 18, 8, 0, 0, 0, kampala)
	for name, order := range map[string][]string{
		"nothing":     {},
		"a duplicate": {"a", "a"},
		"a blank":     {"a", " "},
	} {
		if _, refused := (fieldDay{}).apply(dayEvent{kind: "save", order: order}, now); refused == "" {
			t.Errorf("%s: saved", name)
		}
	}
	long := make([]string, maxDayStops+1)
	for i := range long {
		long[i] = string(rune('a'+i%26)) + string(rune('a'+i/26))
	}
	if _, refused := (fieldDay{}).apply(dayEvent{kind: "save", order: long}, now); refused == "" {
		t.Error("a day longer than the limit was saved")
	}
}
