package myplan

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// noon on 12 November 2026 in Kampala: FY 2027, Q1, week 2 of the month.
var noon = time.Date(2026, time.November, 12, 9, 0, 0, 0, time.UTC)

func values(pairs ...string) url.Values {
	v := url.Values{}
	for i := 0; i+1 < len(pairs); i += 2 {
		v.Set(pairs[i], pairs[i+1])
	}
	return v
}

func TestReadPeriodIsTheViewsReading(t *testing.T) {
	cases := []struct {
		name     string
		query    url.Values
		fy, kind string
		quarter  string
		month    int
		hasMonth bool
		asked    string
	}{
		{"as it opens", values(), "2027", "fy", "", 0, false, ""},
		{"a year as sent", values("fy", " 2026 "), " 2026 ", "fy", "", 0, false, ""},
		{"a month narrows to it", values("month", " 3 "), "2027", "month", "", 3, true, ""},
		{"a quarter opens at its first month", values("quarter", "Q2"), "2027", "month", "Q2", 1, true, ""},
		{"a quarter in lower case is no quarter", values("quarter", "q3"), "2027", "fy", "q3", 0, false, ""},
		{"all is no month", values("quarter", "Q3", "month", " ALL "), "2027", "month", "Q3", 4, true, ""},
		{"an explicit period wins, stripped", values("period", " week ", "month", "11"), "2027", "week", "", 11, true, "week"},
		{"a period that is none", values("period", "xyz"), "2027", "xyz", "", 0, false, "xyz"},
		{"a wider year clears quarter and month", values("fy", "2026", "fy_prev", "2027", "quarter", "Q2", "month", "1"), "2026", "fy", "", 0, false, ""},
		{"the same year keeps them", values("fy", "2027", "fy_prev", "2027", "quarter", "Q2", "month", "5"), "2027", "month", "Q2", 5, true, ""},
		{"a wider quarter clears the month", values("quarter", "Q3", "quarter_prev", "Q2", "month", "5"), "2027", "month", "Q3", 4, true, ""},
		{"a previous value alone clears nothing", values("fy_prev", "2026", "month", "2"), "2027", "month", "", 2, true, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p, ok := ReadPeriod(c.query, noon)
			if !ok {
				t.Fatal("read as unreadable")
			}
			if p.FY != c.fy || p.Kind != c.kind || p.Quarter != c.quarter || p.Month != c.month ||
				p.HasMonth != c.hasMonth || p.Asked != c.asked {
				t.Fatalf("got %+v", p)
			}
		})
	}
}

// The view fails on these (int(), calendar.monthrange, date()), so they are
// left to the existing application.
func TestReadPeriodRefusesWhatTheViewFailsOn(t *testing.T) {
	for _, q := range []url.Values{
		values("fy", "abc"), values("fy", "0"), values("fy", "99999"), values("fy", "20.5"),
		values("month", "13"), values("month", "0"), values("month", "1.5"),
		values("week", "0"), values("week", "6"), values("week", "abc"),
		values("month", "2", "week", "5"), // 29 February 2027 is no day
	} {
		if _, ok := ReadPeriod(q, noon); ok {
			t.Errorf("%v read as readable", q)
		}
	}
	// A leap February has a fifth week.
	if _, ok := ReadPeriod(values("fy", "2028", "month", "2", "week", "5"), noon); !ok {
		t.Error("the fifth week of February 2028 was refused")
	}
}

func TestTheDefaultYearIsKampalasDay(t *testing.T) {
	// 30 September 22:00 UTC is 1 October in Kampala: the next year.
	p, _ := ReadPeriod(values(), time.Date(2026, time.September, 30, 22, 0, 0, 0, time.UTC))
	if p.FY != "2027" {
		t.Fatalf("FY %s", p.FY)
	}
}

func TestQueryEditsAsDjangosQuerystring(t *testing.T) {
	request := NewQuery(values("quarter", "Q2", "month", "1", "fy", "2026", "q", "a b"))
	if got := request.With("period", "week").Without("month", "quarter").String(request); got != "?fy=2026&q=a+b&period=week" {
		t.Errorf("week tab %q", got)
	}
	if got := request.With("month", "3").String(request); got != "?fy=2026&month=3&q=a+b&quarter=Q2" {
		t.Errorf("set in place %q", got)
	}
	empty := NewQuery(url.Values{})
	if got := empty.String(empty); got != "" {
		t.Errorf("empty %q", got)
	}
	only := NewQuery(values("month", "1"))
	if got := only.Without("month").String(only); got != "?" {
		t.Errorf("emptied %q", got)
	}
}

func TestTheTabsAndFiltersFollowThePeriod(t *testing.T) {
	p, _ := ReadPeriod(values("quarter", "Q3"), noon)
	request := NewQuery(values("quarter", "Q3"))
	tabs := p.Tabs(request).GetLinkTabs().GetTabs()
	want := []struct {
		href   string
		active bool
	}{{"?period=week", false}, {"?quarter=Q3&period=month", true}, {"?quarter=Q3&period=quarter", false}, {"?period=fy", false}}
	for i, w := range want {
		if tabs[i].GetHref() != w.href || tabs[i].GetActive() != w.active {
			t.Errorf("tab %d: %s %v", i, tabs[i].GetHref(), tabs[i].GetActive())
		}
	}
	f := filters(p, []string{"2025", "2026", "2027", "2028"}, Choices{}, request).GetFilters()
	got := map[string]string{}
	for _, one := range f.GetFilters() {
		got[one.GetName()] = one.GetValue()
	}
	if got["quarter"] != "Q3" || got["month"] != "4" || got["fy"] != "2027" || got["status"] != "all" {
		t.Errorf("filters %v", got)
	}
	if f.GetHidden()["quarter_prev"] != "Q3" || f.GetHidden()["fy_prev"] != "2027" || f.GetHidden()["period"] != "" {
		t.Errorf("hidden %v", f.GetHidden())
	}
	// A year the menu does not offer reads as its first year.
	p, _ = ReadPeriod(values("fy", "1999"), noon)
	f = filters(p, []string{"2025", "2026"}, Choices{}, NewQuery(values("fy", "1999"))).GetFilters()
	if f.GetFilters()[0].GetValue() != "2025" || f.GetHidden()["fy_prev"] != "1999" {
		t.Errorf("unoffered year %v %v", f.GetFilters()[0].GetValue(), f.GetHidden())
	}
}

func TestTheEmptyPageNamesTheSlice(t *testing.T) {
	p, _ := ReadPeriod(values("period", "quarter"), noon)
	page := emptyPage(p, []string{"2027"}, Choices{}, NewQuery(values("period", "quarter")), Plan{}, Filters{}, 0)
	if page.GetHeader().GetActions()[0].GetHref() != "/my-plan/export-drawer?period=quarter" {
		t.Errorf("export %s", page.GetHeader().GetActions()[0].GetHref())
	}
	titles := []string{}
	for _, b := range page.GetBlocks() {
		if table := b.GetTable(); table != nil {
			titles = append(titles, table.GetTitle())
		}
	}
	if len(titles) != 4 || titles[0] != "School Visits Planned for This Quarter" || titles[3] != "Cluster Meetings Planned for This Quarter" {
		t.Errorf("titles %v", titles)
	}
	strip := page.GetBlocks()[2].GetStrip().GetMetrics()
	if strip[4].GetHelper() != "0 Core, 0 Client" || strip[7].GetValue() != "No data" {
		t.Errorf("strip %v", strip)
	}
}

func TestCommaIsIntcomma(t *testing.T) {
	for n, want := range map[int]string{0: "0", 999: "999", 1000: "1,000", 1234567: "1,234,567", -4500: "-4,500"} {
		if got := comma(n); got != want {
			t.Errorf("%d: %s", n, got)
		}
	}
}

// failingDB answers nothing: a Build that reaches the database fails.
type failingDB struct{ unusedQuerier }

func TestBuildPassesOrRefusesBeforeReading(t *testing.T) {
	s := NewService(failingDB{}, func() time.Time { return noon })
	staff := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: "Admin", Roles: []string{"Admin"}}}
	refused := auth.Principal{Account: auth.Account{UserID: "u2", ActiveRole: "BusinessTransformationOfficer"}}
	cases := []struct {
		name    string
		p       auth.Principal
		path    string
		query   url.Values
		served  bool
		refused bool
	}{
		{"another path", staff, "/my-plan/readiness", values(), false, false},
		{"the slash address", staff, "/my-plan/", values(), false, false},
		{"a role the page refuses", refused, Path, values(), true, true},
		{"a format no renderer answers", refused, Path, values("format", "csv"), true, true},
		{"an export period", staff, Path, values("period_type", "month"), false, false},
		{"a year the view fails on", staff, Path, values("fy", "abc"), false, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, served, err := s.Build(context.Background(), c.p, c.path, c.query)
			if served != c.served || errors.Is(err, pagegate.ErrNotAvailable) != c.refused {
				t.Fatalf("served %v, err %v", served, err)
			}
			if !c.refused && err != nil {
				t.Fatalf("err %v", err)
			}
		})
	}
}

func TestEveryRoleHasADoor(t *testing.T) {
	for _, role := range []string{"CCEO", "Program Lead", "Admin", "CountryDirector", "ImpactAssessment", "ProjectCoordinator"} {
		if !rules.Doors[role].Page {
			t.Errorf("%s cannot open My Plan", role)
		}
	}
	if rules.Doors["BusinessTransformationOfficer"].Page {
		t.Error("Business Transformation opens My Plan")
	}
}

// unusedQuerier fails every statement.
type unusedQuerier struct{}

func (unusedQuerier) Query(context.Context, string, ...any) (pgx.Rows, error) {
	return nil, errors.New("read the database")
}

func (unusedQuerier) QueryRow(context.Context, string, ...any) pgx.Row { return failedRow{} }

type failedRow struct{}

func (failedRow) Scan(...any) error { return errors.New("read the database") }
