package personaltimeoff

import (
	"net/url"
	"testing"
	"time"
)

func TestTheCalendarMonthIsReadAsPythonReadsIt(t *testing.T) {
	today := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC)
	cases := map[string]string{
		"":                   "2026-11",
		"month=12&year=2026": "2026-12",
		"month=+3":           "2026-03",
		"month=%201_2%20":    "2026-12",
		"month=13":           "2026-11",
		"month=0":            "2026-11",
		"year=1999":          "2026-11",
		"month=x&year=2027":  "2026-11",
		"month=2&year=2101":  "2026-11",
		"month=2&year=2000":  "2000-02",
		"month=1&month=4":    "2026-04",
	}
	for raw, want := range cases {
		q, err := url.ParseQuery(raw)
		if err != nil {
			t.Fatal(err)
		}
		if got := monthWindow(q, today).Format("2006-01"); got != want {
			t.Errorf("%q: got %s, want %s", raw, got, want)
		}
	}
}
