package iapages

import (
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

func TestAnnexPeriodNarrowsTheYearAndNamesIt(t *testing.T) {
	now := time.Date(2026, time.November, 26, 9, 0, 0, 0, time.UTC)
	for _, c := range []struct {
		query, start, end, label string
	}{
		{"", "", "", annexAllPeriods},
		{"fy=2026", "2025-10-01", "2026-09-30", "FY2026: 2025-10-01 to 2026-09-30"},
		{"fy=2026&period_start=2026-01-15&period_end=2027-02-01", "2026-01-15", "2026-09-30", "FY2026: 2026-01-15 to 2026-09-30"},
		{"fy=2026&period_start=2024-01-01", "2025-10-01", "2026-09-30", "FY2026: 2025-10-01 to 2026-09-30"},
		{"period_start=2026-03-01", "2026-03-01", "", "2026-03-01 to today"},
		{"period_end=2026-03-01", "", "2026-03-01", "the start to 2026-03-01"},
	} {
		query, _ := url.ParseQuery(c.query)
		start, end, label, err := annexPeriod(query, now)
		if err != nil {
			t.Fatalf("%q: %v", c.query, err)
		}
		if day(start) != c.start || day(end) != c.end || label != c.label {
			t.Errorf("%q = %s, %s, %q; want %s, %s, %q", c.query, day(start), day(end), label, c.start, c.end, c.label)
		}
	}
}

func TestAnnexPeriodRefusesInTheViewsWords(t *testing.T) {
	now := time.Date(2026, time.November, 26, 9, 0, 0, 0, time.UTC)
	for raw, want := range map[string]string{
		"fy=1999":                 "Choose a financial year from the list.",
		"period_start=26/11/2026": "Period dates must be dates (YYYY-MM-DD).",
		"period_start=2026-05-01&period_end=2026-04-01":         "The period must start before it ends.",
		"fy=2026&period_start=2026-09-30&period_end=2026-01-01": "The period must start before it ends.",
	} {
		query, _ := url.ParseQuery(raw)
		_, _, _, err := annexPeriod(query, now)
		var bad workbook.BadRequest
		if !errors.As(err, &bad) || string(bad) != want {
			t.Errorf("%q: %v, want %q", raw, err, want)
		}
	}
}

func TestCSVCellWritesValuesAsPythonWrites(t *testing.T) {
	for _, c := range []struct {
		value any
		want  string
	}{
		{nil, ""}, {true, "Yes"}, {false, "No"}, {7, "7"}, {7.0, "7.0"}, {6.25, "6.25"}, {-0.5, "-0.5"},
		{"=SUM(A1)", "'=SUM(A1)"}, {" -1", "' -1"}, {"School", "School"},
	} {
		if got := CSVCell(c.value); got != c.want {
			t.Errorf("CSVCell(%#v) = %q, want %q", c.value, got, c.want)
		}
	}
}

func day(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.Format(time.DateOnly)
}
