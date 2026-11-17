package acting

import (
	"context"
	"errors"
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// A table's period reads as short_period_label: the days, then the month.
func TestThePeriodIsTheMonthsDays(t *testing.T) {
	cases := map[string]string{"2026-11": "1 – 30 Nov 2026", "2027-02": "1 – 28 Feb 2027", "2028-02": "1 – 29 Feb 2028", "bad": "bad"}
	for month, want := range cases {
		if got := shortPeriod(month); got != want {
			t.Errorf("%s: %q, want %q", month, got, want)
		}
	}
}

// The page refuses a role it does not open to, and hands on a query it does
// not read, before anything is read.
func TestThePageRefusesAndHandsOnBeforeReading(t *testing.T) {
	pg := &Page{}
	if _, served, err := pg.Build(context.Background(), auth.Principal{ActiveRole: "Accountant"}, PagePath, nil); !served || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("the Accountant: %v %v", served, err)
	}
	query, _ := url.ParseQuery("sort=name")
	if _, served, err := pg.Build(context.Background(), auth.Principal{ActiveRole: "CountryDirector"}, PagePath, query); served || err != nil {
		t.Errorf("an unread key: %v %v", served, err)
	}
	if _, served, _ := pg.Build(context.Background(), auth.Principal{ActiveRole: "CountryDirector"}, "/acting-leadership/x", nil); served {
		t.Error("another path is served")
	}
}
