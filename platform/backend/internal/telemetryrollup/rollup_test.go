package telemetryrollup

import (
	"testing"
	"time"
)

// The expected figures are Django's active_seconds_by_category for the same
// events, given in reverse order (the sort is the function's own).
func TestADaysTimeSplitsAsTheStandardSplitsIt(t *testing.T) {
	t0 := time.Date(2026, 11, 24, 8, 0, 0, 0, time.UTC)
	at := func(s float64) time.Time { return t0.Add(time.Duration(s * float64(time.Second))) }
	events := []event{
		{at(1260.9), "/ssa/"}, {at(1080), "/budget/"}, {at(900), "/budget/"}, {at(510.25), "todos/"},
		{at(500), "dashboard"}, {at(100), "/accounts/activities/1"}, {at(40.5), "/planning/x"}, {at(0), "/my-plan/"},
	}
	got := byCategory(events)
	want := map[string]int{planning: 269, execution: 130, other: 10}
	for k, v := range want {
		if got[k] != v {
			t.Fatalf("byCategory = %v, want %v", got, want)
		}
	}
}

func TestExecutionWinsARouteBothPrefixesMatch(t *testing.T) {
	cases := map[string]string{"/accounts/activities/9/proof": execution, "work-plan/add": planning,
		"/notifications/": other, "ssa/upload": execution}
	for route, want := range cases {
		if got := classifyRoute(route); got != want {
			t.Errorf("classifyRoute(%q) = %s, want %s", route, got, want)
		}
	}
}
