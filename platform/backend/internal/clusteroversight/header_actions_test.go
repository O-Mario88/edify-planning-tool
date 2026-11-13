package clusteroversight

import (
	"net/url"
	"testing"
)

func TestHeaderDownloadCarriesTheAreaAndViewTheViewReads(t *testing.T) {
	command := Section{Key: "command", Label: "Command Center"}
	cases := []struct {
		name    string
		section Section
		doors   Doors
		query   url.Values
		want    []string
	}{
		{"opens", command, Doors{Export: true, Scoring: true}, url.Values{},
			[]string{"/cluster-oversight/command?format=csv&fy=2027&view=" + rules.ImpactViews[0], "/cluster-oversight/scoring"}},
		{"an area and a view", command, Doors{Export: true}, url.Values{"area": {" " + rules.SSAInterventions[0][0] + " "}, "view": {rules.ImpactViews[len(rules.ImpactViews)-1]}},
			[]string{"/cluster-oversight/command?area=" + url.QueryEscape(rules.SSAInterventions[0][0]) + "&format=csv&fy=2027&view=" + rules.ImpactViews[len(rules.ImpactViews)-1]}},
		{"not an area, not a view", command, Doors{Export: true}, url.Values{"area": {"nonsense"}, "view": {"nonsense"}},
			[]string{"/cluster-oversight/command?format=csv&fy=2027&view=" + rules.ImpactViews[0]}},
		{"no export", command, Doors{Scoring: true}, url.Values{}, []string{"/cluster-oversight/scoring"}},
		{"reports downloads nothing", Section{Key: "reports"}, Doors{Export: true}, url.Values{}, nil},
	}
	for _, c := range cases {
		got := []string{}
		for _, a := range header(c.section, c.doors, "2027", c.query).GetActions() {
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
