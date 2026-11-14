package iapages

import (
	"net/url"
	"slices"
	"strconv"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func TestAnalyticsWindowTakesOnlyAnOfferedWindow(t *testing.T) {
	for raw, want := range map[string]int{"": 90, "30": 30, " 365 ": 365, "090": 90, "7": 90, "+30": 90, "-30": 90, "abc": 90, "180": 180} {
		if got := analyticsWindow(raw); got != want {
			t.Errorf("analyticsWindow(%q) = %d, want %d", raw, got, want)
		}
	}
}

func TestAnalyticsRoundsAsPython(t *testing.T) {
	if pct(1, 8) != 12 || pct(3, 8) != 38 || pct(0, 0) != 0 || pct(2, 3) != 67 {
		t.Errorf("pct: %d %d %d %d", pct(1, 8), pct(3, 8), pct(0, 0), pct(2, 3))
	}
	end := time.Date(2026, 11, 1, 12, 0, 0, 0, time.UTC)
	start := end.Add(-30 * time.Hour)
	if h := hours(&start, end); h == nil || floatText(*h) != "30.0" {
		t.Errorf("hours: %v", h)
	}
	if hours(nil, end) != nil {
		t.Error("no submission time reads no hours")
	}
	if floatText(round1((30.0+3.0)/2)) != "16.5" {
		t.Error("average")
	}
}

func blockKinds(r *screensv1.GetPageResponse) []string {
	out := []string{}
	for _, b := range r.Blocks {
		switch k := b.Kind.(type) {
		case *screensv1.PageBlock_Section:
			out = append(out, "section:"+k.Section)
		case *screensv1.PageBlock_Panel:
			out = append(out, "panel:"+k.Panel.Title)
		case *screensv1.PageBlock_Table:
			out = append(out, "table:"+strconv.Itoa(len(k.Table.Rows)))
		case *screensv1.PageBlock_Strip:
			out = append(out, "strip")
		case *screensv1.PageBlock_Filters:
			out = append(out, "filters")
		}
	}
	return out
}

func TestAnalyticsPageWithNothingReadsEachSectionsEmptyMessage(t *testing.T) {
	r := analyticsPage(analyticsData{window: 90}, url.Values{})
	want := []string{"filters", "strip", "panel:Why work is returned", "panel:Return rate by month",
		"panel:Submitters, highest return rate first", "panel:Partners, highest return rate first", "panel:Verifiers"}
	if got := blockKinds(r); !slices.Equal(got, want) {
		t.Fatalf("blocks %v, want %v", got, want)
	}
	if items := r.Blocks[6].GetPanel().Items; len(items) != 2 || items[0].GetText() != verifiersExplained {
		t.Errorf("verifiers panel: %v", items)
	}
	if a := r.Header.Actions[0]; a.Key != "export_decisions" || a.Href != "/ia/analytics/export?window=90" || !a.Download {
		t.Errorf("export: %v", a)
	}
	if m := r.Blocks[1].GetStrip().Metrics[2]; m.Value != "0%" || m.Note != "of decisions" {
		t.Errorf("rate: %v", m)
	}
}

func TestAnalyticsPageWithDecisionsReadsSectionsAndTables(t *testing.T) {
	avg, acc := 16.5, 100
	d := analyticsData{window: 30, decisions: 3, returned: 2, rate: 67,
		reasons:    []reasonRow{{"Missing attendance", 1, 50}, {"Unspecified", 1, 50}},
		trend:      []trendRow{{"2026-08", 1, 0, 0}, {"2026-11", 1, 1, 100}},
		submitters: []rateRow{{"Sarah N.", 3, 2, 67}},
		verifiers:  []verifierRow{{name: "Grace Alimo", verified: 2, avgHours: &avg, within24: 50, sampled: 1, accuracy: &acc}},
	}
	r := analyticsPage(d, url.Values{})
	want := []string{"filters", "strip", "section:Why work is returned", "table:2", "section:Return rate by month", "panel:", "table:2",
		"section:Submitters, highest return rate first", "table:1", "panel:Partners, highest return rate first",
		"section:Verifiers", "panel:", "table:1"}
	if got := blockKinds(r); !slices.Equal(got, want) {
		t.Fatalf("blocks %v, want %v", got, want)
	}
	if bars := r.Blocks[5].GetPanel().Items; len(bars) != 4 || bars[3].GetText() != "100%" {
		t.Errorf("trend bars: %v", bars)
	}
	row := r.Blocks[12].GetTable().Rows[0].Cells
	if row[2].Text != "16.5" || row[3].Text != "50%" || row[5].Text != "100%" {
		t.Errorf("verifier row: %v", row)
	}
	if c := r.Blocks[3].GetTable().Columns; c[0].Numeric || !c[1].Numeric {
		t.Errorf("columns: %v", c)
	}
}

func TestAnalyticsTablesPageAtTheTablePageSize(t *testing.T) {
	rows := make([]rateRow, rules.TablePageSize+1)
	for i := range rows {
		rows[i] = rateRow{name: strconv.Itoa(i), submitted: 1}
	}
	r := analyticsPage(analyticsData{window: 90, submitters: rows}, url.Values{"submitters_page": {"2"}})
	got := blockKinds(r)
	if got[5] != "table:1" || got[6] != "panel:" {
		t.Errorf("second page: %v", got)
	}
}

func TestFilesizeIsDjangosFilesizeformat(t *testing.T) {
	n := func(v int64) *int64 { return &v }
	for _, c := range []struct {
		in   *int64
		want string
	}{{nil, "0 bytes"}, {n(1), "1 byte"}, {n(500), "500 bytes"}, {n(1024), "1.0 KB"}, {n(20480), "20.0 KB"}, {n(1572864), "1.5 MB"}} {
		if got := filesize(c.in); got != c.want {
			t.Errorf("filesize = %q, want %q", got, c.want)
		}
	}
}

func TestAReportsPeriodIsItsDatesFilledFromItsYear(t *testing.T) {
	jan := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	for want, x := range map[string]report{
		"1 Jan 2026 – 30 Sep 2026": {fy: "2026", start: &jan},
		"1 Oct 2026 – 30 Sep 2027": {fy: "2027"},
		"All recorded enrolments":  {start: &jan},
	} {
		if got := periodLabel(x); got != want {
			t.Errorf("periodLabel(%+v) = %q, want %q", x, got, want)
		}
	}
}

func TestARegisteredTileDrawsAFigureHelperWithItsTone(t *testing.T) {
	if m := registryMetric("X", 1, "1 overdue", "warning", ""); m.Helper != "1 overdue" || m.Tone != "warning" || m.Note != "" {
		t.Errorf("figure helper: %v", m)
	}
	if m := registryMetric("X", 0, "from released reports", "info", "/x"); m.Note != "from released reports" || m.Tone != "" || m.Href != "/x" {
		t.Errorf("words helper: %v", m)
	}
}
