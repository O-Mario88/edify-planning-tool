package staffactivity

import (
	"net/url"
	"testing"
)

func TestExportCarriesThePagesQueryWithoutItsPages(t *testing.T) {
	cases := []struct {
		query url.Values
		want  string
	}{
		{url.Values{}, "/staff-activity/export"},
		{url.Values{"period": {"week"}, "page": {"2"}, "staff_page": {"3"}, "q": {"Ann B"}}, "/staff-activity/export?period=week&q=Ann+B"},
		{url.Values{"format": {"xlsx"}, "role": {"CCEO"}}, "/staff-activity/export?role=CCEO"},
	}
	for _, c := range cases {
		a := exportAction(c.query)
		if a.GetHref() != c.want || !a.GetDownload() || a.GetKey() != "export" {
			t.Errorf("%v: %v, want %q", c.query, a, c.want)
		}
	}
}
