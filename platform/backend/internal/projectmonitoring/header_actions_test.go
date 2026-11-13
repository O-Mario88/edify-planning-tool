package projectmonitoring

import "testing"

func TestHeaderActionsFollowTheDoorsAndKeepThePagesFilters(t *testing.T) {
	open := &projectRow{p: project{ID: "p1"}}
	cases := []struct {
		name string
		v    view
		want []string
	}{
		{"nothing for a reader without the doors", view{fy: "2027", open: open}, nil},
		{"consolidated alone without an open project", view{fy: "2027", doors: Doors{Consolidated: true, Export: true}},
			[]string{"Consolidated tables /country-planning-oversight/table/projects?fy=2027 false"}},
		{"exports keep the stage and filters in name order", view{fy: "2027", stage: "planned", picks: map[string]string{"partner": "A & B"},
			doors: Doors{Export: true}, open: open},
			[]string{"Export all projects /projects/export?fy=2027&partner=A+%26+B&stage=planned true",
				"Export this project /projects/p1/export?fy=2027&partner=A+%26+B&stage=planned true"}},
		{"a blank stage is left out", view{fy: "2026", doors: Doors{Consolidated: true, Export: true}, open: open},
			[]string{"Consolidated tables /country-planning-oversight/table/projects?fy=2026 false",
				"Export all projects /projects/export?fy=2026 true",
				"Export this project /projects/p1/export?fy=2026 true"}},
	}
	for _, c := range cases {
		got := headerActions(c.v)
		if len(got) != len(c.want) {
			t.Fatalf("%s: %d actions, want %d", c.name, len(got), len(c.want))
		}
		for i, a := range got {
			line := a.Label + " " + a.Href + " " + map[bool]string{true: "true", false: "false"}[a.Download]
			if line != c.want[i] || !a.Enabled || a.Primary || a.Drawer {
				t.Errorf("%s: got %q %+v, want %q", c.name, line, a, c.want[i])
			}
		}
	}
}
