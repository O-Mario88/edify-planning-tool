package planningoversight

import (
	"context"
	"errors"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	teamKey    = "team"
	countryKey = "country"
)

// CountryPath is the Country Planning Oversight page.
const CountryPath = "/country-planning-oversight/"

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
	if table, ok := tableFor(path); ok {
		return s.buildCountryTable(ctx, p, table, query)
	}
	key := pageFor(path)
	if key == "" {
		return nil, false, nil
	}
	if myplan.FeedRefusesFormat(query) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if !refused(p.ActiveRole, key) {
		if key == teamKey {
			// A team lens Go does not draw is handed on. It is never
			// answered with the country summary: that is another page,
			// with country-wide figures, under the team's address.
			return s.buildTeamPlan(ctx, p, query)
		}
		// The planning-coverage dashboard, the page's default lens, is
		// Go's (planningmonitor.CountryOversightPage, as coverage_page draws it).
		if key == countryKey && asksForCoverage(query) {
			return s.buildCountryCoverage(ctx, p, query)
		}
		// Every other lens is handed on (the summary Go used to draw in a
		// design of its own is gone: docs/migration/189).
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

// countryLenses are the views country_planning_oversight_view sends
// somewhere other than coverage_page.
var countryLenses = map[string]bool{"clusters": true, "execution": true, "portfolio": true, "monitor": true,
	"plan": true, "planning": true}

// activityPlanParams are _ACTIVITY_PLAN_PARAMS: a link carrying the Country
// Plan lens's own filters lands on that lens.
var activityPlanParams = []string{"lead", "risk", "activity_type", "executor_type", "context", "status", "district_id", "partner_id"}

// asksForCoverage is whether country_planning_oversight_view answers the
// query with coverage_page.
func asksForCoverage(query url.Values) bool {
	view := ""
	if values := query["view"]; len(values) > 0 {
		// QueryDict.get answers a repeated key's last value.
		view = strings.ToLower(strings.TrimSpace(values[len(values)-1]))
	}
	if view != "" {
		return !countryLenses[view]
	}
	for key := range query {
		if slices.Contains(activityPlanParams, key) || groupPage.MatchString(key) {
			return false
		}
	}
	return true
}

var groupPage = regexp.MustCompile(`^g\d+_page`)

// buildCountryCoverage is coverage_page for p.
func (s *Service) buildCountryCoverage(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	q := map[string]string{}
	for key, values := range query {
		if len(values) > 0 {
			q[key] = values[len(values)-1]
		}
	}
	blocks, err := planningmonitor.CountryOversightPage(ctx, s.db, p, q, s.now())
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetPageResponse{Header: &screensv1.PageHeader{Title: "Country Planning Oversight"}, Blocks: blocks,
		WebPath: CountryPath}, true, nil
}

// tableFor is the key of the consolidated table at path
// (country-planning-oversight/table/<str:key>), if path is one.
func tableFor(path string) (string, bool) {
	key, ok := strings.CutPrefix(path, CountryPath+"table/")
	if !ok || key == "" || strings.Contains(key, "/") {
		return "", false
	}
	return key, true
}

// buildCountryTable is table_view for p: behind the page's own gate, the
// tables Go draws, and every other handed on.
func (s *Service) buildCountryTable(ctx context.Context, p auth.Principal, key string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if myplan.FeedRefusesFormat(query) || refused(p.ActiveRole, countryKey) {
		return nil, true, pagegate.ErrNotAvailable
	}
	page, served, err := planningmonitor.CountryOversightTable(ctx, s.db, p, key, query, s.now())
	if errors.Is(err, planningmonitor.ErrNoSuchTable) {
		return nil, false, nil
	}
	return page, served, err
}
