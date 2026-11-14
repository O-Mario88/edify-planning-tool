package screens

import (
	"context"
	"net/url"
	"reflect"
	"testing"
)

func TestPlainQueryDropsBlankValuesAndKeepsTheRest(t *testing.T) {
	cases := []struct {
		name  string
		given map[string]string
		want  url.Values
	}{
		{"nil", nil, url.Values{}},
		{"empty", map[string]string{}, url.Values{}},
		{"one blank", map[string]string{"q": ""}, url.Values{}},
		{"blank beside a value", map[string]string{"q": "", "tab": "plan"},
			url.Values{"tab": {"plan"}}},
		{"spaces are a value", map[string]string{"q": " "}, url.Values{"q": {" "}}},
		{"every value kept", map[string]string{"fy": "2026", "page": "2"},
			url.Values{"fy": {"2026"}, "page": {"2"}}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := PlainQuery(c.given); !reflect.DeepEqual(got, c.want) {
				t.Fatalf("PlainQuery(%v) = %v, want %v", c.given, got, c.want)
			}
		})
	}
}

// The gateway's own reading of a page query is PlainQuery once the keys and
// values pass, so the parity tool's request to the existing application,
// which uses PlainQuery, sends what the gateway's pages see.
func TestPageQueryIsPlainQueryOnceTheQueryPasses(t *testing.T) {
	given := map[string]string{"q": "", "tab": "plan", "status": "", "page": "3"}
	got, err := pageQuery(context.Background(), given)
	if err != nil {
		t.Fatalf("pageQuery: %v", err)
	}
	if want := PlainQuery(given); !reflect.DeepEqual(got, want) {
		t.Fatalf("pageQuery = %v, PlainQuery = %v", got, want)
	}
}

// A page key is the feed's QUERY_KEY (apps.mobile_feed.views): a lower-case
// letter, then letters, digits or underscores, at most 40 in all. A table
// that pages on its own parameter names it by a record id
// ("portfolio_cmw9p7bwp00t19mekheun_page"), so a key with digits is a page's
// key; anything else is refused.
func TestPageQueryTakesTheKeysTheFeedPasses(t *testing.T) {
	cases := []struct {
		key  string
		pass bool
	}{
		{"page", true},
		{"portfolio_cmw9p7bwp00t19mekheun_page", true},
		{"g1_page", true},
		{"1page", false},
		{"Page", false},
		{"page-2", false},
		{"a2345678901234567890123456789012345678901", false},
	}
	for _, c := range cases {
		_, err := pageQuery(context.Background(), map[string]string{c.key: "2"})
		if (err == nil) != c.pass {
			t.Errorf("pageQuery(%q): err = %v, want pass %v", c.key, err, c.pass)
		}
	}
}
