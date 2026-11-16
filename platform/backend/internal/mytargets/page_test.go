package mytargets

import (
	"net/url"
	"testing"
	"time"
)

func TestTheQueryChoosesTheYearAndMonthAsTheViewReadsThem(t *testing.T) {
	now := time.Date(2026, 11, 17, 9, 0, 0, 0, local)
	cases := []struct {
		raw   string
		fy    string
		month int
		ok    bool
	}{
		{"", "2027", 0, true},
		{"fy=2026", "2026", 0, true},
		{"fy=2027&month=3", "2027", 3, true},
		{"month=01", "2027", 1, true},
		{"month=13", "2027", 0, true},
		{"month=0", "2027", 0, true},
		{"month=-1", "2027", 0, true},
		{"month=%EF%BC%91", "", 0, false},
		{"fy=2099", "", 0, false},
		{"fy=abc", "", 0, false},
		{"page=2", "", 0, false},
	}
	for _, c := range cases {
		query, err := url.ParseQuery(c.raw)
		if err != nil {
			t.Fatal(err)
		}
		fy, month, ok := choose(query, now)
		if fy != c.fy || month != c.month || ok != c.ok {
			t.Errorf("%q: %q %d %v, want %q %d %v", c.raw, fy, month, ok, c.fy, c.month, c.ok)
		}
	}
}

func TestStatusForReadsThePaceBands(t *testing.T) {
	cases := []struct {
		achieved, target, pace int
		started                bool
		status, tone           string
	}{
		{3, 0, 50, true, "Not Assigned", "neutral"},
		{3, 10, 50, false, "Not Started", "neutral"},
		{11, 10, 50, true, "Exceeded", "success"},
		{10, 10, 50, true, "Complete", "success"},
		{45, 100, 50, true, "On Track", "success"},
		{30, 100, 50, true, "At Risk", "warning"},
		{29, 100, 50, true, "Off Track", "danger"},
		// round(): 12.5% is 12, 37.5% is 38.
		{1, 8, 17, true, "On Track", "success"},
		{3, 8, 58, true, "At Risk", "warning"},
	}
	for _, c := range cases {
		status, tone := statusFor(c.achieved, c.target, c.pace, c.started)
		if status != c.status || tone != c.tone {
			t.Errorf("%+v: %s %s", c, status, tone)
		}
	}
}

func TestFiguresAndTitlesPrintAsPython(t *testing.T) {
	for n, want := range map[int]string{0: "0", 999: "999", 1000: "1,000", 1234567: "1,234,567", -1500: "-1,500"} {
		if got := comma(n); got != want {
			t.Errorf("comma(%d) = %q, want %q", n, got, want)
		}
	}
	for in, want := range map[string]string{"word of god": "Word Of God", "teacher's room": "Teacher'S Room"} {
		if got := pyTitle(in); got != want {
			t.Errorf("pyTitle(%q) = %q, want %q", in, got, want)
		}
	}
}
