package main

import (
	"net/url"
	"testing"
)

// The existing application is asked exactly what the gateway's pages see:
// a blank value (q=) is dropped, as the gateway drops it before any page.
func TestExistingPageURLDropsBlankParametersAsTheGatewayDoes(t *testing.T) {
	cases := []struct {
		name  string
		query map[string]string
		want  url.Values
	}{
		{"no query", nil, url.Values{"path": {"/staff-activity"}}},
		{"blank search", map[string]string{"q": ""}, url.Values{"path": {"/staff-activity"}}},
		{"blank beside a value", map[string]string{"q": "", "tab": "plan"},
			url.Values{"path": {"/staff-activity"}, "tab": {"plan"}}},
		{"a search", map[string]string{"q": "kam pala"},
			url.Values{"path": {"/staff-activity"}, "q": {"kam pala"}}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := &pageRun{existing: "http://localhost:8185", path: "/staff-activity"}
			got, err := url.Parse(r.existingPageURL(c.query))
			if err != nil {
				t.Fatalf("parse: %v", err)
			}
			if got.Path != "/api/mobile/v1/page" {
				t.Fatalf("path = %q", got.Path)
			}
			if values := got.Query(); values.Encode() != c.want.Encode() {
				t.Fatalf("query = %q, want %q", values.Encode(), c.want.Encode())
			}
		})
	}
}
