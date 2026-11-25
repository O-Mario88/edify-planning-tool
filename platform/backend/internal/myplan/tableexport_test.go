package myplan

import (
	"net/url"
	"testing"
	"time"
)

func TestEveryExportedTableHasACellForEachHeading(t *testing.T) {
	for key, headers := range rules.TableExport.Headers {
		if got := len(exportColumns[key]); got != len(headers) {
			t.Errorf("%s: %d cells for %d headings %v", key, got, len(headers), headers)
		}
	}
	for _, key := range rules.TableExport.AllSheets {
		if _, ok := exportColumns[key]; !ok {
			t.Errorf("%s: no columns", key)
		}
	}
}

func TestExportBoundsReadTheDrawersPeriod(t *testing.T) {
	day := func(s string) time.Time { d, _ := time.Parse(time.DateOnly, s); return d }
	cases := []struct {
		query      string
		start, end string
	}{
		{"", "2026-10-01", "2027-09-30"},
		{"period_type=month_range&from_month=11&to_month=1", "2026-11-01", "2027-01-31"},
		{"period_type=month_range&from_month=3&to_month=10", "2026-10-01", "2027-03-31"},
		{"from_month=2", "2026-10-01", "2027-09-30"},
		{"period_type=month_range&from_month=2", "2027-02-01", "2027-02-28"},
		{"period_type=custom_dates&start_date=2027-03-09&end_date=2027-01-02&from_month=10&to_month=12", "2027-01-02", "2027-03-09"},
		{"start_date=2027-01-02&end_date=bad", "2026-10-01", "2027-09-30"},
		{"period_type=fy&from_month=11&to_month=12", "2026-10-01", "2027-09-30"},
	}
	for _, c := range cases {
		q, _ := url.ParseQuery(c.query)
		s, e := exportBounds(q, 2027)
		if !s.Equal(day(c.start)) || !e.Equal(day(c.end)) {
			t.Errorf("%q: %s – %s, want %s – %s", c.query, s.Format(time.DateOnly), e.Format(time.DateOnly), c.start, c.end)
		}
	}
}

func TestExportFormatAndKind(t *testing.T) {
	for query, want := range map[string]string{
		"export=csv": "csv", "export=EXCEL": "xlsx", "format=xlsx": "xlsx", "from_month=1": "xlsx",
		"": "", "format=csv": "", "export=pdf": "",
	} {
		q, _ := url.ParseQuery(query)
		if got := exportFormat(q); got != want {
			t.Errorf("exportFormat(%q) = %q, want %q", query, got, want)
		}
	}
	q, _ := url.ParseQuery("activity_type=school_visit")
	if readKind(q) != "all" || !keepsStatus("all", "completed") || keepsStatus("scheduled", "completed") {
		t.Error("an unknown kind is the whole plan; scheduled leaves completed work out")
	}
	if !keepsKind("online", "cluster_training", true) || keepsKind("online", "cluster_training", false) {
		t.Error("the online kind keeps only online group trainings")
	}
}
