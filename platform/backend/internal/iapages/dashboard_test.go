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

// A query the dashboard does not read goes to the existing application
// before anything is read.
func TestTheDashboardHandsOnTheViewsItDoesNotDraw(t *testing.T) {
	s := &Service{}
	for _, raw := range []string{"view=today&page=2", "view=collection&gap=missing", "page=2", "view=map&sort=name"} {
		query, _ := url.ParseQuery(raw)
		resp, served, err := s.dashboard(context.Background(), auth.Principal{ActiveRole: "ImpactAssessment"}, Role{Page: true}, query)
		if served || resp != nil || err != nil {
			t.Errorf("%q: served %v, %v", raw, served, err)
		}
	}
}

// A paged worklist's links carry the request's query in its own order, so
// it is drawn only when the pager carries one key besides its own.
func TestThePagerCarriesTheQueryOnlyWhenItsOrderIsKnown(t *testing.T) {
	cases := map[string]int{
		"view=collection":                              1,
		"view=collection&collection_page=2":            1,
		"view=collection&state=follow_up_due":          2,
		"view=collection&district=d&collection_page=3": 2,
	}
	for raw, want := range cases {
		query, _ := url.ParseQuery(raw)
		if got := carriedKeys(query, "collection_page"); got != want {
			t.Errorf("%q: %d, want %d", raw, got, want)
		}
	}
}
