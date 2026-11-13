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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// Piece 2 (first slice): the Team Plan lens (team_planning_oversight_view
// with no view) for a Programme Lead in their own role whose team has
// nothing planned in the period and no flagged school: the lens strip, the
// period bar, the headline tiles over no work, the people and activity
// tabs, the chosen tab's Field Plan with its four empty tables, the
// per-person chart, School Oversight and an empty Flagged schools. Any
// reader or question outside that is handed on (served=false).

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
}

// buildTeamPlan answers the Team Plan for p, or served=false.
func (s *Service) buildTeamPlan(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	tp := rules.TeamPlan
	if p.ActiveRole != tp.LeadRole || p.Acting != nil || p.InActingAppointment {
		return nil, false, nil
	}
	query = passed(query)
	if !plainTeamQuery(query) {
		return nil, false, nil
	}
	now := s.now()
	per, ok := partneroversight.ReadPeriod(query, now)
	if !ok {
		return nil, false, nil
	}
	fyOptions := schooldirectory.FYOptions(now)
	years, label, read, err := s.planPeriod(ctx, per, fyOptions, now)
	if err != nil {
		return nil, true, err
	}

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
	if busy, err := s.anyPlanned(ctx, team, years, read); err != nil || busy {
		return nil, err != nil, err
	}
	if busy, err := s.anyFlaggable(ctx, team, per, now); err != nil || busy {
		return nil, err != nil, err
	}

	members, err := s.members(ctx, supervised)
	if err != nil {
		return nil, true, err
	}
	roster, err := s.roster(ctx, p.UserID)
	if err != nil {
		return nil, true, err
	}
	w := teamPlan{period: per, periodLabel: label, fyOptions: fyOptions, activity: allActivity}
	if a := strings.TrimSpace(query.Get("activity")); a != "" {
		w.activity = a
	}
	w.tabs, w.owner = ownerTabs(members, strings.TrimSpace(query.Get("owner")))
	groups := rosterFor(roster, w.owner)
	if len(groups) == 0 {
		return nil, false, nil
	}
	w.panelName = tabLabel(w.tabs, w.owner)
	if len(groups) == 1 {
		w.panelName = groups[0].name
	}
	w.ownLabel = p.Name
	if w.ownLabel == "" {
		w.ownLabel = "My work"
	}
	w.ownLabel += " (you)"
	return teamPage(w), true, nil
}

// plainTeamQuery is whether the query reads as this slice draws it: the
// planning lens named or left out, ASCII alone (a Unicode digit is a number
// to Python), no custom period or follow-up, and no advanced filter.
func plainTeamQuery(q url.Values) bool {
	if v, ok := q["view"]; ok && (len(v) != 1 || v[0] != "planning") {
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
func (s *Service) planPeriod(ctx context.Context, per partneroversight.Period, fyOptions []string, now time.Time) ([]string, string, periodRead, error) {
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
	years, err := schoolplanning.Horizon(ctx, s.db, per.FY, operational, fyOptions, now)
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

// anyPlanned is whether build_items could hold anything for the team in the
// period: a live activity of theirs (_activity_queryset with
// _activity_scope_q). Partner work counts too, so the answer is at least as
// wide as the page's (which drops partner work); unscheduled hand-overs are
// partner work alone and never reach this lens.
func (s *Service) anyPlanned(ctx context.Context, team, years []string, read periodRead) (bool, error) {
	args := []any{rules.TeamPlan.LiveActivityStatuses, years, team}
	where := ""
	switch {
	case read.month != 0:
		year, _ := strconv.Atoi(years[0])
		first := time.Date(year, time.Month(read.month), 1, 0, 0, 0, 0, time.UTC)
		if read.month >= 10 {
			first = first.AddDate(-1, 0, 0)
		}
		args = append(args, read.month, first, first.AddDate(0, 1, 0))
		where = " AND ((a.planned_date IS NULL AND a.scheduled_date IS NULL AND a.planned_month = $4) OR " + dated("$5::date", "$6::date") + ")"
	case read.quarter != "":
		args = append(args, read.quarter)
		where = " AND a.quarter = $4"
	case !read.start.IsZero():
		args = append(args, read.start, read.end)
		where = " AND " + dated("$4::date", "$5::date")
	}
	var found bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1 FROM activity a
  LEFT JOIN school sc ON sc.id = a.school_id
  LEFT JOIN cluster c ON c.id = a.cluster_id
  WHERE a.deleted_at IS NULL AND a.status = ANY($1) AND a.fy = ANY($2)`+where+`
    AND (a.responsible_staff_id = ANY($3) OR a.monitored_by_staff_id = ANY($3)
         OR sc.account_owner_id = ANY($3) OR c.responsible_staff_id = ANY($3)))`, args...).Scan(&found)
	if err != nil {
		return false, fmt.Errorf("planningoversight: reading the team's plan: %w", err)
	}
	return found, nil
}

// anyFlaggable is whether team_flagged_schools has a school to classify: an
// activity of the team's at a school in the page year's month (the chosen
// month, else today's), not cancelled, rejected or deferred.
func (s *Service) anyFlaggable(ctx context.Context, team []string, per partneroversight.Period, now time.Time) (bool, error) {
	month := int(now.In(zone).Month())
	if per.Kind == "month" {
		month = per.Month
	}
	year, _ := strconv.Atoi(per.FY)
	if month < 10 {
		year++
	}
	first := time.Date(year-1, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
	var found bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1 FROM activity
  WHERE fy = $1 AND planned_date >= $2::date AND planned_date < $3::date AND deleted_at IS NULL
    AND (status IS NULL OR NOT status = ANY($4))
    AND responsible_staff_id = ANY($5) AND school_id IS NOT NULL)`,
		per.FY, first, first.AddDate(0, 1, 0), rules.TeamPlan.NotPlannedStatuses, team).Scan(&found)
	if err != nil {
		return false, fmt.Errorf("planningoversight: reading the month's planned schools: %w", err)
	}
	return found, nil
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
