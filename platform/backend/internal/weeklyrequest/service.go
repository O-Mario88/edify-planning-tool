package weeklyrequest

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/fund-requests/weekly"

// kampala is the page's local day (Uganda keeps no summer time).
var kampala = time.FixedZone("EAT", 3*60*60)

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// errPassOn is a request the existing page answers.
var errPassOn = errors.New("weeklyrequest: handed on")

// The query keys the week reads; any other is handed on.
var known = map[string]bool{"fy": true, "quarter": true, "month": true, "week": true, "district": true,
	"staff": true, "status": true, "request_type": true, "period_tab": true, "budget_scope": true}

// ask is the request as the page reads it.
type ask struct {
	fy, quarter, monthName, week, district, staff, status, requestType string
	everyone                                                           bool
	query                                                              url.Values
}

func day(t time.Time) time.Time { return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC) }

func monday(d time.Time) time.Time { return d.AddDate(0, 0, -((int(d.Weekday()) + 6) % 7)) }

// pageFY is _page_fy: the year asked, else the year of the named week's
// Monday, else the running year.
func pageFY(query url.Values, today time.Time) (string, error) {
	if fy := strings.TrimSpace(query.Get("fy")); fy != "" {
		return fy, nil
	}
	if w := strings.TrimSpace(query.Get("week")); w != "" {
		d, err := time.Parse(time.DateOnly, w)
		if err != nil {
			return "", errPassOn
		}
		return schooldirectory.OperationalFY(monday(d)), nil
	}
	return schooldirectory.OperationalFY(today), nil
}

func readAsk(query url.Values, today time.Time) (ask, error) {
	for key, values := range query {
		if !known[key] || len(values) != 1 {
			return ask{}, errPassOn
		}
	}
	if tab := strings.ToLower(strings.TrimSpace(query.Get("period_tab"))); tab != "" && tab != "week" {
		// The Month, Quarter and Annual horizons, and a tab the page does not
		// know (which it reads as the week: handed on rather than guessed).
		return ask{}, errPassOn
	}
	fy, err := pageFY(query, today)
	if err != nil {
		return ask{}, err
	}
	if n, err := strconv.Atoi(fy); err != nil || n < 1000 || n > 9999 {
		return ask{}, errPassOn
	}
	a := ask{
		fy:          fy,
		quarter:     strings.TrimSpace(query.Get("quarter")),
		monthName:   strings.TrimSpace(query.Get("month")),
		week:        strings.TrimSpace(query.Get("week")),
		district:    strings.TrimSpace(query.Get("district")),
		staff:       strings.TrimSpace(query.Get("staff")),
		status:      strings.TrimSpace(query.Get("status")),
		requestType: strings.TrimSpace(query.Get("request_type")),
		query:       query,
	}
	if a.quarter != "" && !in([]string{"Q1", "Q2", "Q3", "Q4"}, a.quarter) {
		return ask{}, errPassOn
	}
	if a.staff == rules.EveryoneStaff {
		a.staff, a.everyone = "", true
	}
	return a, nil
}

// Build answers /fund-requests/weekly; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	r, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !r.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.InActingAppointment || (len(r.Strip) > 0 && string(r.Strip) != "null") {
		return nil, false, nil
	}
	now := s.now()
	a, err := readAsk(query, now.In(kampala))
	if err != nil {
		return nil, false, nil
	}
	out, err := s.build(ctx, p, r, a, now)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return out, true, nil
}

// scope is _scoped_base_querysets for one year: whose requests, cost lines
// and activities the page reads, and the staff it is pinned to.
type scope struct {
	fy         string
	country    bool
	owners     []string // the requests' and lines' responsible users; nil is anyone
	actors     []string // the activities' responsible staff ids; nil is anyone
	supervised []string // supervised_user_ids
	staff      string   // the staff filter after pinning
	// countryID and countryIDs keep a country reader to the request's
	// country (docs/migration/80, §19); nil is every country.
	countryID  any
	countryIDs []string
}

func (s *Service) scopeFor(ctx context.Context, p auth.Principal, sc schooldirectory.Scope, a ask, fy string) (scope, error) {
	out := scope{fy: fy, country: sc.CountryScope}
	if sc.CountryScope && p.Country != nil {
		// The Admin and the regional roles read the country they work in, so
		// money is never summed across countries.
		out.countryID, out.countryIDs = p.Country.ID, []string{p.Country.ID}
	}
	if !sc.CountryScope {
		me := p.UserID
		if me == "" {
			me = "__none__"
		}
		out.owners = []string{me}
		if len(sc.SupervisedStaffIDs) > 0 {
			users, err := strs(ctx, s.db, `SELECT user_id FROM staff_profile WHERE id = ANY($1) AND deleted_at IS NULL AND user_id IS NOT NULL`, sc.SupervisedStaffIDs)
			if err != nil {
				return out, err
			}
			out.supervised = users
			out.owners = append(out.owners, users...)
		}
		identities := []string{}
		for _, id := range []string{p.UserID, sc.StaffID} {
			if id != "" {
				identities = append(identities, id)
			}
		}
		if len(identities) == 0 {
			identities = []string{"__none__"}
		}
		out.actors = append(append(identities, out.supervised...), sc.SupervisedStaffIDs...)
	} else {
		users, err := strs(ctx, s.db, `SELECT DISTINCT responsible_user FROM weekly_fund_request
WHERE fy = $1 AND responsible_user IS NOT NULL AND responsible_user <> $2`, fy, p.UserID)
		if err != nil {
			return out, err
		}
		out.supervised = users
	}
	out.staff = a.staff
	if out.staff == "" && len(out.supervised) > 0 && !(a.everyone && sc.CountryScope) {
		out.staff = p.UserID
	}
	return out, nil
}

func strs(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([]string, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("weeklyrequest: reading ids: %w", err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var v string
		if err := rows.Scan(&v); err != nil {
			return nil, fmt.Errorf("weeklyrequest: reading ids: %w", err)
		}
		out = append(out, v)
	}
	return out, rows.Err()
}
