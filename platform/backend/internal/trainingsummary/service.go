package trainingsummary

import (
	"context"
	"net/url"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is Team Oversight, the page whose Training Summary lens this
// package answers.
const Path = "/team-planning-oversight/"

// ErrNotAvailable is the page refused to the reader.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds the Training Summary.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// passed is the query as the feed hands it to the page
// (apps.mobile_feed.views._page_params).
func passed(query url.Values) url.Values {
	out := url.Values{}
	for key, values := range query {
		if !queryKey.MatchString(key) || in(rules.QueryKeysNotPassed, key) || len(values) == 0 {
			continue
		}
		value := values[len(values)-1]
		if utf8.RuneCountInString(value) > rules.MaxQueryValue {
			continue
		}
		out.Set(key, value)
	}
	return out
}

// lowered is the view's (request.GET.get(key) or "").strip().lower().
func lowered(query url.Values, key string) string {
	return strings.ToLower(strings.TrimSpace(query.Get(key)))
}

// Build answers the Training Summary's Summary tab. served is false for any
// other path, lens or tab, for a reader whose page answers in another way,
// and for a page opened from a planning follow-up.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if myplan.FeedRefusesFormat(query) {
		return nil, true, ErrNotAvailable
	}
	query = passed(query)
	if lowered(query, "view") != "trainings" || query.Get("followup") != "" {
		return nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !doors.FeedOpens {
		return nil, true, ErrNotAvailable
	}
	if !doors.Page || !doors.Trainings || !(p.ActiveRole == rules.ProgramLeadRole || doors.ReadsCountry) {
		return nil, false, nil
	}
	if tab := lowered(query, "tab"); tab == "staff" || tab == "schools" {
		return nil, false, nil
	}
	now := s.now()
	years := schooldirectory.FYOptions(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if !slices.Contains(years, fy) {
		fy = schooldirectory.OperationalFY(now)
	}
	summary, err := forReader(ctx, s.db, p.ActiveRole, p.UserID, p.StaffProfileID, fy,
		strings.TrimSpace(query.Get("program_lead")), doors, now)
	if err != nil {
		return nil, true, err
	}
	lens := doors.LensTabsTeam
	country := doors.CountryReader
	if !country {
		if country, err = isSuperuser(ctx, s.db, p.UserID); err != nil {
			return nil, true, err
		}
	}
	if country {
		lens = doors.LensTabsCountry
	}
	return page(summary, years, lens), true, nil
}
