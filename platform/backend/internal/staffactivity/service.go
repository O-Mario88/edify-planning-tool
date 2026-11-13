package staffactivity

import (
	"context"
	"errors"
	"net/url"
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/staff-activity"

// dashboardPath is the dashboard a Programme Lead reads the log on
// (dashboard_embed.to_dashboard).
const dashboardPath = "/dashboard"

// Service builds the Staff Activity Log.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

func isAlpha(r rune) bool { return unicode.IsLetter(r) }

// Build answers path for p with the page's query. served is false for a
// path this package does not answer, and for a reader it cannot answer
// exactly.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.ActiveRole == rules.Dashboard.Role {
		return &screensv1.GetPageResponse{Redirect: toDashboard(query)}, true, nil
	}
	if p.ActiveRole != rules.Roles.CountryDirector && p.ActiveRole != rules.Roles.Admin {
		// viewer_scope is None: the page reads nobody's log.
		return nil, true, pagegate.ErrForbidden
	}
	l, gs, err := s.log(ctx, p, query)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	out := page(l, gs)
	out.Header.Actions = append([]*screensv1.PageAction{exportAction(query)}, out.Header.Actions...)
	return out, true, nil
}

// exportAction is the header's Export: the log as a file, for the page's own
// query without its pages (_query), none the feed holds back.
func exportAction(query url.Values) *screensv1.PageAction {
	own := url.Values{}
	for key, values := range query {
		if key != "page" && key != "staff_page" && !slices.Contains(rules.Query.NotPassed, key) {
			own[key] = values
		}
	}
	return pageheader.Download("Export", pageheader.Href(exportPath, own))
}

// exportPath is the log's export (staff_activity_export).
const exportPath = "/staff-activity/export"

var queryKey = regexp.MustCompile(rules.Query.KeyPattern)

// toDashboard is dashboard_embed.to_dashboard: the dashboard section that
// holds the log, the page's own query carried in one parameter and its year
// as the dashboard's.
func toDashboard(query url.Values) string {
	own := url.Values{}
	for key, values := range query {
		if queryKey.MatchString(key) && !slices.Contains(rules.Query.NotPassed, key) {
			for _, v := range values {
				if len([]rune(v)) <= rules.Query.MaxValue {
					own.Add(key, v)
				}
			}
		}
	}
	target := dashboardPath
	if encoded := own.Encode(); encoded != "" {
		params := url.Values{rules.Dashboard.Param: {encoded}}
		if year := strings.TrimSpace(own.Get("fy")); year != "" {
			params.Set("fy", year)
		}
		target += "?" + params.Encode()
	}
	return target + "#" + rules.Dashboard.Anchor
}

func (s *Service) log(ctx context.Context, p auth.Principal, query url.Values) (*theLog, []*group, error) {
	now := s.now()
	today := dateOf(now)
	f := filters{
		period:      query.Get("period"),
		on:          query.Get("on"),
		role:        strings.TrimSpace(query.Get("role")),
		programLead: strings.TrimSpace(query.Get("pl")),
		status:      strings.TrimSpace(query.Get("status")),
		q:           runes(strings.TrimSpace(query.Get("q")), 80),
	}
	chosen := choosePeriod(f.period, f.on, today)
	country, err := readerCountry(ctx, s.db, p.UserID)
	if err != nil {
		return nil, nil, err
	}
	ids, err := countryRoster(ctx, s.db, p.UserID, country)
	if err != nil {
		return nil, nil, err
	}
	everyone, err := buildPeople(ctx, s.db, ids, chosen, now, today)
	if err != nil {
		return nil, nil, err
	}
	leadOf, names, err := programLeads(ctx, s.db)
	if err != nil {
		return nil, nil, err
	}
	for _, x := range everyone {
		if id, ok := leadOf[x.id]; ok {
			x.lead = &lead{id: id, name: names[id]}
		}
	}
	l := &theLog{
		period: chosen, everyone: everyone, total: len(everyone), filters: f, today: today,
		canFollowUp: p.ActiveRole == rules.Roles.CountryDirector,
	}
	l.people = narrow(everyone, f)
	for _, role := range rules.InternalRoles {
		if slices.ContainsFunc(everyone, func(x *person) bool { return x.role == role }) {
			name, _ := label(rules.RoleFilterLabels, role)
			l.roleOptions = append(l.roleOptions, [2]string{role, name})
		}
	}
	if l.leadOptions, err = leadOptions(everyone); err != nil {
		return nil, nil, err
	}
	if l.canFollowUp {
		if l.followUpCount, err = followUpCount(ctx, s.db, p.UserID); err != nil {
			return nil, nil, err
		}
	}
	gs := groups(l.people)
	if len(gs) > rules.PageSize {
		// More groups than one page: the pager is not drawn here.
		return nil, nil, errPassOn
	}
	if l.insights, err = teamInsights(ctx, s.db, l.people, chosen, today); err != nil {
		return nil, nil, err
	}
	return l, gs, nil
}

// leadOptions is activity_log's program_lead_options: every Programme Lead
// a person is filed under and every Programme Lead listed, by name. Two of
// one name are ordered by a set the page does not fix: passed on.
func leadOptions(everyone []*person) ([][2]string, error) {
	seen := map[[2]string]bool{}
	out := [][2]string{}
	add := func(o [2]string) {
		if !seen[o] {
			seen[o] = true
			out = append(out, o)
		}
	}
	for _, x := range everyone {
		if x.lead != nil {
			add([2]string{x.lead.id, x.lead.name})
		}
	}
	for _, x := range everyone {
		if x.role == rules.Roles.ProgramLead {
			add([2]string{x.id, x.name})
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i][1] < out[j][1] })
	for i := 1; i < len(out); i++ {
		if out[i][1] == out[i-1][1] {
			return nil, errPassOn
		}
	}
	return out, nil
}
