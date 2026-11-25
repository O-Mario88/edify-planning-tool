package calendarpage

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Whose calendar a reader may open besides their own
// (apps.activities.calendar_people): a Programme Lead each CCEO on their
// team, the Country Director every Programme Lead's team.

type person struct {
	key, name string
	// ids are the two ids their work is written under.
	ids []string
}

type team struct {
	key, name string
	people    []person
}

// ownerIDs is scoping.owner_ids: both ids the reader's work is filed under.
func ownerIDs(p auth.Principal) []string {
	out := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			out = append(out, id)
		}
	}
	return out
}

func nameOr(name, email *string, id string) string {
	if name != nil && *name != "" {
		return *name
	}
	if email != nil && *email != "" {
		return *email
	}
	return id
}

// teamsFor is calendar_people.teams_for.
func teamsFor(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope, now time.Time) ([]team, error) {
	switch p.ActiveRole {
	case rules.LeadRole:
		return leadTeam(ctx, db, p, now)
	case rules.DirectorRole:
		if !rules.AllowCDOperational {
			return nil, nil
		}
		return countryTeams(ctx, db, p, scope)
	}
	return nil, nil
}

// leadTeam is hr.team_roster.team_members as one unnamed team: the CCEOs
// the Lead supervises, or those of a Lead they cover while the cover runs,
// who are live, by name.
func leadTeam(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) ([]team, error) {
	if p.StaffProfileID == "" {
		return nil, nil
	}
	rows, err := db.Query(ctx, `
WITH covered AS (
  SELECT original_staff_id FROM temporary_coverage_assignment
  WHERE covering_staff_id = $1 AND start_datetime <= $2 AND end_datetime >= $2 AND status = 'active'),
supervisors AS (
  SELECT $1::varchar AS id
  UNION SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND sp.id IN (SELECT original_staff_id FROM covered)
    AND (u.active_role = $3 OR u.roles @> ARRAY[$3]::varchar[]))
SELECT sp.id, sp.user_id, u.name, u.email
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE (u.active_role = $4 OR u.roles @> ARRAY[$4]::varchar[])
  AND sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id IN (SELECT id FROM supervisors))
  AND sp.deleted_at IS NULL AND u.deleted_at IS NULL AND u.is_active AND sp.id <> $1
ORDER BY u.name ASC`, p.StaffProfileID, now, rules.LeadRole, rules.PlanningCCEORole)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the lead's team: %w", err)
	}
	defer rows.Close()
	people := []person{}
	for rows.Next() {
		var id, userID string
		var name, email *string
		if err := rows.Scan(&id, &userID, &name, &email); err != nil {
			return nil, fmt.Errorf("calendarpage: reading the lead's team: %w", err)
		}
		people = append(people, person{key: id, name: nameOr(name, email, id), ids: bothIDs(id, userID)})
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("calendarpage: reading the lead's team: %w", err)
	}
	if len(people) == 0 {
		return nil, nil
	}
	return []team{{people: people}}, nil
}

func bothIDs(id, userID string) []string {
	out := []string{}
	for _, v := range []string{id, userID} {
		if v != "" && !slices.Contains(out, v) {
			out = append(out, v)
		}
	}
	return out
}

// rosterPerson is country_oversight.rules.roster's Person.
type rosterPerson struct {
	person
	lead bool
}

// countryTeams is calendar_people._country_teams over
// monitor_roster.monitor_roster for a country reader
// (country_oversight.rules.roster): each Programme Lead by name with the
// CCEOs they supervise, then the CCEOs who report to no Lead, the reader
// themself left out.
//
// The country keeps the people to it (country.RosterIn): in Uganda the
// profile's country or none recorded; in a country whose roles come from the
// registry, the Leads and CCEOs who hold those roles there.
func countryTeams(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope) ([]team, error) {
	lead, cceo := rules.PlanningLeadRole, rules.PlanningCCEORole
	r := registry.RosterIn(scope.Country, scope.CountryID, scope.CountryFromRegistry, []string{lead, cceo})
	rows, err := db.Query(ctx, `
SELECT sp.id, sp.user_id, u.name, u.email, `+r.Roles+`, `+r.Active+`
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.is_active AND u.deleted_at IS NULL
  AND `+r.Where, r.Args...)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the roster: %w", err)
	}
	people := map[string]*rosterPerson{}
	order := []string{}
	for rows.Next() {
		var id, userID, active string
		var name, email *string
		var roles []string
		if err := rows.Scan(&id, &userID, &name, &email, &roles, &active); err != nil {
			rows.Close()
			return nil, fmt.Errorf("calendarpage: reading the roster: %w", err)
		}
		held := append(slices.Clone(roles), active)
		var isLead bool
		switch {
		case slices.Contains(held, lead):
			isLead = true
		case slices.Contains(held, cceo):
		default:
			continue
		}
		people[id] = &rosterPerson{person: person{key: id, name: nameOr(name, email, id), ids: bothIDs(id, userID)}, lead: isLead}
		order = append(order, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("calendarpage: reading the roster: %w", err)
	}
	byName := func(list []*rosterPerson) {
		sort.SliceStable(list, func(i, j int) bool {
			a, b := casefold(list[i].name), casefold(list[j].name)
			if a != b {
				return a < b
			}
			return list[i].key < list[j].key
		})
	}
	leads := []*rosterPerson{}
	for _, id := range order {
		if people[id].lead {
			leads = append(leads, people[id])
		}
	}
	byName(leads)
	leadOrder := map[string]int{}
	leadIDs := []string{}
	for i, l := range leads {
		leadOrder[l.key] = i
		leadIDs = append(leadIDs, l.key)
	}
	placed := map[string]string{}
	if len(leads) > 0 {
		rows, err = db.Query(ctx, `
SELECT supervisor_id, supervisee_id FROM staff_supervisor_assignment
WHERE supervisor_id = ANY($1) AND supervisee_id = ANY($2)`, leadIDs, order)
		if err != nil {
			return nil, fmt.Errorf("calendarpage: reading the reporting lines: %w", err)
		}
		for rows.Next() {
			var supervisor, supervisee string
			if err := rows.Scan(&supervisor, &supervisee); err != nil {
				rows.Close()
				return nil, fmt.Errorf("calendarpage: reading the reporting lines: %w", err)
			}
			if people[supervisee].lead || supervisor == supervisee {
				continue
			}
			if current, ok := placed[supervisee]; !ok || leadOrder[supervisor] < leadOrder[current] {
				placed[supervisee] = supervisor
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, fmt.Errorf("calendarpage: reading the reporting lines: %w", err)
		}
	}
	own := ownerIDs(p)
	notOwn := func(list []*rosterPerson) []person {
		out := []person{}
		for _, r := range list {
			mine := false
			for _, id := range r.ids {
				mine = mine || slices.Contains(own, id)
			}
			if !mine {
				out = append(out, r.person)
			}
		}
		return out
	}
	teams := []team{}
	for _, l := range leads {
		members := []*rosterPerson{}
		for _, id := range order {
			if placed[id] == l.key {
				members = append(members, people[id])
			}
		}
		byName(members)
		if kept := notOwn(append([]*rosterPerson{l}, members...)); len(kept) > 0 {
			teams = append(teams, team{key: l.key, name: l.name + "'s team", people: kept})
		}
	}
	loose := []*rosterPerson{}
	for _, id := range order {
		if _, ok := placed[id]; !ok && !people[id].lead {
			loose = append(loose, people[id])
		}
	}
	byName(loose)
	if kept := notOwn(loose); len(kept) > 0 {
		teams = append(teams, team{key: rules.NoLeadKey, name: rules.NoLeadLabel, people: kept})
	}
	return teams, nil
}

// find is calendar_people.find: the person ?person= names on the reader's
// own strip, and their team.
func find(teams []team, key string) (*team, *person) {
	key = closedschools.PyStrip(key)
	if key == "" {
		return nil, nil
	}
	for i := range teams {
		for j := range teams[i].people {
			if teams[i].people[j].key == key {
				return &teams[i], &teams[i].people[j]
			}
		}
	}
	return nil, nil
}

// planOf is calendar_scope.plan_of: the work these ids are responsible for,
// and the partner-delivered work they monitor.
// organisationPlan is calendar_scope.personal_plan for a partner: the work
// scheduled for its organisation, delivered by it or facilitated by it.
func organisationPlan(rows []*activity, partners []string) []*activity {
	out := []*activity{}
	for _, a := range rows {
		if (a.partnerID != "" && in(partners, a.partnerID)) || (a.facilitatingID != "" && in(partners, a.facilitatingID)) {
			out = append(out, a)
		}
	}
	return out
}

func planOf(rows []*activity, ids []string) []*activity {
	out := []*activity{}
	for _, a := range rows {
		if holds(a, ids) {
			out = append(out, a)
		}
	}
	return out
}

func holds(a *activity, ids []string) bool {
	return (a.staffID != "" && slices.Contains(ids, a.staffID)) ||
		(a.monitorID != "" && a.delivery == "partner" && slices.Contains(ids, a.monitorID))
}

// planCounts is calendar_people.plan_counts: how many of the rows are on
// each holder's plan.
func planCounts(rows []*activity, holders map[string][]string) map[string]int {
	counts := map[string]int{}
	for _, a := range rows {
		for tab, ids := range holders {
			if holds(a, ids) {
				counts[tab]++
			}
		}
	}
	return counts
}
