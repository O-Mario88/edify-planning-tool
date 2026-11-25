package planningoversight

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teamtargets"
)

// Piece 2: the Team Plan lens (team_planning_oversight_view with no view)
// for a Programme Lead in their own role: the lens strip, the period bar,
// the headline tiles folded from the team's staff work, the people and
// activity tabs with their counts, the chosen tab's Field Plan with its four
// tables, the per-person chart, School Oversight and the month's Flagged
// schools. Handed on (served=false): an advanced filter or a custom period,
// a reader working as someone else, rows the reader owns (their Actions
// menu) or that offer Complete, a table or flagged list past its first
// page, a flagged school whose problem is the recommendation engine's, and
// a meals line Go does not price.

const (
	wholeTeamKey = "team"
	myWorkKey    = "mine"
	allActivity  = "all"
	// kampala is the application's TIME_ZONE (a date is read in it).
	kampala = "Africa/Kampala"
)

// customPeriodKeys are the Export drawer's period fields and the planning
// follow-up a Country Director's link carries: this slice draws neither.
var customPeriodKeys = []string{"period_type", "from_month", "to_month", "start_date", "end_date", "followup"}

var zone = mustZone(kampala)

func mustZone(name string) *time.Location {
	loc, err := time.LoadLocation(name)
	if err != nil {
		panic(fmt.Sprintf("planningoversight: time zone %s: %v", name, err))
	}
	return loc
}

// person is one entry of the team: a tab (a supervised officer) or a
// roster line (the lead and their reporting line).
type person struct {
	id, name string
	ids      []string // the StaffProfile id and its User id
}

func (p person) owns(id string) bool { return id != "" && slices.Contains(p.ids, id) }

// teamPlan is what the lens draws.
type teamPlan struct {
	period      partneroversight.Period
	periodLabel string
	fyOptions   []string
	owner       string // the chosen tab's key
	activity    string
	tabs        []Tab // Whole team, My Work, one per officer
	panelName   string
	ownLabel    string
	// The reader's lens: what its role draws, and whether it reads many
	// Programme Leads (the country and region lenses).
	reader    Reader
	country   bool
	region    bool
	lensTitle string
	years     []string
	read      periodRead
	groups    []officerGroup // the country lens's officer switches
	shown     int            // the open switch
	// The work: each tab's items, the fold of what is shown, the panel's
	// fold and tables, and the month's flagged schools.
	query        url.Values // the query the page was opened with (the pagers')
	tabItems     map[string][]*item
	summary      fold
	panelSummary fold
	streams      [4][]*item
	flagged      flaggedSchools
	today        time.Time
}

// buildTeamPlan answers the Team Plan for p, or served=false: the team
// lens for a Programme Lead, the country lens for a country reader.
func (s *Service) buildTeamPlan(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	reader, ok := rules.TeamPlan.Readers[p.ActiveRole]
	if !ok || !reader.Planning || p.Acting != nil || p.InActingAppointment {
		return nil, false, nil
	}
	query = passed(query)
	if !plainTeamQuery(query) {
		return nil, false, nil
	}
	switch activeLens(reader, query) {
	case "planning":
	case "coverage":
		return s.buildCoverage(ctx, p, reader, query)
	case "targets":
		return s.buildTargets(ctx, p, reader, query)
	default:
		return nil, false, nil
	}
	switch reader.Scope {
	case "country", "region":
		return s.buildCountryPlan(ctx, p, reader, query)
	case "pl":
		if p.ActiveRole == rules.TeamPlan.LeadRole {
			return s.buildLeadPlan(ctx, p, reader, query)
		}
	}
	return nil, false, nil
}

// buildLeadPlan is the team lens: the Lead's own work and their officers'.
func (s *Service) buildLeadPlan(ctx context.Context, p auth.Principal, reader Reader, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	now := s.now()
	per, ok := partneroversight.ReadPeriod(query, now)
	if !ok {
		return nil, false, nil
	}
	w, served, err := s.lensBase(ctx, p, reader, query, per, now)
	if !served || err != nil {
		return nil, served, err
	}
	years, read, today := w.years, w.read, w.today

	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	own, err := partneroversight.BothIDSpaces(ctx, s.db, []string{p.UserID, p.StaffProfileID})
	if err != nil {
		return nil, true, err
	}
	supervised, err := partneroversight.BothIDSpaces(ctx, s.db, scope.SupervisedStaffIDs)
	if err != nil {
		return nil, true, err
	}
	supervised = slices.DeleteFunc(supervised, func(id string) bool { return slices.Contains(own, id) })
	team := append(append([]string{}, own...), supervised...)
	if len(team) == 0 {
		return nil, false, nil
	}
	items, err := s.buildItems(ctx, team, nil, years, read, today)
	if err != nil {
		return nil, true, err
	}
	flagged, err := s.flaggedFor(ctx, team, per, now)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}

	members, err := s.members(ctx, supervised)
	if err != nil {
		return nil, true, err
	}
	roster, err := s.roster(ctx, p.UserID)
	if err != nil {
		return nil, true, err
	}
	w.flagged = flagged
	w.tabs, w.owner = ownerTabs(members, strings.TrimSpace(query.Get("owner")))
	w.tabItems = map[string][]*item{wholeTeamKey: items, myWorkKey: ownedBy(items, own)}
	for _, m := range members {
		w.tabItems[m.id] = ownedBy(items, m.ids)
	}
	visible := inFamily(w.tabItems[w.owner], w.activity)
	w.summary = summarize(visible, today)
	groups := rosterFor(roster, w.owner)
	if len(groups) == 0 {
		return nil, false, nil
	}
	panelItems, single, err := s.panelGroup(ctx, groups, visible)
	if err != nil {
		return nil, true, err
	}
	w.panelName, w.panelSummary = tabLabel(w.tabs, w.owner), w.summary
	if single != nil {
		w.panelName, w.panelSummary = single.name, summarize(panelItems, today)
	}
	viewer := []string{p.UserID, p.StaffProfileID}
	for _, it := range panelItems {
		if it.showsComplete || (it.owner != "" && slices.Contains(viewer, it.owner)) {
			return nil, false, nil
		}
	}
	if single != nil && (slices.Contains(viewer, single.id) || strings.EqualFold(single.name, p.Name)) && len(panelItems) > 0 {
		return nil, false, nil
	}
	w.streams, err = s.streams(ctx, p.Country, panelItems, today)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	for _, rows := range w.streams {
		for _, it := range rows {
			if it.showsComplete {
				return nil, false, nil
			}
		}
	}
	w.ownLabel = p.Name
	if w.ownLabel == "" {
		w.ownLabel = "My work"
	}
	w.ownLabel += " (you)"
	return teamPage(w), true, nil
}

// ownedBy is _items_owned_by for one person: the items whose owner (who
// planned them too, for staff work) is one of their ids.
func ownedBy(items []*item, ids []string) []*item {
	out := []*item{}
	for _, it := range items {
		if it.owner != "" && slices.Contains(ids, it.owner) {
			out = append(out, it)
		}
	}
	return out
}

// panelGroup is group_by_owner over the roster and _tab_panel_group: the
// one person the panel is, with their items, or (nil) everyone's rows
// together under the tab's name.
func (s *Service) panelGroup(ctx context.Context, roster []person, visible []*item) ([]*item, *person, error) {
	filed := make([][]*item, len(roster))
	remaining := []*item{}
	for _, it := range visible {
		found := -1
		for i, m := range roster {
			if m.owns(it.owner) {
				found = i // a later member holding the same id wins, as the lookup does
			}
		}
		if found < 0 {
			remaining = append(remaining, it)
			continue
		}
		filed[found] = append(filed[found], it)
	}
	others, err := s.peopleOf(ctx, remaining)
	if err != nil {
		return nil, nil, err
	}
	switch {
	case len(roster) == 1 && len(others) == 0:
		return filed[0], &roster[0], nil
	case len(roster) == 0 && len(others) == 1:
		return remaining, &others[0], nil
	}
	return visible, nil, nil
}

// peopleOf is _group_by_person's groups over items: one per person, both
// id spaces folded into the profile.
func (s *Service) peopleOf(ctx context.Context, items []*item) ([]person, error) {
	if len(items) == 0 {
		return nil, nil
	}
	owners := []string{}
	for _, it := range items {
		if it.owner != "" {
			owners = append(owners, it.owner)
		}
	}
	canonical := map[string]string{}
	if len(owners) > 0 {
		rows, err := s.db.Query(ctx, `SELECT id, COALESCE(user_id, '') FROM staff_profile WHERE id = ANY($1) OR user_id = ANY($1)`, owners)
		if err != nil {
			return nil, fmt.Errorf("planningoversight: reading the owners: %w", err)
		}
		for rows.Next() {
			var id, user string
			if err := rows.Scan(&id, &user); err != nil {
				rows.Close()
				return nil, fmt.Errorf("planningoversight: reading the owners: %w", err)
			}
			for _, key := range []string{id, user} {
				if key != "" && slices.Contains(owners, key) {
					canonical[key] = id
				}
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	out := []person{}
	for _, it := range items {
		key := canonical[it.owner]
		if key == "" {
			key = it.owner
		}
		if !slices.ContainsFunc(out, func(p person) bool { return p.id == key }) {
			out = append(out, person{id: key, name: first(it.ownerName, "Unassigned")})
		}
	}
	return out, nil
}

// plainTeamQuery is whether the query reads as this lens draws it: one
// view at most, ASCII alone (a Unicode digit is a number to Python), no
// custom period or follow-up, and no advanced filter.
func plainTeamQuery(q url.Values) bool {
	if v, ok := q["view"]; ok && len(v) != 1 {
		return false
	}
	for key, values := range q {
		if slices.Contains(customPeriodKeys, key) {
			return false
		}
		if slices.Contains(rules.TeamPlan.FilterKeys, key) {
			for _, v := range values {
				if strings.TrimSpace(v) != "" {
					return false
				}
			}
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

// otherLenses are the views team_planning_oversight_view answers with a
// lens of their own; anything else is the planning lens.
var otherLenses = []string{"targets", "coverage", "portfolio", "monitor", "execution", "trainings"}

// activeLens is the lens team_planning_oversight_view opens for the asked
// ?view= ("" where it redirects instead): a lens the reader does not hold
// falls back to planning, and planning to targets for a reader without it.
func activeLens(r Reader, q url.Values) string {
	view := strings.ToLower(strings.TrimSpace(q.Get("view")))
	if q.Get("view") == "" {
		view = "planning"
	}
	switch {
	case view == "projects" || view == "clusters":
		return ""
	case (view == "monitor" || view == "execution") && !r.Lenses["monitors"]:
		return ""
	}
	active := "planning"
	if slices.Contains(otherLenses, view) {
		active = view
	}
	for _, lens := range []string{"trainings", "targets", "coverage", "portfolio"} {
		if active == lens && !r.Lenses[lens] {
			active = "planning"
		}
	}
	if (active == "planning" || active == "coverage" || active == "portfolio") && !r.Lenses["planning"] {
		active = "targets"
	}
	return active
}

// passed drops the query keys the app's feed never passes to a page.
func passed(query url.Values) url.Values {
	out := url.Values{}
	for key, values := range query {
		if !slices.Contains(rules.TeamPlan.QueryKeysNotPassed, key) {
			out[key] = values
		}
	}
	return out
}

// periodRead is the part of _plan_period beyond the years: a month, a
// quarter, or a run of dated days [start, end).
type periodRead struct {
	month      int
	quarter    string
	start, end time.Time
}

// planPeriod is _plan_period with _plan_period_label: the years a plan read
// covers, how the page names the period, and what narrows it.
func (s *Service) planPeriod(ctx context.Context, place *registry.Work, per partneroversight.Period, fyOptions []string, now time.Time) ([]string, string, periodRead, error) {
	switch per.Kind {
	case "month":
		return []string{per.FY}, monthNames[per.Month-1] + " · FY " + per.FY, periodRead{month: per.Month}, nil
	case "quarter":
		return []string{per.FY}, per.Quarter + " · FY " + per.FY, periodRead{quarter: per.Quarter}, nil
	case "week":
		start := weekStart(per.Week)
		end := start.AddDate(0, 0, 7)
		years := []string{schooldirectory.OperationalFY(start)}
		if last := schooldirectory.OperationalFY(end.AddDate(0, 0, -1)); last != years[0] {
			years = append(years, last)
			sort.Strings(years)
		}
		return years, "Week of " + start.Format("02 Jan 2006"), periodRead{start: start, end: end}, nil
	}
	operational, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
	years, err := schoolplanning.Horizon(ctx, s.db, place, per.FY, operational, fyOptions, now)
	if err != nil {
		return nil, "", periodRead{}, err
	}
	return years, horizonLabel(years), periodRead{}, nil
}

// horizonLabel is fy_policy.horizon_label.
func horizonLabel(years []string) string {
	sorted := append([]string{}, years...)
	sort.Strings(sorted)
	switch len(sorted) {
	case 0:
		return ""
	case 1:
		return "FY " + sorted[0]
	}
	return "FY " + sorted[0] + "–" + sorted[len(sorted)-1]
}

// weekStart is the Monday of an ISO week "YYYY-Www" (readPeriod has
// checked its shape).
func weekStart(week string) time.Time {
	year, _ := strconv.Atoi(week[:4])
	n, _ := strconv.Atoi(week[6:])
	jan4 := time.Date(year, time.January, 4, 0, 0, 0, 0, time.UTC)
	monday := jan4.AddDate(0, 0, -((int(jan4.Weekday()) + 6) % 7))
	return monday.AddDate(0, 0, (n-1)*7)
}

var monthNames = []string{"January", "February", "March", "April", "May", "June", "July",
	"August", "September", "October", "November", "December"}

// dated is oversight_service._dated_between over [$s, $e): the planned
// date, or for an undated row its scheduled day in the application's zone.
func dated(s, e string) string {
	return "((a.planned_date >= " + s + " AND a.planned_date < " + e + ") OR (a.planned_date IS NULL AND " +
		"(a.scheduled_date AT TIME ZONE '" + kampala + "')::date >= " + s + " AND " +
		"(a.scheduled_date AT TIME ZONE '" + kampala + "')::date < " + e + "))"
}

// members is _team_members: the live profiles the lens supervises, one tab
// each, by name.
func (s *Service) members(ctx context.Context, supervised []string) ([]person, error) {
	if len(supervised) == 0 {
		return nil, nil
	}
	return s.people(ctx, `
SELECT DISTINCT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, ''), u.name
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))
ORDER BY u.name`, supervised)
}

// roster is oversight_service.program_lead_members(team_lead_user_id): the
// reader's live profile holding the Lead role (the first by key), then
// everyone with a reporting line to it, by name.
func (s *Service) roster(ctx context.Context, userID string) ([]person, error) {
	var lead person
	var userOf string
	err := s.db.QueryRow(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = $1 OR sp.user_id = $1)
  AND (u.active_role = $2 OR $2 = ANY(COALESCE(u.roles, '{}')))
ORDER BY sp.id LIMIT 1`, userID, rules.TeamPlan.LeadRole).Scan(&lead.id, &userOf, &lead.name)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the team's Lead: %w", err)
	}
	lead.ids = []string{lead.id, userOf}
	rest, err := s.people(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, ''), u.name
FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisee_id
JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisor_id = $1 AND a.supervisee_id <> a.supervisor_id
ORDER BY u.name, a.supervisee_id`, lead.id)
	if err != nil {
		return nil, err
	}
	return append([]person{lead}, rest...), nil
}

func (s *Service) people(ctx context.Context, sql string, arg any) ([]person, error) {
	rows, err := s.db.Query(ctx, sql, arg)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the team: %w", err)
	}
	defer rows.Close()
	out := []person{}
	for rows.Next() {
		var p person
		var userID string
		var order *string
		if err := rows.Scan(&p.id, &userID, &p.name, &order); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the team: %w", err)
		}
		p.ids = []string{p.id, userID}
		out = append(out, p)
	}
	return out, rows.Err()
}

// ownerTabs is _team_owner_tabs over no work: Whole team, My Work, one tab
// per officer, and the key of the tab chosen (an officer's User id finds
// their tab; anything else is Whole team).
func ownerTabs(members []person, selected string) ([]Tab, string) {
	tabs := []Tab{}
	for _, t := range rules.TeamPlan.OwnerTabs {
		tabs = append(tabs, Tab{Key: t.Key, Label: t.Label})
	}
	for _, m := range members {
		tabs = append(tabs, Tab{Key: m.id, Label: m.name})
	}
	if selected == "" {
		selected = wholeTeamKey
	}
	active := -1
	for i, t := range tabs {
		if t.Key == selected {
			active = i
			break
		}
	}
	if active < 0 {
		active = 0
		for _, m := range members {
			if m.owns(selected) {
				for i, t := range tabs {
					if t.Key == m.id {
						active = i
					}
				}
				break
			}
		}
	}
	tabs[active].Active = true
	return tabs, tabs[active].Key
}

// rosterFor is _team_roster: the people the chosen tab files work under
// (none: the page is not this slice's).
func rosterFor(roster []person, selected string) []person {
	if len(roster) == 0 {
		return nil
	}
	switch selected {
	case wholeTeamKey:
		return roster
	case myWorkKey:
		return roster[:1]
	}
	out := []person{}
	for _, p := range roster {
		if p.owns(selected) {
			out = append(out, p)
		}
	}
	return out
}

func tabLabel(tabs []Tab, key string) string {
	for _, t := range tabs {
		if t.Key == key {
			return t.Label
		}
	}
	return ""
}

// buildTargets is the Target Performance lens: Team Targets
// (teamtargets.Page) under the lens strip with its own tab active.
func (s *Service) buildTargets(ctx context.Context, p auth.Principal, reader Reader, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	page, err := teamtargets.Page(ctx, s.db, p, teamtargets.Query(query), s.now())
	if errors.Is(err, teamtargets.ErrHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	tabs := lensTabs(reader)
	for _, b := range tabs {
		for _, t := range b.GetLinkTabs().GetTabs() {
			t.Active = strings.HasSuffix(t.GetHref(), "?view=targets")
		}
	}
	page.Blocks = append(tabs, page.Blocks...)
	page.WebPath = "/team-planning-oversight/"
	return page, true, nil
}
