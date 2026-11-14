package targets

import (
	"testing"
	"time"
)

func ptr(n int) *int { return &n }

func TestStatusFollowsThePaceBands(t *testing.T) {
	cases := []struct {
		pct               *int
		pace              int
		started, assigned bool
		want              string
	}{
		{nil, 50, true, false, "Not Assigned"},
		{ptr(10), 50, false, true, "Not Started"},
		{ptr(101), 50, true, true, "Exceeded"},
		{ptr(100), 50, true, true, "Complete"},
		{ptr(45), 50, true, true, "On Track"},
		{ptr(44), 50, true, true, "Slightly Behind"},
		{ptr(35), 50, true, true, "Slightly Behind"},
		{ptr(34), 50, true, true, "High Risk"},
		{ptr(20), 50, true, true, "High Risk"},
		{ptr(19), 50, true, true, "Critical"},
		{nil, 0, true, true, "On Track"},
	}
	for _, c := range cases {
		if got, _ := Status(c.pct, c.pace, c.started, c.assigned); got != c.want {
			t.Errorf("%v pace %d: %s, want %s", c.pct, c.pace, got, c.want)
		}
	}
	if s, tone := Display(Status(ptr(30), 50, true, true)); s != "Needs Attention" || tone != "warning" {
		t.Errorf("High Risk shows as %s/%s", s, tone)
	}
}

func TestTheWeightedShareLeavesOutAreasWithNoTargetAndRoundsHalfEven(t *testing.T) {
	areas := []Area{{Key: "a", Weight: 1}, {Key: "b", Weight: 1}, {Key: "c", Weight: 5}}
	targets := Series{"a": {8}, "b": {8}}
	achieved := Series{"a": {1}, "b": {1}, "c": {9}}
	pct, ach, tgt := WeightedPct(areas, targets, achieved, []int{1})
	// 12.5% each: half-even rounds to 12; c has no target and is left out.
	if pct == nil || *pct != 12 || ach != 11 || tgt != 16 {
		t.Errorf("got %v %d %d", pct, ach, tgt)
	}
	if pct, _, _ := WeightedPct(areas, Series{}, achieved, []int{1}); pct != nil {
		t.Errorf("no target anywhere: %v, want none", *pct)
	}
}

func TestAnAnnualTargetIsSplitWithTheRemainderInTheEarlyMonths(t *testing.T) {
	r := &Roster{areas: map[string][]Area{"u": {{Key: "school_visits", Annual: ptr(14)}}}}
	got := r.Targets(Person{UserID: "u"})["school_visits"]
	want := [12]int{2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1}
	if got != want {
		t.Errorf("%v, want %v", got, want)
	}
}

func TestThePaceCountsWorkingDaysLessHolidaysAndLeave(t *testing.T) {
	start, end := MonthRange("2027", 2) // November 2026
	c := calendar{holidays: map[string]bool{}, leave: map[string]bool{}}
	if got := c.workingDays(start, end); got != 21 {
		t.Fatalf("November 2026 has %d weekdays, want 21", got)
	}
	day := date(2026, time.November, 13)
	if got := c.expectedPace(start, end, day); got != 48 { // 10 of 21 days
		t.Errorf("pace on the 13th: %d", got)
	}
	c.leave["2026-11-02"], c.holidays["2026-11-30"] = true, true
	if got := c.expectedPace(start, end, day); got != 47 { // 9 of 19
		t.Errorf("pace with leave and a holiday: %d", got)
	}
	if c.expectedPace(start, end, start.AddDate(0, 0, -1)) != 0 || c.expectedPace(start, end, end) != 100 {
		t.Error("before the period the pace is 0, after it 100")
	}
}

func TestTheYearsMonthsAndQuarters(t *testing.T) {
	if MonthOfFY(date(2026, time.October, 1), "2027") != 1 || MonthOfFY(date(2027, time.September, 30), "2027") != 12 ||
		MonthOfFY(date(2027, time.October, 1), "2027") != 0 {
		t.Error("month of the year")
	}
	if s, e := QuarterRange("2027", "Q2"); !s.Equal(date(2027, time.January, 1)) || !e.Equal(date(2027, time.April, 1)) {
		t.Errorf("Q2: %v %v", s, e)
	}
	if MonthLabel("2027", 4) != "January 2027" || QuarterOfMonth(4) != "Q2" {
		t.Error("labels")
	}
}
