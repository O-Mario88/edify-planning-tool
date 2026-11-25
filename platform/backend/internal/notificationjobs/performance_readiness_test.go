package notificationjobs

import (
	"testing"
	"time"
)

func TestTheReadinessNoticeIsSevenDaysBeforeEachQuarterEnds(t *testing.T) {
	d := func(y int, m time.Month, day int) time.Time { return time.Date(y, m, day, 0, 0, 0, 0, time.UTC) }
	cases := []struct {
		day     time.Time
		quarter string
		days    int
	}{
		{d(2026, 12, 24), "Q1", 7},
		{d(2027, 3, 24), "Q2", 7},
		{d(2027, 6, 23), "Q3", 7},
		{d(2027, 9, 23), "Q4", 7},
		{d(2026, 11, 25), "Q1", 36},
		{d(2026, 10, 1), "Q1", 91},
	}
	for _, c := range cases {
		q, days := daysToQuarterEnd(c.day)
		if q != c.quarter || days != c.days {
			t.Errorf("daysToQuarterEnd(%s) = %s %d, want %s %d", c.day.Format(time.DateOnly), q, days, c.quarter, c.days)
		}
	}
}
