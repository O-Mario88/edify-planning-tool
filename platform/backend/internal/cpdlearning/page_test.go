package cpdlearning

import (
	"net/url"
	"testing"
	"time"
)

func TestMoneyIsWholeUnitsWithCommasAndAHalfToTheEven(t *testing.T) {
	for cents, want := range map[int64]string{
		0: "0", 25000: "250", 25050: "250", 25150: "252", -2000: "-20", 123456789: "1,234,568", -100000000: "-1,000,000",
	} {
		if got := whole(cents); got != want {
			t.Errorf("whole(%d) = %q, want %q", cents, got, want)
		}
	}
	if got := money("USD", 504000); got != "USD 5,040" {
		t.Errorf("money = %q", got)
	}
}

func TestTheQueryHandsThePageOnWhenItCannotBeRead(t *testing.T) {
	now := time.Date(2026, time.November, 16, 9, 0, 0, 0, time.UTC)
	for raw, served := range map[string]bool{
		"":                       true,
		"fy=2026&status=bogus":   true,
		"page=2&fund_status=all": true,
		"page=two":               false,
		"page=-1":                false,
		"fy=1999":                false,
		"partial=tracker":        false,
	} {
		query, err := url.ParseQuery(raw)
		if err != nil {
			t.Fatal(err)
		}
		if _, ok := readAsk(query, now); ok != served {
			t.Errorf("readAsk(%q) served = %v, want %v", raw, ok, served)
		}
	}
}
