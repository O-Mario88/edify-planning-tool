package tablepager

import (
	"net/url"
	"reflect"
	"testing"
)

func labels(t *testing.T, p Page) []string {
	t.Helper()
	if p.Pager == nil {
		return nil
	}
	out := []string{}
	for _, page := range p.Pager.Pages {
		label := page.Label
		if page.Current {
			label = "[" + label + "]"
		}
		out = append(out, label)
	}
	return out
}

func TestOnePageNeedsNoPager(t *testing.T) {
	p := Paginate(50, 50, url.Values{}, "rows_page")
	if p.Pager != nil || p.Start != 0 || p.End != 50 {
		t.Fatalf("got %+v, want the whole fifty rows and no pager", p)
	}
}

func TestTheRequestedPageIsReadAsPythonReadsIt(t *testing.T) {
	for _, tc := range []struct {
		raw        string
		start, end int
	}{
		{"", 0, 50},
		{"2", 50, 100},
		{" 2 ", 50, 100},
		{"+2", 50, 100},
		{"0", 0, 50},
		{"-4", 0, 50},
		{"x", 0, 50},
		{"9", 100, 120},
		{"1_0", 100, 120},
	} {
		p := Paginate(120, 50, url.Values{"rows_page": {tc.raw}}, "rows_page")
		if p.Start != tc.start || p.End != tc.end {
			t.Errorf("page %q: rows [%d, %d), want [%d, %d)", tc.raw, p.Start, p.End, tc.start, tc.end)
		}
	}
}

func TestThePagerCarriesTheOtherKeysInKeyOrder(t *testing.T) {
	query := url.Values{"rows_page": {"2"}, "work": {"schools"}, "partner": {"p 1"}, "status": {""}}
	p := Paginate(120, 50, query, "rows_page")
	if p.Pager.Summary != "Showing 51–100 of 120" {
		t.Errorf("summary %q", p.Pager.Summary)
	}
	want := []string{"Prev", "1", "[2]", "3", "Next"}
	if got := labels(t, p); !reflect.DeepEqual(got, want) {
		t.Errorf("pages %v, want %v", got, want)
	}
	if got := p.Pager.Pages[0].Href; got != "?partner=p+1&work=schools&rows_page=1" {
		t.Errorf("Prev links to %q", got)
	}
	if p.Pager.Pages[2].Href != "" {
		t.Errorf("the current page links to %q", p.Pager.Pages[2].Href)
	}
}

func TestTheWindowShowsTheEndsAndOnePageEitherSide(t *testing.T) {
	for _, tc := range []struct {
		page string
		want []string
	}{
		{"1", []string{"[1]", "2", "…", "10", "Next"}},
		{"5", []string{"Prev", "1", "…", "4", "[5]", "6", "…", "10", "Next"}},
		{"10", []string{"Prev", "1", "…", "9", "[10]"}},
	} {
		p := Paginate(500, 50, url.Values{"rows_page": {tc.page}}, "rows_page")
		if got := labels(t, p); !reflect.DeepEqual(got, tc.want) {
			t.Errorf("page %s: %v, want %v", tc.page, got, tc.want)
		}
	}
}
