package iapages

import (
	"context"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The header's period is the server's (UTC) week, Monday to Sunday, as
// _ia_week_window reads timezone.now().
func TestTheDashboardWeekIsTheServersWeek(t *testing.T) {
	nairobi := time.FixedZone("EAT", 3*60*60)
	cases := []struct {
		now  time.Time
		want string
	}{
		{time.Date(2026, time.November, 17, 9, 0, 0, 0, time.UTC), "Nov 16 – Nov 22, 2026"},
		{time.Date(2026, time.November, 16, 0, 0, 0, 0, time.UTC), "Nov 16 – Nov 22, 2026"},
		{time.Date(2026, time.November, 22, 23, 59, 0, 0, time.UTC), "Nov 16 – Nov 22, 2026"},
		// Monday 01:00 in Nairobi is still Sunday on the server.
		{time.Date(2026, time.November, 23, 1, 0, 0, 0, nairobi), "Nov 16 – Nov 22, 2026"},
		{time.Date(2026, time.December, 30, 12, 0, 0, 0, time.UTC), "Dec 28 – Jan 3, 2027"},
	}
	for _, c := range cases {
		if got := weekRange(c.now); got != c.want {
			t.Errorf("%s: %q, want %q", c.now, got, c.want)
		}
	}
}

// Collection and Map, and a query the dashboard does not
// read, go to the existing application before anything is read.
func TestTheDashboardHandsOnTheViewsItDoesNotDraw(t *testing.T) {
	s := &Service{}
	for _, raw := range []string{"view=map", "view=collection", "view= Map ",
		"view=today&page=2", "view=operations&gap=missing", "page=2"} {
		query, _ := url.ParseQuery(raw)
		resp, served, err := s.dashboard(context.Background(), auth.Principal{ActiveRole: "ImpactAssessment"}, Role{Page: true}, query)
		if served || resp != nil || err != nil {
			t.Errorf("%q: served %v, %v", raw, served, err)
		}
	}
}
