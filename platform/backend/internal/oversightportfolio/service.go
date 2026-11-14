package oversightportfolio

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// Service builds the portfolio lens.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// passed is the query as the feed hands it to the page
// (apps.mobile_feed.views._page_params): each key's last value, keys the
// feed never passes and over-long values left out. ok is false for a list
// of ids (`ids`, `*_ids`), whose own check the lens does not port: such a
// query is handed on.
func passed(query url.Values) (url.Values, bool) {
	out := url.Values{}
	for key, values := range query {
		if !queryKey.MatchString(key) || slices.Contains(rules.QueryKeysNotPassed, key) || len(values) == 0 {
			continue
		}
		if key == "ids" || strings.HasSuffix(key, "_ids") {
			return nil, false
		}
		value := values[len(values)-1]
		if utf8.RuneCountInString(value) > rules.MaxQueryValue {
			continue
		}
		out.Set(key, value)
	}
	return out, true
}

// pyStrip is the view's (request.GET.get(key) or "").strip().
func pyStrip(query url.Values, key string) string { return strings.TrimSpace(query.Get(key)) }

var plainYear = regexp.MustCompile(`^[1-9][0-9]{3}$`)

// periodReadable is whether _period_filters reads the query without
// failing: the year is a number it can date (anything else is the existing
// page's error, handed on), and the month fields hold no digit Python's
// isdigit takes and int() then refuses.
func periodReadable(query url.Values, fy string) bool {
	if !plainYear.MatchString(fy) {
		return false
	}
	for _, key := range []string{"month", "from_month", "to_month"} {
		for _, r := range query.Get(key) {
			if r >= utf8.RuneSelf {
				return false
			}
		}
	}
	return true
}

// Build answers /team-planning-oversight/?view=portfolio for a reader the
// lens opens for. served is false for any other path or lens, for a reader
// whose page answers in another way (the Accountant and Human Resources
// fall back to the Team Plan), for a page opened from a planning follow-up,
// and for a year the existing page cannot read.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if myplan.FeedRefusesFormat(query) {
		return nil, true, pagegate.ErrNotAvailable
	}
	query, ok := passed(query)
	if !ok || strings.ToLower(pyStrip(query, "view")) != "portfolio" || query.Get("followup") != "" {
		return nil, false, nil
	}
	_, known := rules.Doors[p.ActiveRole]
	doors := doorsFor(p.ActiveRole)
	if !known {
		return nil, false, nil
	}
	if !doors.FeedOpens {
		return nil, true, pagegate.ErrNotAvailable
	}
	if !doors.Page || !doors.Portfolio {
		return nil, false, nil
	}
	now := s.now()
	fy := pyStrip(query, "fy")
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	if !periodReadable(query, fy) {
		return nil, false, nil
	}
	v, years, err := s.read(ctx, p, doors, fy, query, now)
	if err != nil {
		return nil, true, err
	}
	return page(v, years), true, nil
}

func (s *Service) read(ctx context.Context, p auth.Principal, doors Doors, fy string, query url.Values, now time.Time) (view, []string, error) {
	v := view{
		fy:          fy,
		programLead: pyStrip(query, "program_lead"),
		district:    pyStrip(query, "district"),
		planned:     pyStrip(query, "planned"),
		query:       query,
		country:     doors.CountryReader,
	}
	if !v.country {
		yes, err := isSuperuser(ctx, s.db, p.UserID)
		if err != nil {
			return v, nil, err
		}
		v.country = yes
	}
	v.lens = doors.LensTabsTeam
	if v.country {
		v.lens = doors.LensTabsCountry
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return v, nil, fmt.Errorf("oversightportfolio: resolving the scope: %w", err)
	}
	options := schooldirectory.FYOptions(now)
	operational, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
	horizon, err := schoolplanning.Horizon(ctx, s.db, fy, operational, options, now)
	if err != nil {
		return v, nil, err
	}
	rows, err := portfolioRows(ctx, s.db, scope, v.district, horizon)
	if err != nil {
		return v, nil, err
	}
	v.p = build(rows, v.programLead, v.planned)
	return v, options, nil
}

// isSuperuser is the account's is_superuser, which makes any reader a
// reader of the country (is_country_reader).
func isSuperuser(ctx context.Context, q schooldirectory.Querier, userID string) (bool, error) {
	var yes bool
	err := q.QueryRow(ctx, `SELECT is_superuser FROM "user" WHERE id = $1`, userID).Scan(&yes)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return false, fmt.Errorf("oversightportfolio: reading the account: %w", err)
	}
	return yes, nil
}
