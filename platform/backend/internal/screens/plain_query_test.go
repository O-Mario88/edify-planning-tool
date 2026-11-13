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
