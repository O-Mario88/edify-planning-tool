package pageheader

import (
	"net/url"
	"testing"
)

func TestKeyIsTheFeedsSlug(t *testing.T) {
	cases := map[string]string{
		"Export":                  "export",
		"Plan Field Event":        "plan_field_event",
		"+ Set Training Capacity": "set_training_capacity",
		"Download CSV":            "download_csv",
	}
	for label, want := range cases {
		if got := Key(label); got != want {
			t.Errorf("Key(%q) = %q, want %q", label, got, want)
		}
	}
}

func TestQueryHrefResolvesTheExportLinkAsTheFeedDoes(t *testing.T) {
	notPassed := []string{"csv", "download", "export", "format", "pdf", "xlsx"}
	cases := []struct {
		name  string
		query url.Values
		want  string
	}{
		{"no query", url.Values{}, "/planning?export=csv"},
		{"name order", url.Values{"tab": {"core"}, "search": {"a b"}}, "/planning?export=csv&search=a+b&tab=core"},
		{"blank and held back", url.Values{"district": {""}, "format": {"xlsx"}, "tab": {"core"}}, "/planning?export=csv&tab=core"},
		{"an export asked for is replaced", url.Values{"export": {"xlsx"}}, "/planning?export=csv"},
		{"escaped", url.Values{"search": {"Ann & Co/1"}}, "/planning?export=csv&search=Ann+%26+Co%2F1"},
	}
	for _, c := range cases {
		if got := QueryHref("/planning", c.query, notPassed, "export", "csv"); got != c.want {
			t.Errorf("%s: got %q, want %q", c.name, got, c.want)
		}
	}
}

func TestButtonsCarryTheFeedsShape(t *testing.T) {
	d := Drawer("Recent changes", "/planning/recent-changes", false)
	if d.Key != "recent_changes" || !d.Drawer || !d.Enabled || d.Download || d.Primary {
		t.Errorf("Drawer: %+v", d)
	}
	e := Download("Export", "/x?export=csv")
	if !e.Download || e.Drawer || !e.Enabled {
		t.Errorf("Download: %+v", e)
	}
	l := Link("Scoring", "/cluster-oversight/scoring")
	if l.Download || l.Drawer || !l.Enabled || l.Key != "scoring" {
		t.Errorf("Link: %+v", l)
	}
}

func TestHrefDropsBlankParametersAndAnEmptyQuery(t *testing.T) {
	if got := Href("/staff-activity/export", url.Values{"q": {""}}); got != "/staff-activity/export" {
		t.Errorf("got %q", got)
	}
	got := Href("/cluster-oversight/command", url.Values{"fy": {"2027"}, "area": {""}, "view": {"clusters"}, "format": {"csv"}})
	if got != "/cluster-oversight/command?format=csv&fy=2027&view=clusters" {
		t.Errorf("got %q", got)
	}
}
