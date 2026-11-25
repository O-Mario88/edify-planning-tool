package hrforms

import (
	"errors"
	"testing"
	"time"
)

// derived_status: no evidence is Missing; past its expiry Expired; within 30
// days Due Soon (the 30th day included); otherwise Compliant.
func TestDerivedStatus(t *testing.T) {
	today := time.Date(2026, 11, 25, 0, 0, 0, 0, time.UTC)
	at := func(days int) *time.Time { d := today.AddDate(0, 0, days); return &d }
	cases := []struct {
		name     string
		expiry   *time.Time
		evidence bool
		want     string
	}{
		{"no evidence", at(400), false, "Missing"},
		{"expired yesterday", at(-1), true, "Expired"},
		{"expires today", at(0), true, "Due Soon"},
		{"in thirty days", at(30), true, "Due Soon"},
		{"in thirty-one days", at(31), true, "Compliant"},
		{"no expiry", nil, true, "Compliant"},
	}
	for _, tc := range cases {
		if got := derivedStatus(tc.expiry, tc.evidence, today); got != tc.want {
			t.Errorf("%s: %s, want %s", tc.name, got, tc.want)
		}
	}
}

// _date: blank is no day; anything not YYYY-MM-DD is the form's refusal.
func TestDay(t *testing.T) {
	if d, err := day("  "); d != nil || err != nil {
		t.Fatalf("blank: %v, %v", d, err)
	}
	if d, err := day("2026-12-05"); err != nil || d.Format("2006-01-02") != "2026-12-05" {
		t.Fatalf("a day: %v, %v", d, err)
	}
	var r *Refusal
	for _, raw := range []string{"5/12/2026", "2026-02-30", "20-11-2026"} {
		if _, err := day(raw); !errors.As(err, &r) || r.Message != "Dates use the format YYYY-MM-DD." {
			t.Errorf("%q: %v", raw, err)
		}
	}
}

// The gateway takes lower-case field names only, so a country's tick box is
// named in lower case.
func TestPulseCountryField(t *testing.T) {
	for country, want := range map[string]string{"Uganda": "country_uganda", "South Sudan": "country_south_sudan", "DRC-East": "country_drc_east"} {
		if got := PulseCountryField(country); got != want {
			t.Errorf("%s: %s, want %s", country, got, want)
		}
	}
}

// A tick box is ticked unless empty, false, off or 0.
func TestChecked(t *testing.T) {
	for v, want := range map[string]bool{"1": true, "on": true, "true": true, "": false, "false": false, "off": false, "0": false} {
		if checked(v) != want {
			t.Errorf("%q", v)
		}
	}
}
