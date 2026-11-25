package planningoversight

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

func principal(role string) auth.Principal {
	var p auth.Principal
	p.ActiveRole = role
	return p
}

func TestBuildAnswersTheDoorsAndHandsOpenReadersOn(t *testing.T) {
	const team, country = "/team-planning-oversight/", "/country-planning-oversight/"
	cases := []struct {
		name       string
		role, path string
		query      url.Values
		wantServed bool
		wantRefuse bool
	}{
		{"a CCEO is refused Planning Oversight", "CCEO", team, nil, true, true},
		{"a CCEO is refused Country Oversight", "CCEO", country, nil, true, true},
		{"a Programme Lead is refused Country Oversight", "Program Lead", country, nil, true, true},
		{"the Project Coordinator is refused either", "ProjectCoordinator", team, nil, true, true},
		{"a refusal holds for every lens", "CCEO", team, url.Values{"view": {"trainings"}}, true, true},
		{"a role unknown to the rules is refused", "", team, nil, true, true},
		{"a Programme Lead's other lens is the existing application's", "Program Lead", team, url.Values{"view": {"targets"}}, false, false},
		{"an acting Programme Lead's Team Plan is the existing application's", "Program Lead", team, nil, false, false},
		{"the Country Director's Country Plan lens is the existing application's", "CountryDirector", country, url.Values{"view": {"plan"}}, false, false},
		{"a Country Plan filter keeps the existing application's lens", "CountryDirector", country, url.Values{"risk": {"high"}}, false, false},
		{"a lens the reader may open is the existing application's", "ImpactAssessment", team, url.Values{"view": {"monitor"}}, false, false},
		{"a format the feed cannot render is refused even to an opener", "Admin", team, url.Values{"format": {"xml"}}, true, true},
		{"a part under the page is not this package's", "Admin", country + "rows", nil, false, false},
		{"a CCEO is refused Country Oversight's tables", "CCEO", country + "table/not-planned", nil, true, true},
		{"a table Go does not draw yet is the existing application's", "CountryDirector", country + "table/visits", nil, false, false},
		{"a table the page has none of is the existing application's", "CountryDirector", country + "table/bogus", nil, false, false},
		{"a path under a table is not a table", "CountryDirector", country + "table/not-planned/x", nil, false, false},
		{"a table refuses a format the feed cannot render", "CountryDirector", country + "table/not-planned", url.Values{"format": {"xml"}}, true, true},
		{"the page without its slash is not this package's", "CCEO", "/team-planning-oversight", nil, false, false},
		{"another page is not this package's", "CCEO", "/my-plan", nil, false, false},
	}
	s := NewService(nil, time.Now)
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := principal(tc.role)
			if tc.name == "an acting Programme Lead's Team Plan is the existing application's" {
				p.InActingAppointment = true
			}
			page, served, err := s.Build(context.Background(), p, tc.path, tc.query)
			if served != tc.wantServed {
				t.Fatalf("served = %v, want %v", served, tc.wantServed)
			}
			if refused := errors.Is(err, pagegate.ErrNotAvailable); refused != tc.wantRefuse {
				t.Fatalf("err = %v, want refused %v", err, tc.wantRefuse)
			}
			if page != nil {
				t.Fatalf("page = %v, want none before the database is read", page)
			}
		})
	}
}

// country_planning_oversight_view: coverage_page answers every view but the
// lenses it sends elsewhere, and a link carrying the Country Plan's own
// filters (or a group's page) lands on the plan.
func TestAsksForCoverage(t *testing.T) {
	cases := map[string]bool{"": true, "view=coverage": true, "view=Bogus": true, "fy=2027&period=quarter": true,
		"view=plan": false, "view=PLANNING": false, "view=monitor": false, "view=execution": false, "view=clusters": false,
		"view=portfolio": false, "lead=x": false, "g2_page=3": false, "view=coverage&risk=high": true, "view=plan&view=coverage": true}
	for raw, want := range cases {
		q, _ := url.ParseQuery(raw)
		if got := asksForCoverage(q); got != want {
			t.Errorf("%q: %v", raw, got)
		}
	}
}

func TestEveryRoleThePageOpensForIsLetInByTheView(t *testing.T) {
	// The feed asks can_open_url first; a reader it lets through whom the
	// view's decorator then refuses would see the view's own refusal and an
	// audit row, which Go must not answer. The exported gates agree today.
	for role, doors := range rules.Doors {
		for key, door := range doors {
			if door.Open && !door.Page {
				t.Errorf("%s on %s: the feed opens a page the view refuses", role, key)
			}
		}
	}
}
