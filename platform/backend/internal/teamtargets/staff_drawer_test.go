package teamtargets

import (
	"testing"
	"time"
)

// The view's year and month: a month 1 to 12 as asked, else this month in
// the current year and the first in another; a year that is not four digits
// and a month with a non-ASCII digit are handed on.
func TestStaffPeriodReadsTheViewsYearAndMonth(t *testing.T) {
	today := time.Date(2026, time.November, 25, 0, 0, 0, 0, time.UTC)
	for _, c := range []struct {
		fy, month string
		wantFY    string
		want      int
		ok        bool
	}{
		{"", "", "2027", 2, true},
		{"2026", "7", "2026", 7, true},
		{"2026", "", "2026", 1, true},
		{"2027", "13", "2027", 2, true},
		{"2027", "abc", "2027", 2, true},
		{"2027", "0", "2027", 2, true},
		{"20x6", "3", "", 0, false},
		{"2027", "²", "", 0, false},
	} {
		fy, month, ok := staffPeriod(map[string]string{"fy": c.fy, "month": c.month}, "2027", today)
		if fy != c.wantFY || month != c.want || ok != c.ok {
			t.Errorf("fy=%q month=%q: %q %d %v, want %q %d %v", c.fy, c.month, fy, month, ok, c.wantFY, c.want, c.ok)
		}
	}
}

// str.title capitalises each run of letters: "submitted to pl" reads
// "Submitted To Pl".
func TestPyTitleIsPythonsTitle(t *testing.T) {
	for in, want := range map[string]string{"submitted to pl": "Submitted To Pl", "ia verified": "Ia Verified", "x2y": "X2Y", "": ""} {
		if got := pyTitle(in); got != want {
			t.Errorf("%q: %q, want %q", in, got, want)
		}
	}
}
