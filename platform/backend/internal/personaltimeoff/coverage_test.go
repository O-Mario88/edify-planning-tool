package personaltimeoff

import (
	"testing"
	"time"
)

func TestACoverageIsLiveOnlyInsideItsWindowWhileActive(t *testing.T) {
	now := time.Date(2026, 11, 18, 12, 0, 0, 0, time.UTC)
	start, end := now.Add(-time.Hour), now.Add(time.Hour)
	cases := []struct {
		name string
		c    coverage
		want string
		live bool
	}{
		{"in its window", coverage{status: "active", start: start, end: end}, "active", true},
		{"at its very end", coverage{status: "active", start: start, end: now}, "active", true},
		{"not started", coverage{status: "active", start: end, end: end.Add(time.Hour)}, "expired", false},
		{"revoked", coverage{status: "revoked", start: start, end: end, revoked: true}, "revoked", false},
		{"ended", coverage{status: "active", start: start.Add(-time.Hour), end: start}, "expired", false},
	}
	for _, tc := range cases {
		label, live := tc.c.state(now)
		if label != tc.want || live != tc.live {
			t.Errorf("%s: got %q %v, want %q %v", tc.name, label, live, tc.want, tc.live)
		}
	}
	if got := person("Moses K.", ""); got != "Moses K." {
		t.Errorf("a person without a role: %q", got)
	}
}
