package planningoversight

import (
	"context"
	"net/url"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	teamKey    = "team"
	countryKey = "country"
)

// Service answers the two oversight pages' doors.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database the later pieces read.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// pageFor is the key of the page at path, or "" for any other path (the
// parts under the pages are the existing application's).
func pageFor(path string) string {
	for key, page := range rules.Pages {
		if page.FeedOpensPage && page.Path == path {
			return key
		}
	}
	return ""
}

// Build answers /team-planning-oversight/ and /country-planning-oversight/
// for p. A reader the page refuses gets pagegate.ErrNotAvailable, as the
// feed answers 404 before the view runs; a ?format= the feed has no renderer
// for is refused for everyone. A reader the page opens for is handed to the
// existing application (served=false), except the Team Plan a Programme
// Lead's team has nothing planned on (teamplan.go).
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	key := pageFor(path)
	if key == "" {
		return nil, false, nil
	}
	if myplan.FeedRefusesFormat(query) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if !refused(p.ActiveRole, key) {
		if key == teamKey {
			if resp, served, err := s.buildTeamPlan(ctx, p, query); served || err != nil {
				return resp, served, err
			}
			if pagegate.DjangoAbsent(ctx) {
				return s.buildCountryOversight(ctx, p, query)
			}
			return nil, false, nil
		}
		if key == countryKey && pagegate.DjangoAbsent(ctx) {
			return s.buildCountryOversight(ctx, p, query)
		}
		return nil, false, nil
	}
	return nil, true, pagegate.ErrNotAvailable
}

// refused is whether the feed answers "not available" to a reader in role
// before the page's view runs. A role's answer only narrows for the person
// (an acting appointment's withheld pages, a partner member's), so a role
// the gate refuses refuses everyone in it, and a role it opens for is asked
// again by the existing application. A role unknown to the rules has no
// page permission at all.
func refused(role, key string) bool {
	door, ok := rules.Doors[role][key]
	return !ok || !door.Open
}
