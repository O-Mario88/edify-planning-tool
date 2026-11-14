package btportfolio

import (
	"strings"
	"testing"
	"time"
)

func TestThePeriodAFilterSelects(t *testing.T) {
	day := func(s string) time.Time { d, _ := time.Parse(time.DateOnly, s); return d }
	cases := []struct {
		f          Filters
		start, end string
	}{
		{Filters{}, "2026-10-01", "2027-10-01"},
		{Filters{"period_type": "quarter", "quarter": "Q1"}, "2026-10-01", "2027-01-01"},
		{Filters{"period_type": "quarter", "quarter": "Q3"}, "2027-04-01", "2027-07-01"},
		{Filters{"period_type": "month", "month": "4"}, "2027-01-01", "2027-02-01"},
		{Filters{"period_type": "month", "month": "13"}, "2026-10-01", "2027-10-01"},
		{Filters{"period_type": "quarter", "quarter": "Q9"}, "2026-10-01", "2027-10-01"},
	}
	for _, c := range cases {
		s, e := Period("2027", c.f)
		if !s.Equal(day(c.start)) || !e.Equal(day(c.end)) {
			t.Errorf("%v: %s..%s", c.f, s, e)
		}
	}
	s, e := Period("2027", Filters{"period_type": "custom", "custom_from": "2026-11-01", "custom_to": "2026-11-30"})
	if s.Format(time.RFC3339) != "2026-10-31T21:00:00Z" || e.Format(time.RFC3339) != "2026-11-30T21:00:00Z" {
		t.Errorf("custom: %s..%s", s, e)
	}
}

func TestFilterLoansNarrowsOnlyWhatIsAsked(t *testing.T) {
	a := &Args{}
	if FilterLoans(Filters{}, a) != "" || len(*a) != 0 {
		t.Error("no filters, no conditions")
	}
	got := FilterLoans(Filters{"mfi": "m1", "edtech": "no", "report_month": "2026-11", "q": "50%"}, a)
	if !strings.Contains(got, "l.mfi_id = $1") || !strings.Contains(got, "p.is_edtech IS FALSE") ||
		!strings.Contains(got, "l.disbursement_date >= $2::date") || (*a)[3] != `%50\%%` {
		t.Errorf("conditions: %s %v", got, *a)
	}
	b := &Args{}
	if strings.Contains(FilterLoans(Filters{"report_month": "2026-1"}, b), "disbursement_date") {
		t.Error("a malformed report month narrows nothing")
	}
}
