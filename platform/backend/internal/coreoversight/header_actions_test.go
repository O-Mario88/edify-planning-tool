package coreoversight

import (
	"net/url"
	"testing"
)

func TestHeaderDownloadsFollowTheFiltersAndThePlanTab(t *testing.T) {
	cases := []struct {
		name  string
		doors Doors
		query url.Values
		want  []string
	}{
		{"opens", Doors{Export: true}, url.Values{}, []string{"/core-schools-oversight/?format=csv"}},
		{"filters, a page and a held-back key", Doors{Export: true},
			url.Values{"q": {"a b"}, "page": {"2"}, "export": {"xlsx"}, "district": {""}, "tab": {"groups"}},
			[]string{"/core-schools-oversight/?format=csv&q=a+b"}},
		{"a tab of planned work", Doors{Export: true}, url.Values{"tab": {rules.PlanTabs[0]}, "q": {"a"}},
			[]string{"/core-schools-oversight/?format=csv&q=a", "/core-schools-oversight/?format=xlsx&q=a&tab=" + rules.PlanTabs[0]}},
		{"no export", Doors{}, url.Values{"tab": {rules.PlanTabs[0]}}, nil},
	}
	for _, c := range cases {
		v := newView(c.query, "2027", []string{"2027"})
		got := []string{}
		for _, a := range header(v, c.doors).GetActions() {
			if !a.GetDownload() {
				t.Errorf("%s: %v is not a download", c.name, a)
			}
			got = append(got, a.GetHref())
		}
		if len(got) != len(c.want) {
			t.Fatalf("%s: %v, want %v", c.name, got, c.want)
		}
		for i := range got {
			if got[i] != c.want[i] {
				t.Errorf("%s: %q, want %q", c.name, got[i], c.want[i])
			}
		}
	}
}
