package planningpage

import (
	"net/url"
	"testing"
)

func TestHeaderOffersPlanFieldEventOnlyToARoleThatMayAddOne(t *testing.T) {
	cases := []struct {
		name  string
		doors Doors
		query url.Values
		want  []string
		href  string
	}{
		{"may add", Doors{FieldEvent: true}, url.Values{}, []string{"export", "plan_field_event", "recent_changes"}, "/planning?export=csv"},
		{"may not", Doors{}, url.Values{"tab": {"core"}, "format": {"xlsx"}}, []string{"export", "recent_changes"}, "/planning?export=csv&tab=core"},
	}
	for _, c := range cases {
		h := header(c.doors, c.query)
		keys := []string{}
		for _, a := range h.GetActions() {
			keys = append(keys, a.GetKey())
		}
		if len(keys) != len(c.want) {
			t.Fatalf("%s: %v, want %v", c.name, keys, c.want)
		}
		for i := range keys {
			if keys[i] != c.want[i] {
				t.Errorf("%s: %v, want %v", c.name, keys, c.want)
			}
		}
		if got := h.GetActions()[0]; got.GetHref() != c.href || !got.GetDownload() {
			t.Errorf("%s: export %v", c.name, got)
		}
	}
}
