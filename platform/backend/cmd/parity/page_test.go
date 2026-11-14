package main

import (
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/parity"
	"net/url"
	"strings"
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

func TestComparePagesSetsAsideOnlyAListedDifference(t *testing.T) {
	list, err := parity.Load([]byte(`[{"id":"probe","tool":"page","where":"/p","questions":["(as it opens)"],
		"fields":[".header.title"],"existing":"Old","go":"New","defect":"d","decision":"o","test":"cmd/parity.TestComparePagesSetsAsideOnlyAListedDifference"}]`))
	if err != nil {
		t.Fatal(err)
	}
	saved := intended
	intended = list
	t.Cleanup(func() { intended = saved })
	page := func(title, redirect string) *screensv1.GetPageResponse {
		return &screensv1.GetPageResponse{Header: &screensv1.PageHeader{Title: title}, Redirect: redirect}
	}
	answer := parity.Answer{Tool: parity.ToolPage, Where: "/p", Question: "(as it opens)"}

	text, accepted := comparePages(answer, page("New", ""), nil, page("Old", ""), nil)
	if text != "" || len(accepted) != 1 || accepted[0].Entry != "probe" {
		t.Fatalf("the listed difference: %q %v", text, accepted)
	}
	text, accepted = comparePages(answer, page("New", "/x"), nil, page("Old", ""), nil)
	if !strings.Contains(text, ".redirect") || strings.Contains(text, ".header.title") || len(accepted) != 1 {
		t.Fatalf("an unlisted difference beside it still fails: %q %v", text, accepted)
	}
	other := parity.Answer{Tool: parity.ToolPage, Where: "/p", Question: "tab=x"}
	if text, _ := comparePages(other, page("New", ""), nil, page("Old", ""), nil); !strings.Contains(text, ".header.title") {
		t.Fatalf("the same difference on another question still fails: %q", text)
	}
}
