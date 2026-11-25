package calendarpage

import (
	"context"
	"errors"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers (apps.mobile_feed.views.NATIVE_PAGES
// names calendar, the URL /calendar).
const Path = "/calendar"

// Service builds the Calendar.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// request is the page's query as the view reads it.
type request struct {
	year         int
	mon          time.Month
	agenda       bool
	kind, status string
	eventKind    string
	person       string
	projectScope string
	project      string
}

// readRequest is calendar_view's reading of its query: a month and year
// that are whole numbers in range (else the month that holds today), and
// filters it knows (else none).
func readRequest(query url.Values, today time.Time) request {
	r := request{year: today.Year(), mon: today.Month()}
	month, year := int(today.Month()), today.Year()
	ok := true
	if query.Has("month") {
		month, ok = closedschools.PyInt(query.Get("month"))
	}
	if ok && query.Has("year") {
		year, ok = closedschools.PyInt(query.Get("year"))
	}
	if ok && month >= 1 && month <= 12 && year >= rules.Years[0] && year <= rules.Years[1] {
		r.year, r.mon = year, time.Month(month)
	}
	r.agenda = query.Get("view") == "agenda"
	if _, known := typeLabels[query.Get("activity_type")]; known {
		r.kind = query.Get("activity_type")
	}
	if _, known := rules.StatusFamilies[query.Get("status")]; known {
		r.status = query.Get("status")
	}
	r.eventKind = "all"
	if in(rules.EventKinds, query.Get("event_kind")) {
		r.eventKind = query.Get("event_kind")
	}
	r.person, r.projectScope, r.project = query.Get("person"), query.Get("project_scope"), query.Get("project")
	return r
}

// Build answers /calendar for p. served is false for another path, and for
// a partner's calendar (its Today table and delivery team), which the
// existing application still answers.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	// The feed's REST framework view answers a ?format= it has no renderer
	// for as not found, for everyone, before the page is asked.
	if format := query.Get("format"); format != "" && !in(rules.APIFormats, format) {
		return nil, true, pagegate.ErrNotAvailable
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if rules.PartnerRoleBridge {
		return nil, false, nil
	}
	// A partner's calendar is its organisation's work (calendar_scope.
	// personal_plan). A login holding an organisation in a staff role, whose
	// strip may show someone else's calendar, is handed on.
	partners, err := partnerIDs(ctx, s.db, p)
	if err != nil {
		return nil, true, err
	}
	if len(partners) > 0 && !in(rules.PartnerRoles, p.ActiveRole) {
		return nil, false, nil
	}
	for _, key := range rules.NotPassedQueryKeys {
		query.Del(key)
	}
	now := s.now()
	v, err := s.view(ctx, p, role, readRequest(query, localDay(now)), now, partners)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return v.page(), true, nil
}

// errHandOn is a calendar Go does not draw yet (handed on).
var errHandOn = errors.New("calendarpage: a calendar Go does not draw yet")

func (s *Service) view(ctx context.Context, p auth.Principal, role Role, r request, now time.Time, partners []string) (*view, error) {
	today := localDay(now)
	start := day(r.year, r.mon, 1)
	end := start.AddDate(0, 1, -1)
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	f := filter{status: r.status, kind: r.kind}
	// Whose work: the Admin's is everyone's; the special-projects lens is
	// its projects'; anyone else's their own plan or a team member's.
	personal := p.ActiveRole != rules.AdminRole
	leaveAll := !personal
	if r.projectScope == "special" {
		ids, err := projectIDs(ctx, s.db, scope, p.ActiveRole, p.StaffProfileID, r.project)
		if err != nil {
			return nil, err
		}
		f.byProject, f.projects = true, ids
		personal = false
	}
	leaveStaff := []string{}
	if p.StaffProfileID != "" {
		leaveStaff = []string{p.StaffProfileID}
	}
	monthRows, err := readActivities(ctx, s.db, scope, start, end, f)
	if err != nil {
		return nil, err
	}
	rows := monthRows
	var teams []team
	var shownTeam *team
	var shown *person
	if personal {
		if teams, err = teamsFor(ctx, s.db, p, scope, now); err != nil {
			return nil, err
		}
		shownTeam, shown = find(teams, r.person)
		switch {
		case shown != nil:
			rows = planOf(monthRows, shown.ids)
			leaveStaff = []string{shown.key}
		case len(partners) > 0:
			rows = organisationPlan(monthRows, partners)
		default:
			rows = planOf(monthRows, ownerIDs(p))
		}
	}
	partnerCalendar := len(partners) > 0 && shown == nil
	if partnerCalendar {
		// A training it facilitates is the officer's record, a link only
		// where it opens (can_view_record): not drawn by Go yet.
		for _, a := range rows {
			if a.delivery != "partner" {
				return nil, errHandOn
			}
		}
	}
	sp := spans(rows)
	book := newHolidayBook(s.db)
	marks, err := dayOffMarks(ctx, s.db, book, rows, sp)
	if err != nil {
		return nil, err
	}
	ticks := map[string]bool{}
	if shown == nil {
		if ticks, err = tickable(ctx, s.db, p, scope, rows); err != nil {
			return nil, err
		}
		// Its organisation's live work, which it holds and may run
		// (group_actions.tickable_ids: a partner supervises nobody).
		if partnerCalendar && rules.Roles[p.ActiveRole].MyPlan {
			for _, a := range rows {
				if a.partnerID != "" && in(partners, a.partnerID) && !in(rules.Untickable, a.status) {
					ticks[a.id] = true
				}
			}
		}
	}
	closed := map[string]bool{}
	if shown != nil {
		if closed, err = unopened(ctx, s.db, p, scope, rows, now); err != nil {
			return nil, err
		}
	}
	m := newMonth(start, end)
	if partnerCalendar {
		m.partner, m.today = true, today
		if m.leads, err = leadsTeam(ctx, s.db, p, partners); err != nil {
			return nil, err
		}
	}
	m.addActivities(rows, sp, marks, ticks, closed)
	leaves, err := readLeave(ctx, s.db, start, end, leaveStaff, leaveAll)
	if err != nil {
		return nil, err
	}
	m.addLeave(leaves, p.StaffProfileID)
	holidays, err := book.between(ctx, start, end)
	if err != nil {
		return nil, err
	}
	m.addHolidays(holidays)
	country, err := viewerCountry(ctx, s.db, p.UserID)
	if err != nil {
		return nil, err
	}
	if p.ActiveRole == rules.AdminRole {
		country = ""
	}
	events, err := readEvents(ctx, s.db, start, end, country)
	if err != nil {
		return nil, err
	}
	m.addEvents(events)
	m.sortDays()

	keep := params{}
	if shown != nil {
		keep.add("person", shown.key)
	}
	if r.projectScope != "" {
		keep.add("project_scope", r.projectScope)
	}
	if r.project != "" {
		keep.add("project", r.project)
	}
	if r.kind != "" {
		keep.add("activity_type", r.kind)
	}
	if r.status != "" {
		keep.add("status", r.status)
	}
	if r.eventKind != "all" {
		keep.add("event_kind", r.eventKind)
	}
	if r.agenda {
		keep.add("view", "agenda")
	}
	v := &view{year: r.year, mon: r.mon, today: today, agenda: r.agenda, m: m, person: shown,
		kind: r.kind, status: r.status, eventKind: r.eventKind, filtersActive: r.kind != "" || r.status != "" || r.eventKind != "all",
		leave: role.Leave, addEvent: role.AddEvent, strip: role.Strip, picks: len(ticks)}
	v.teamTabs, v.memberTabs = peopleTabs(p, teams, shownTeam, shown, monthRows,
		append(params{{"year", itoa(r.year)}, {"month", itoa(int(r.mon))}}, keep...))
	v.hidden = map[string]string{"year": itoa(r.year), "month": itoa(int(r.mon)), "event_kind": ""}
	if r.agenda {
		v.hidden["view"] = "agenda"
	}
	if shown != nil {
		v.hidden["person"] = shown.key
	}
	if r.projectScope != "" {
		v.hidden["project_scope"] = r.projectScope
	}
	if r.project != "" {
		v.hidden["project"] = r.project
	}
	return v, nil
}

// params is an ordered query, as urlencode writes a dict.
type params [][2]string

func (q *params) add(k, v string) { *q = append(*q, [2]string{k, v}) }

func (q params) without(key string) params {
	out := params{}
	for _, kv := range q {
		if kv[0] != key {
			out = append(out, kv)
		}
	}
	return out
}

func (q params) encode() string {
	parts := make([]string, 0, len(q))
	for _, kv := range q {
		parts = append(parts, url.QueryEscape(kv[0])+"="+url.QueryEscape(kv[1]))
	}
	return strings.Join(parts, "&")
}

// peopleTabs is _calendar_people_tabs: the reader's own calendar, then a
// Lead's CCEOs or the Director's teams, and the people of the team opened.
func peopleTabs(p auth.Principal, teams []team, shownTeam *team, shown *person, monthRows []*activity, q params) ([]tab, []tab) {
	if len(teams) == 0 {
		return nil, nil
	}
	const own = "mine"
	holders := map[string][]string{own: ownerIDs(p)}
	for _, t := range teams {
		for _, ps := range t.people {
			holders[ps.key] = ps.ids
		}
	}
	counts := planCounts(monthRows, holders)
	ownQ := q.without("person")
	personTab := func(ps person) tab {
		return tab{label: ps.name, count: counts[ps.key], href: "/calendar?" + append(slices.Clone(ownQ), [2]string{"person", ps.key}).encode()}
	}
	teamTabs := []tab{{label: rules.OwnLabel, count: counts[own], href: "/calendar?" + ownQ.encode()}}
	var memberTabs []tab
	for i := range teams {
		t := &teams[i]
		if t.name == "" {
			for _, ps := range t.people {
				teamTabs = append(teamTabs, personTab(ps))
			}
			continue
		}
		total := 0
		for _, ps := range t.people {
			total += counts[ps.key]
		}
		teamTabs = append(teamTabs, tab{label: t.name, count: total,
			href: "/calendar?" + append(slices.Clone(ownQ), [2]string{"person", t.people[0].key}).encode()})
		if shownTeam != nil && t.key == shownTeam.key {
			for _, ps := range t.people {
				memberTabs = append(memberTabs, personTab(ps))
			}
		}
	}
	return teamTabs, memberTabs
}
