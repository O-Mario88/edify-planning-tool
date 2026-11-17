package targetdistribution

import (
	"context"
	"errors"
	"math/big"
	"net/url"
	"testing"
)

// An asked year is read as asked only when the view would read it so (four
// ASCII digits within the bounds); any other ask, a query key the view does
// not read, a search beyond ASCII and a reader with one view are handed on
// before the database is read.
func TestTheAskedYearAndQueryAreReadAsTheViewReadsThem(t *testing.T) {
	s := &Service{}
	for raw, want := range map[string]bool{"2027": true, "2000": true, "2100": true,
		"1999": false, "2101": false, "27": false, "02027": false, "２０２７": false, "20x7": false} {
		fy, err := s.year(context.Background(), raw)
		if got := err == nil; got != want || (want && fy != raw) {
			t.Errorf("year %q: %q, %v; want accepted %v", raw, fy, err, want)
		}
		if !want && !errors.Is(err, errPassOn) {
			t.Errorf("year %q: %v, want handed on", raw, err)
		}
	}
	role := door{Import: true, Distributor: true,
		Tabs: [][2]string{{"Priority Setting", "/strategic-priorities"}, {"Target Distribution", Path}}}
	for _, q := range []url.Values{{"import": {"b1"}}, {"other": {"x"}}, {"q": {"écoles"}}} {
		if _, err := s.build(context.Background(), role, q); !errors.Is(err, errPassOn) {
			t.Errorf("%v: %v, want handed on", q, err)
		}
	}
	single := role
	single.Tabs = role.Tabs[:1]
	if _, err := s.build(context.Background(), single, url.Values{}); !errors.Is(err, errPassOn) {
		t.Errorf("one view: %v, want handed on", err)
	}
}

// The rail carries the year as it was asked.
func TestTheRailCarriesTheAskedYear(t *testing.T) {
	tabs := [][2]string{{"Priority Setting", "/strategic-priorities"}, {"Target Distribution", Path}}
	got := rail(tabs, "2028").GetLinkTabs().GetTabs()
	if got[0].Href != "/strategic-priorities?fy=2028" || got[1].Href != Path+"?fy=2028" || !got[1].Active || got[0].Active {
		t.Errorf("rail: %v", got)
	}
	if bare := rail(tabs, "").GetLinkTabs().GetTabs(); bare[0].Href != "/strategic-priorities" {
		t.Errorf("no year asked: %v", bare)
	}
}

// The figures print as the template prints them: floatformat:"-2"|intcomma,
// truncatechars, Python's str.title() and round(x, 1).
func TestTheMasterFiguresPrintAsTheTemplatePrintsThem(t *testing.T) {
	for in, want := range map[string]string{"1000.00": "1,000", "62105": "62,105", "12.50": "12.50", "1234567.5": "1,234,567.50",
		"-3026": "-3,026", "0": "0"} {
		r, _ := new(big.Rat).SetString(in)
		if got := figure(r); got != want {
			t.Errorf("figure(%s) = %q, want %q", in, got, want)
		}
	}
	if got := truncate("Active social media and internal marketing — 2 posts/week minimum", 54); got != "Active social media and internal marketing — 2 posts/…" {
		t.Errorf("truncate: %q", got)
	}
	if got := pyTitle("balance_open"); got != "Balance_Open" {
		t.Errorf("pyTitle: %q", got)
	}
	if got := share(big.NewRat(3026, 1), big.NewRat(62105, 1)); got != 4.9 {
		t.Errorf("share: %v", got)
	}
	if got := cents(big.NewRat(125, 1000)); got.Cmp(big.NewRat(12, 100)) != 0 {
		t.Errorf("cents(0.125) = %s, want 0.12 (half to even)", got.FloatString(2))
	}
}
