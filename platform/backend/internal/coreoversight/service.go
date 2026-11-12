package coreoversight

import (
	"context"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers, the one address of it the app's
// feed opens (apps.mobile_feed.views.NATIVE_PAGES names
// core_schools_oversight).
const Path = "/core-schools-oversight/"

// under is every other address of the page: the same without its slash,
// and anything below it, which resolve to no page.
const under = "/core-schools-oversight"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds Core School Oversight.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// passed is the query as the feed hands it to the page: without the keys
// that answer with a file (apps.mobile_feed.views.NOT_PASSED).
func passed(query url.Values) url.Values {
	out := url.Values{}
	for key, values := range query {
		if !in(rules.NotPassedQueryKeys, key) {
			out[key] = values
		}
	}
	return out
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer, and for the two tabs of planned work
// (Core School Visits and Core School Trainings), which are My Plan's own
// tables and stay the existing application's until My Plan is Go's.
//
// Every other address under the page is not found there for every reader,
// and so it is here.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		if (path == under || strings.HasPrefix(path, Path)) && rules.FeedOpensPage {
			return nil, true, ErrNotAvailable
		}
		return nil, false, nil
	}
	if !rules.FeedOpensPage {
		return nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page {
		return nil, true, ErrNotAvailable
	}
	query = passed(query)
	tab := choice(query, "tab", keysOf(rules.Tabs), "schools")
	if in(rules.PlanTabs, tab) {
		return nil, false, nil
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	years := yearOptions(now)
	fy := choice(query, "fy", years, schooldirectory.OperationalFY(now))
	found, err := read(ctx, s.db, scope, fy, tab == "recommendations")
	if err != nil {
		return nil, true, err
	}
	return page(found, reader{doors: doors}, fy, years, schooldirectory.OperationalFY(now), query), true, nil
}

// yearOptions is the view's sorted(fy_options(), reverse=True).
func yearOptions(now time.Time) []string {
	years := slices.Clone(schooldirectory.FYOptions(now))
	slices.Sort(years)
	slices.Reverse(years)
	return years
}
