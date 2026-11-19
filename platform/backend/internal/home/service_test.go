package home

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestHomeWordsTheDayAsTheExistingPage(t *testing.T) {
	at := func(hour, minute int) time.Time { return time.Date(2026, 11, 19, hour, minute, 0, 0, kampala) }
	for _, c := range []struct {
		at   time.Time
		want string
	}{{at(5, 0), "Good morning"}, {at(11, 59), "Good morning"}, {at(12, 0), "Good afternoon"}, {at(16, 59), "Good afternoon"}, {at(17, 0), "Good evening"}} {
		if got := greeting(c.at); got != c.want {
			t.Errorf("%s: %q, want %q", c.at.Format("15:04"), got, c.want)
		}
	}
	midnight, afternoon := at(0, 0), at(14, 30)
	if clock(&midnight) != "" || clock(nil) != "" || clock(&afternoon) != "2:30 PM" {
		t.Errorf("clock: %q %q %q", clock(&midnight), clock(nil), clock(&afternoon))
	}
}

func TestTheYearTurnsInOctoberOnTheUTCDay(t *testing.T) {
	for _, c := range []struct {
		at   time.Time
		want string
	}{
		{time.Date(2026, 9, 30, 23, 0, 0, 0, time.UTC), "2026"},
		{time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC), "2027"},
		{time.Date(2027, 1, 1, 0, 0, 0, 0, time.UTC), "2027"},
	} {
		if got := operationalFY(c.at); got != c.want {
			t.Errorf("%s: %s, want %s", c.at, got, c.want)
		}
	}
}

func TestHomeHandsOnWhatTheExistingApplicationStillAnswers(t *testing.T) {
	for _, c := range []struct {
		p    auth.Principal
		want bool
	}{
		{auth.Principal{Account: auth.Account{ActiveRole: "CCEO"}}, true},
		{auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}, true},
		{auth.Principal{Account: auth.Account{ActiveRole: "PartnerFieldOfficer"}}, false},
		{auth.Principal{Account: auth.Account{ActiveRole: "ClusterLeader"}}, false},
		{auth.Principal{Account: auth.Account{ActiveRole: "CCEO", InActingAppointment: true}}, false},
		{auth.Principal{Account: auth.Account{ActiveRole: "Nobody"}}, false},
	} {
		if got := Served(c.p); got != c.want {
			t.Errorf("%s (acting %v): served %v, want %v", c.p.ActiveRole, c.p.InActingAppointment, got, c.want)
		}
	}
}

func TestQueueFiguresWaitValuelessThenTakeTheirTone(t *testing.T) {
	waiting := QueueFigures(nil, true)
	if len(waiting) != 1 || !waiting[0].GetLoading() || waiting[0].GetValue() != "" || waiting[0].GetTone() != "plain" {
		t.Fatalf("a planner's waiting tile: %v", waiting)
	}
	got := QueueFigures(map[string]int{"waiting_me": 2, "critical": 0}, false)
	if len(got) != 3 || got[0].GetValue() != "2" || got[0].GetTone() != "caution" || got[2].GetTone() != "plain" || got[1].GetValue() != "0" {
		t.Fatalf("a queue's tiles: %v", got)
	}
}
