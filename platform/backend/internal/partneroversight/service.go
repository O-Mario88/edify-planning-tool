package partneroversight

import (
	"context"
	"errors"
	"net/url"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/partner-oversight/"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds Partner Monitoring.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
	// target is the Planning Monitor's Partner visit target for the reader
	// (internal/planningmonitor, which reads this package, so it is given
	// rather than called): target, Core part, beyond staff capacity, held
	// by a Partner, and whether the monitor has anybody on it.
	target func(context.Context, auth.Principal, string, time.Time) (int, int, int, int, bool, error)
}

// ErrTargetNotDrawn is the Planning Monitor's answer for a reader whose
// monitor this application does not draw yet: the page is handed on.
var ErrTargetNotDrawn = errors.New("partneroversight: the reader's Planning Monitor is not drawn")

// WithTarget gives the service the Planning Monitor's Partner target.
func (s *Service) WithTarget(read func(context.Context, auth.Principal, string, time.Time) (int, int, int, int, bool, error)) *Service {
	s.target = read
	return s
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// customPeriodKeys are the Export drawer's period fields
// (_period_filters: period_type, the month pair, the dates): a link that
// carries one reads a custom period, which this piece does not draw.
var customPeriodKeys = []string{"period_type", "from_month", "to_month", "start_date", "end_date"}

// workspace is what the page draws for a reader with no partner work.
type workspace struct {
	role        Role
	period      period
	programLead string
	member      string
	status      string
	work        string
	members     []member
	withTarget  bool
	fyOptions   []string
	// partnerAsked and memberAsked are the Partner and team member the
	// link asks for, before they are checked against the work.
	partnerAsked, memberAsked string
	// country is the reader's scope's country ("" the whole deployment),
	// which the Partners' follow-ups are read in.
	country string
	// supervised are the staff the reader supervises (the scope's, active
	// cover included), whose completions a lead reviews.
	supervised []string
	// activityType is the activity filter a link carries
	// (filter_workspace's activity_type), "" for none.
	activityType string
	// regions bound a region's lens (the Regional Programme Lead): nil for
	// a team or the whole country.
	regions []string
	// query is the page's query, which a table's pager reads its page from
	// and carries on.
	query url.Values
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer and for a reader this piece does not
// draw (see the package comment): the existing application answers them.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !role.Page {
		return nil, true, ErrNotAvailable
	}
	if !drawn(p, role) {
		return nil, false, nil
	}
	query = passed(query)
	if !plain(query) {
		return nil, false, nil
	}
	now := s.now()
	per, ok := readPeriod(query, now)
	if !ok {
		return nil, false, nil
	}

	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	own, err := bothIDSpaces(ctx, s.db, []string{p.UserID, p.StaffProfileID})
	if err != nil {
		return nil, true, err
	}
	supervised := scope.SupervisedStaffIDs
	// The widest team any of the page's sources reads: the reader and the
	// people they supervise (the Planning Monitor counts a CCEO's too).
	team, err := bothIDSpaces(ctx, s.db, append(append([]string{}, own...), scope.SupervisedStaffIDs...))
	if err != nil {
		return nil, true, err
	}
	if role.Lens == "country" || role.Lens == "region" {
		var regions []string
		if role.Lens == "region" {
			regions = nonNil(scope.RegionIDs)
		}
		return s.country(ctx, p, role, per, query, scope.Country, regions, supervised, now)
	}
	busy, err := anyPartnerWork(ctx, s.db, team, nonNil(scope.SchoolIDs), per.fy, per.fy == schooldirectory.OperationalFY(now))
	if err != nil {
		return nil, true, err
	}
	if role.EngagementRegister {
		engaged, err := anyEngagement(ctx, s.db, p.UserID)
		if err != nil || engaged {
			return nil, !engaged, err
		}
	}
	w := workspace{role: role, period: per, status: query.Get("status"), fyOptions: schooldirectory.FYOptions(now),
		query: query}
	w.programLead = strings.TrimSpace(query.Get("program_lead"))
	if w.members, err = roster(ctx, s.db, p.UserID); err != nil {
		return nil, true, err
	}
	if w.withTarget, err = isRosterLead(ctx, s.db, own); err != nil {
		return nil, true, err
	}
	w.member = strings.TrimSpace(query.Get("member"))
	if w.member == "" || !w.hasMember(w.member) {
		w.member = "all"
	}
	w.work = workTab(strings.TrimSpace(query.Get("work")))
	if !busy {
		return page(w), true, nil
	}
	w.work = strings.TrimSpace(query.Get("work"))
	w.partnerAsked = strings.TrimSpace(query.Get("partner"))
	w.memberAsked = strings.TrimSpace(query.Get("member"))
	return s.work(ctx, p, w, own, scope.SupervisedStaffIDs, query.Get("activity_type"), now)
}

// drawn is whether this piece draws the reader at all: a field officer or a
// Programme Lead in their own role, reading through their team.
func drawn(p auth.Principal, role Role) bool {
	if p.Acting != nil || p.InActingAppointment {
		return false
	}
	if role.Lens == "country" || role.Lens == "region" {
		// The country or region lens of a country whose roles come from the
		// registry is not drawn yet (docs/migration/80).
		return p.Country == nil || !p.Country.FromRegistry()
	}
	if role.Lens != "team" {
		return false
	}
	return p.ActiveRole == rules.PlanningCCEORole || p.ActiveRole == rules.PlanningLeadRole
}

// plain is whether the query reads as this piece draws it: ASCII alone (a
// Unicode digit is a number to Python), no custom period, and no drawer to
// open on load.
func plain(q url.Values) bool {
	for key, values := range q {
		if contains(customPeriodKeys, key) || contains(rules.EngagementAutoloadParams, key) || key == rules.EngagementPageParam {
			return false
		}
		for _, text := range append([]string{key}, values...) {
			for i := 0; i < len(text); i++ {
				if text[i] >= 0x80 {
					return false
				}
			}
		}
	}
	return true
}

// passed drops the query keys the app's feed never passes to a page.
func passed(query url.Values) url.Values {
	out := url.Values{}
	for key, values := range query {
		if !contains(rules.QueryKeysNotPassed, key) {
			out[key] = values
		}
	}
	return out
}

// workTab is work_tabs with no tables: the tab asked for when it is one
// (Core schools is a tab only for a Partner holding a Core school), else
// the first.
func workTab(requested string) string {
	if requested != rules.CoreWorkTab && contains(rules.WorkTabs, requested) {
		return requested
	}
	return rules.WorkTabs[0]
}

func (w workspace) hasMember(key string) bool {
	for _, m := range w.members {
		if m.key == key {
			return true
		}
	}
	return false
}

func nonNil(ids []string) []string {
	if ids == nil {
		return []string{}
	}
	return ids
}
