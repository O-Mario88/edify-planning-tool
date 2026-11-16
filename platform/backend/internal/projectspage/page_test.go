package projectspage

import (
	"net/url"
	"testing"
	"time"
)

func TestTheFollowUpIsWrittenAsDjangosDefaultDateTime(t *testing.T) {
	at := func(h, m int) time.Time { return time.Date(2026, 12, 1, h, m, 0, 0, zone) }
	for _, c := range []struct {
		t    time.Time
		want string
	}{
		{at(10, 0), "Dec. 1, 2026, 10 a.m."},
		{at(13, 30), "Dec. 1, 2026, 1:30 p.m."},
		{at(0, 0), "Dec. 1, 2026, midnight"},
		{at(12, 0), "Dec. 1, 2026, noon"},
		{at(0, 5), "Dec. 1, 2026, 12:05 a.m."},
		{time.Date(2026, 9, 3, 9, 0, 0, 0, zone), "Sept. 3, 2026, 9 a.m."},
		{time.Date(2026, 5, 3, 9, 0, 0, 0, zone), "May 3, 2026, 9 a.m."},
	} {
		if got := djangoDateTime(c.t); got != c.want {
			t.Errorf("%v: %q, want %q", c.t, got, c.want)
		}
	}
}

func TestMoneyIsCompactedAsTheDashboardCompactsIt(t *testing.T) {
	for amount, want := range map[int64]string{
		0: "UGX 0", 900: "UGX 900", 50_000: "UGX 50K", 170_000: "UGX 170K", 2_500: "UGX 2K",
		2_670_000: "UGX 2.7M", 2_480_000_000: "UGX 2.48B", 1_000_000: "UGX 1.0M",
	} {
		if got := ugx(amount); got != want {
			t.Errorf("%d: %q, want %q", amount, got, want)
		}
	}
	if got := thousands(1252); got != "1,252" {
		t.Errorf("thousands: %q", got)
	}
}

func TestATabKeepsThePagesFiltersInTheFormsOrder(t *testing.T) {
	q := url.Values{"status": {"planning"}, "tab": {"x"}, "fy": {"2026"}, "portfolio_page": {"2"}, "type": {"pilot"}}
	if got := keptQuery(q); got != "fy=2026&type=pilot&status=planning&" {
		t.Errorf("kept: %q", got)
	}
	if got := keptQuery(url.Values{"tab": {"x"}}); got != "" {
		t.Errorf("kept with only a tab: %q", got)
	}
}
