package leavetracker

import (
	"testing"
	"time"
)

func TestTheWindowHoldsBetweenFourAndTwelveWeeks(t *testing.T) {
	cases := []struct {
		raw     string
		present bool
		want    int
	}{{"", false, 8}, {"", true, 8}, {"abc", true, 8}, {"5", true, 5}, {"99", true, 12}, {"-3", true, 4}, {" 6 ", true, 6}}
	for _, c := range cases {
		if got := weeksAsked(c.raw, c.present); got != c.want {
			t.Errorf("weeksAsked(%q) = %d, want %d", c.raw, got, c.want)
		}
	}
}

func TestWeekHeadersNameTheirDays(t *testing.T) {
	if got := weekHeader(0, time.Date(2026, 11, 9, 0, 0, 0, 0, time.UTC)); got != "Wk 1 · 9–15 Nov" {
		t.Errorf("same month: %q", got)
	}
	if got := weekHeader(3, time.Date(2026, 11, 30, 0, 0, 0, 0, time.UTC)); got != "Wk 4 · 30 Nov–6 Dec" {
		t.Errorf("across months: %q", got)
	}
}

func TestCollisionsListTheWorstFirst(t *testing.T) {
	heat := []HeatRow{
		{StaffID: "a", Name: "A", Role: "CCEO", Weeks: []HeatWeek{{Stranded: 1}}},
		{StaffID: "b", Name: "B", Role: "CCEO", Weeks: []HeatWeek{{Stranded: 2}, {Stranded: 1}}},
		{StaffID: "c", Name: "C", Role: "CCEO", Weeks: []HeatWeek{{}}},
	}
	p := collisions(heat).GetPanel()
	if p.Title != "4 school visits scheduled against absent staff" || p.Subtitle[:16] != "2 staff members " {
		t.Errorf("card: %q / %q", p.Title, p.Subtitle)
	}
	if p.Items[0].GetLinks().Links[0].Text != "B" || p.Items[1].GetLinks().Links[0].Caption != "· CCEO" {
		t.Errorf("order: %v", p.Items)
	}
	if collisions(heat[2:]) != nil {
		t.Error("no collisions, no card")
	}
}
