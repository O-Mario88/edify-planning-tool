package myperformance

import (
	"net/url"
	"testing"
)

func TestASubPagesTabWinsOverTheQuerysTab(t *testing.T) {
	query := url.Values{"tab": {"values"}, "fy": {"2026"}}
	got := withTab(query, "development")
	if got.Get("tab") != "development" || got.Get("fy") != "2026" {
		t.Fatalf("withTab: %v", got)
	}
	if query.Get("tab") != "values" {
		t.Fatalf("the request's own query changed: %v", query)
	}
	for path, want := range map[string]string{
		"/my-performance/development": "development",
		"/my-performance/values":      "values",
		// The documents link names a tab the page does not draw: the page
		// opens on its first.
		"/my-performance/documents": "conversations",
	} {
		if sub, ok := rules.SubPages[path]; !ok || sub.Tab != want {
			t.Errorf("%s: %+v", path, sub)
		}
	}
}
