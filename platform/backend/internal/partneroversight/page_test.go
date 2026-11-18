package partneroversight

import (
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// 2026-11-13 09:00 UTC: FY 2027, ISO week 2026-W46.
var at = time.Date(2026, time.November, 13, 9, 0, 0, 0, time.UTC)

func TestReadPeriodIsThePeriodFilters(t *testing.T) {
	cases := []struct {
		query string
		ok    bool
		want  period
	}{
		{"", true, period{fy: "2027", kind: "fy", week: "2026-W46", month: 11, quarter: "Q1"}},
		{"period=WEEK", true, period{fy: "2027", kind: "week", week: "2026-W46", month: 11, quarter: "Q1"}},
		{"period=year", true, period{fy: "2027", kind: "fy", week: "2026-W46", month: 11, quarter: "Q1"}},
		{"month=3", true, period{fy: "2027", kind: "month", week: "2026-W46", month: 3, quarter: "Q1"}},
		{"month=13", true, period{fy: "2027", kind: "fy", week: "2026-W46", month: 11, quarter: "Q1"}},
		{"quarter=q3", true, period{fy: "2027", kind: "quarter", week: "2026-W46", month: 11, quarter: "Q3"}},
		{"month=2&quarter=Q4", true, period{fy: "2027", kind: "month", week: "2026-W46", month: 2, quarter: "Q4"}},
		// Another year reads from its first day: 1 October before it.
		{"fy=2025", true, period{fy: "2025", kind: "fy", week: "2024-W40", month: 10, quarter: "Q1"}},
		{"fy=%202026%20", true, period{fy: "2026", kind: "fy", week: "2025-W40", month: 10, quarter: "Q1"}},
		{"fy=1999", true, period{fy: "1999", kind: "fy", week: "1998-W40", month: 10, quarter: "Q1"}},
		{"week=2026-W02&period=week", true, period{fy: "2027", kind: "week", week: "2026-W02", month: 11, quarter: "Q1"}},
		// Readings Go does not copy go to the existing application.
		{"fy=abc", false, period{}},
		{"fy=0999", false, period{}},
		{"week=2026-W2", false, period{}},
		{"week=2026-W53", false, period{}},
		{"week=nonsense", false, period{}},
	}
	for _, c := range cases {
		q, _ := url.ParseQuery(c.query)
		got, ok := readPeriod(q, at)
		if ok != c.ok || got != c.want {
			t.Errorf("%q: got %+v %v, want %+v %v", c.query, got, ok, c.want, c.ok)
		}
	}
}

func TestTodayIsKampalasDay(t *testing.T) {
	// 22:30 UTC on 30 September is 1 October in Kampala: the page's year is
	// still FY 2026 (get_operational_fy reads UTC) while today, Kampala's day,
	// is in FY 2027, so the page reads FY 2026 from its first day.
	late := time.Date(2026, time.September, 30, 22, 30, 0, 0, time.UTC)
	got, ok := readPeriod(url.Values{}, late)
	if !ok || got.fy != "2026" || got.month != 10 || got.quarter != "Q1" || got.week != "2025-W40" {
		t.Fatalf("got %+v %v", got, ok)
	}
}

func TestQuarterOf(t *testing.T) {
	for month, want := range map[time.Month]string{
		time.October: "Q1", time.December: "Q1", time.January: "Q2", time.March: "Q2",
		time.April: "Q3", time.June: "Q3", time.July: "Q4", time.September: "Q4",
	} {
		if got := quarterOf(time.Date(2026, month, 1, 0, 0, 0, 0, time.UTC)); got != want {
			t.Errorf("%s: got %s want %s", month, got, want)
		}
	}
}

func TestWorkTab(t *testing.T) {
	for requested, want := range map[string]string{
		"": "schools", "schools": "schools", "visits": "visits", "trainings": "trainings",
		"clusters": "clusters", "core": "schools", "bogus": "schools",
	} {
		if got := workTab(requested); got != want {
			t.Errorf("%q: got %q want %q", requested, got, want)
		}
	}
}

func TestPlainQueries(t *testing.T) {
	for query, want := range map[string]bool{
		"":                      true,
		"status=scheduled":      true,
		"period_type=fy":        false,
		"from_month=1":          false,
		"start_date=2026-01-01": false,
		"engagement=abc":        false,
		"record=1":              false,
		"engagement_page=2":     false,
		"month=%D9%A3":          false, // an Arabic-Indic 3 is a digit to Python
	} {
		q, _ := url.ParseQuery(query)
		if got := plain(q); got != want {
			t.Errorf("%q: got %v want %v", query, got, want)
		}
	}
}

func TestDrawnReaders(t *testing.T) {
	role := func(name string) Role { return rules.Roles[name] }
	for _, c := range []struct {
		p    auth.Principal
		want bool
	}{
		{auth.Principal{Account: auth.Account{ActiveRole: "CCEO"}}, true},
		{auth.Principal{Account: auth.Account{ActiveRole: "Program Lead"}}, true},
		{auth.Principal{Account: auth.Account{ActiveRole: "CountryDirector"}}, true},
		{auth.Principal{Account: auth.Account{ActiveRole: "CountryDirector", InActingAppointment: true}}, false},
		{auth.Principal{Account: auth.Account{ActiveRole: "RegionalProgramLead"}}, true},
		{auth.Principal{Account: auth.Account{ActiveRole: "CCEO", InActingAppointment: true}}, false},
		{auth.Principal{Account: auth.Account{ActiveRole: "CCEO", Acting: &auth.ActingAppointment{}}}, false},
	} {
		if got := drawn(c.p, role(c.p.ActiveRole)); got != c.want {
			t.Errorf("%+v: got %v want %v", c.p.Account, got, c.want)
		}
	}
}

func TestStatusWords(t *testing.T) {
	for key, want := range map[string]string{
		"awaiting_schedule": "Awaiting Schedule", "in_progress": "In Progress", "returned": "Returned",
	} {
		if got := title_(key); got != want {
			t.Errorf("%s: got %q want %q", key, got, want)
		}
	}
}

func lead() workspace {
	return workspace{
		role:   rules.Roles["Program Lead"],
		period: period{fy: "2027", kind: "fy", week: "2026-W46", month: 11, quarter: "Q1"},
		member: "sp2", status: "returned", work: "visits", programLead: "x",
		members:    []member{{"sp1", "Program Lead 2"}, {"sp2", "Daniel O."}},
		withTarget: true, fyOptions: []string{"2025", "2026", "2027", "2028"},
	}
}

func TestPageForALeadWithNoPartnerWork(t *testing.T) {
	got := page(lead())
	if len(got.GetHeader().GetActions()) != 0 || got.GetWebPath() != Path {
		t.Fatalf("header %+v", got.GetHeader())
	}
	blocks := got.GetBlocks()
	if len(blocks) != 7 {
		t.Fatalf("got %d blocks", len(blocks))
	}
	f := blocks[0].GetFilters()
	if f.GetHidden()["member"] != "sp2" || f.GetHidden()["work"] != "visits" || f.GetHidden()["program_lead"] != "x" {
		t.Errorf("hidden %v", f.GetHidden())
	}
	values := map[string]string{}
	for _, filter := range f.GetFilters() {
		values[filter.GetName()] = filter.GetValue()
	}
	// The period select shows the period in use (the lead's is the FY), not
	// the existing feed's stuck "week" (intended.json go-fix-period-select-partner).
	want := map[string]string{"period": "fy", "fy": "2027", "month": "11", "quarter": "Q1", "status": "returned"}
	for k, v := range want {
		if values[k] != v {
			t.Errorf("filter %s: got %q want %q", k, values[k], v)
		}
	}
	tabs := blocks[1].GetLinkTabs().GetTabs()
	if len(tabs) != 3 || tabs[2].GetLabel() != "Daniel O. 0" || !tabs[2].GetActive() || tabs[0].GetActive() ||
		tabs[2].GetHref() != "?program_lead=x&partner=&member=sp2&work=visits&period=fy&fy=2027&month=11&quarter=Q1&week=2026-W46" {
		t.Errorf("tabs %v", tabs)
	}
	if note := blocks[2].GetStrip().GetMetrics()[0].GetNote(); note == "" {
		t.Error("the first tile lacks the Partner target")
	}
	if blocks[3].GetEmpty() == "" || blocks[4].GetPanel().GetTitle() != registerTitle {
		t.Error("empty state or register title missing")
	}
	metrics := blocks[5].GetStrip().GetMetrics()
	if len(metrics) != 4 || metrics[0].GetNote() != "FY2027 · meetings, orientations and follow-ups" || metrics[0].GetHelper() != "" {
		t.Errorf("register tiles %v", metrics)
	}
	if blocks[6].GetTable().GetEmptyMessage() != recordedEmpty {
		t.Errorf("register table %v", blocks[6].GetTable())
	}
}

func TestPageForAnOfficerAndForAReaderWhoAddsPartners(t *testing.T) {
	w := lead()
	w.role, w.members, w.withTarget, w.member, w.status, w.fyOptions = rules.Roles["CCEO"], nil, false, "all", "xyz", []string{"2026"}
	blocks := page(w).GetBlocks()
	if len(blocks) != 4 || len(blocks[1].GetLinkTabs().GetTabs()) != 1 || blocks[2].GetStrip().GetMetrics()[0].GetNote() != "" {
		t.Fatalf("officer page %v", blocks)
	}
	for _, f := range blocks[0].GetFilters().GetFilters() {
		if f.GetName() == "status" && f.GetValue() != "" || f.GetName() == "fy" && f.GetValue() != "2026" {
			t.Errorf("filter %s reads %q", f.GetName(), f.GetValue())
		}
	}
	w.role = rules.Roles["CountryDirector"]
	got := page(w)
	if a := got.GetHeader().GetActions(); len(a) != 1 || a[0].GetHref() != "/partners/create" || !a[0].GetDrawer() {
		t.Errorf("actions %v", a)
	}
	w.role = rules.Roles["ImpactAssessment"]
	if table := page(w).GetBlocks()[6].GetTable(); table.GetEmptyMessage() != readerEmpty || len(page(w).GetBlocks()[5].GetStrip().GetMetrics()) != 3 {
		t.Errorf("reader register %v", table)
	}
}

// The existing page's period select marks no option, so its feed always reads
// "week" whatever period is shown. Go marks the period in use (owner,
// 2026-11-13: "Can you fix those from the go side"; intended.json
// go-fix-period-select-partner).
func TestThePeriodSelectShowsThePeriodInUse(t *testing.T) {
	for _, kind := range []string{"week", "month", "quarter", "fy"} {
		block := filters(workspace{period: period{fy: "2027", kind: kind, quarter: "Q1", month: 11}})
		if got := block.GetFilters().GetFilters()[0]; got.GetName() != "period" || got.GetValue() != kind {
			t.Fatalf("period %s: the select shows %q", kind, got.GetValue())
		}
	}
}
