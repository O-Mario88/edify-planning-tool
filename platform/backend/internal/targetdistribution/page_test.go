package targetdistribution

import (
	"context"
	"errors"
	"net/url"
	"testing"
)

// An asked year is read as asked only when the view would read it so (four
// ASCII digits within the bounds); any other ask, and any query besides the
// year, is handed on before the database is read.
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
	tabs := [][2]string{{"Priority Setting", "/strategic-priorities"}, {"Target Distribution", Path}}
	for _, q := range []url.Values{{"tab": {"field_cascade"}}, {"q": {"visits"}}, {"page": {"2"}}} {
		if _, err := s.build(context.Background(), true, tabs, q); !errors.Is(err, errPassOn) {
			t.Errorf("%v: %v, want handed on", q, err)
		}
	}
	if _, err := s.build(context.Background(), true, tabs[:1], url.Values{}); !errors.Is(err, errPassOn) {
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
