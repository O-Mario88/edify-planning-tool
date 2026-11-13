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
		{"a Programme Lead's Team Plan is the existing application's", "Program Lead", team, nil, false, false},
		{"the Country Director's Country Oversight is the existing application's", "CountryDirector", country, nil, false, false},
		{"a lens the reader may open is the existing application's", "ImpactAssessment", team, url.Values{"view": {"monitor"}}, false, false},
		{"a format the feed cannot render is refused even to an opener", "Admin", team, url.Values{"format": {"xml"}}, true, true},
		{"a part under the page is not this package's", "Admin", country + "rows", nil, false, false},
		{"the page without its slash is not this package's", "CCEO", "/team-planning-oversight", nil, false, false},
		{"another page is not this package's", "CCEO", "/my-plan", nil, false, false},
	}
	s := NewService(nil, time.Now)
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			page, served, err := s.Build(context.Background(), principal(tc.role), tc.path, tc.query)
			if served != tc.wantServed {
				t.Fatalf("served = %v, want %v", served, tc.wantServed)
			}
			if refused := errors.Is(err, pagegate.ErrNotAvailable); refused != tc.wantRefuse {
				t.Fatalf("err = %v, want refused %v", err, tc.wantRefuse)
			}
			if page != nil {
				t.Fatalf("page = %v, want none in piece 1", page)
			}
		})
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
