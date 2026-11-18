package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strings"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Officer is one person's year (OfficerMonitor). Every figure is folded from
// Schools.
type Officer struct {
	Key, Name        string
	LeadID, LeadName string
	VisitsTarget     int
	Role             string
	IDs              []string
	Schools          []*School
	// Outreach are the schools held that take no visit and no training.
	Outreach []*School
	// What the person planned, wherever it is (_count_planned_visits).
	PlannedCore, PlannedClient, PlannedDone int
	// The Partner work the person hands over and monitors.
	PartnerAssignedSchools, PartnerScheduled, PartnerDelivered, PartnerAwaiting int
	// Their project ceilings put together, and the schools they added.
	ProjectCeiling, ProjectAdded int
}

// Lead is a Programme Lead's column: their people and the sums of them.
type Lead struct {
	Key, Name string
	Officers  []*Officer
}

// rosterPerson is one person of rules.roster.
type rosterPerson struct {
	key, name, role string
	ids             []string
	lead            bool
}

// rosterTeam is one of rules.roster's teams: a Lead and their CCEOs, or the
// CCEOs with no Lead.
type rosterTeam struct {
	lead   Lead
	people []rosterPerson
	noLead bool
}

// leadTeam is monitor_roster for a Programme Lead: themselves, then the
// CCEOs they supervise by name (rules.roster's team whose Lead is one of
// wanted), the people the planning rulebook follows by the role they hold.
func (m *monitor) leadTeam(ctx context.Context, wanted []string) (*Lead, []rosterPerson, error) {
	teams, err := m.roster(ctx, countryLens{})
	if err != nil {
		return nil, nil, err
	}
	for _, t := range teams {
		if !t.noLead && intersects(t.people[0].ids, wanted) {
			lead := t.lead
			return &lead, t.people, nil
		}
	}
	return nil, nil, nil
}

// roster is rules.roster: every Programme Lead with their CCEOs (a CCEO on
// several Leads' lines under the first by name), then the CCEOs with no
// Lead; a country keeps the people to it (country.RosterIn: in Uganda the
// profile's country or none recorded; in a country whose roles come from the
// registry, the roles held there). The zero lens is unbounded.
func (m *monitor) roster(ctx context.Context, in countryLens) ([]rosterTeam, error) {
	r := registry.RosterIn(in.name, in.id, in.fromRegistry, []string{rules.ProgramLeadRole, rules.CCEORole})
	rows, err := m.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), sp.id),
  `+r.Active+`, `+r.Roles+`
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.is_active AND u.deleted_at IS NULL
AND `+r.Where, r.Args...)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the roster: %w", err)
	}
	people := map[string]rosterPerson{}
	for rows.Next() {
		var id, user, name, active string
		var roles []string
		if err := rows.Scan(&id, &user, &name, &active, &roles); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningmonitor: the roster: %w", err)
		}
		role := planningRole(roles, active)
		if role == "" {
			continue
		}
		ids := []string{id}
		if user != "" {
			ids = append(ids, user)
		}
		people[id] = rosterPerson{key: id, name: name, role: rules.RoleCodes[role], ids: ids, lead: role == rules.ProgramLeadRole}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var leads []rosterPerson
	for _, p := range people {
		if p.lead {
			leads = append(leads, p)
		}
	}
	byName := func(ps []rosterPerson) {
		sort.Slice(ps, func(i, j int) bool {
			a, b := strings.ToLower(ps[i].name), strings.ToLower(ps[j].name)
			if a != b {
				return a < b
			}
			return ps[i].key < ps[j].key
		})
	}
	byName(leads)
	order := map[string]int{}
	leadKeys := make([]string, len(leads))
	for i, l := range leads {
		order[l.key], leadKeys[i] = i, l.key
	}
	keys := make([]string, 0, len(people))
	for k := range people {
		keys = append(keys, k)
	}
	placed := map[string]string{}
	links, err := m.db.Query(ctx, `SELECT supervisor_id, supervisee_id FROM staff_supervisor_assignment
WHERE supervisor_id = ANY($1) AND supervisee_id = ANY($2)`, leadKeys, keys)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the reporting lines: %w", err)
	}
	for links.Next() {
		var sup, sub string
		if err := links.Scan(&sup, &sub); err != nil {
			links.Close()
			return nil, fmt.Errorf("planningmonitor: the reporting lines: %w", err)
		}
		if people[sub].lead || sup == sub {
			continue
		}
		if cur, ok := placed[sub]; !ok || order[sup] < order[cur] {
			placed[sub] = sup
		}
	}
	links.Close()
	teams := []rosterTeam{}
	for _, l := range leads {
		var members []rosterPerson
		for sub, sup := range placed {
			if sup == l.key {
				members = append(members, people[sub])
			}
		}
		byName(members)
		teams = append(teams, rosterTeam{lead: Lead{Key: l.key, Name: l.name}, people: append([]rosterPerson{l}, members...)})
	}
	var loose []rosterPerson
	for _, p := range people {
		if _, ok := placed[p.key]; !ok && !p.lead {
			loose = append(loose, p)
		}
	}
	if len(loose) > 0 {
		byName(loose)
		teams = append(teams, rosterTeam{lead: Lead{Key: rules.NoLead[0], Name: rules.NoLead[1]}, people: loose, noLead: true})
	}
	return teams, nil
}

func intersects(a, b []string) bool {
	for _, x := range a {
		if slices.Contains(b, x) {
			return true
		}
	}
	return false
}

// planningRole is rules.planning_role: Programme Lead before CCEO, or "".
// countryLens is the country a roster is kept to: its name, registry id and
// whether its roles come from the registry; the zero lens is unbounded.
type countryLens struct {
	name, id     string
	fromRegistry bool
}

func lensOf(scope schooldirectory.Scope) countryLens {
	return countryLens{name: scope.Country, id: scope.CountryID, fromRegistry: scope.CountryFromRegistry}
}

func planningRole(roles []string, active string) string {
	held := append(slices.Clone(roles), active)
	switch {
	case slices.Contains(held, rules.ProgramLeadRole):
		return rules.ProgramLeadRole
	case slices.Contains(held, rules.CCEORole):
		return rules.CCEORole
	}
	return ""
}

// people is _people for a Programme Lead's team (the roster team whose
// Lead is one of wanted).
func (m *monitor) people(ctx context.Context, wanted []string) error {
	team, members, err := m.leadTeam(ctx, wanted)
	if err != nil {
		return err
	}
	teams := []rosterTeam{}
	if team != nil {
		teams = append(teams, rosterTeam{lead: *team, people: members})
	}
	return m.peopleOf(ctx, teams)
}

// peopleOf is _people: the roster's rows, then a row for whoever else holds
// a school in scope, then Unassigned for the schools nobody holds.
func (m *monitor) peopleOf(ctx context.Context, teams []rosterTeam) error {
	m.officers, m.leadsByKey, m.teams = map[string]*Officer{}, map[string]*Lead{}, teams
	leadFor := func(key, name string) *Lead {
		if l, ok := m.leadsByKey[key]; ok {
			return l
		}
		l := &Lead{Key: key, Name: name}
		m.leadsByKey[key] = l
		m.leadOrder = append(m.leadOrder, l)
		return l
	}
	add := func(l *Lead, key, name, role string, ids []string, target int) {
		o := &Officer{Key: key, Name: name, LeadID: l.Key, LeadName: l.Name, VisitsTarget: target, Role: role, IDs: ids}
		m.officers[key] = o
		l.Officers = append(l.Officers, o)
	}
	for _, t := range teams {
		l := leadFor(t.lead.Key, t.lead.Name)
		for _, p := range t.people {
			if _, ok := m.officers[p.key]; !ok {
				add(l, p.key, p.name, p.role, p.ids, rules.VisitTargets[p.role])
			}
		}
	}
	var extra []*School
	unassigned := false
	for _, s := range m.schoolOrder {
		switch {
		case s.OfficerID == rules.Unassigned[0]:
			unassigned = true
		case m.officers[s.OfficerID] == nil:
			extra = append(extra, s)
		}
	}
	for _, s := range m.outreachOrder {
		switch {
		case s.OfficerID == rules.Unassigned[0]:
			unassigned = true
		case m.officers[s.OfficerID] == nil:
			extra = append(extra, s)
		}
	}
	if len(extra) > 0 {
		ids := map[string]bool{}
		for _, s := range extra {
			ids[s.OfficerID] = true
		}
		roles, spaces, err := m.rolesAndIDs(ctx, keysOf(ids))
		if err != nil {
			return err
		}
		sort.SliceStable(extra, func(i, j int) bool {
			return strings.ToLower(extra[i].OfficerName) < strings.ToLower(extra[j].OfficerName)
		})
		for _, s := range extra {
			if m.officers[s.OfficerID] != nil {
				continue
			}
			key, name := rules.NoLead[0], rules.NoLead[1]
			if _, ok := m.leadsByKey[s.LeadID]; ok {
				key, name = s.LeadID, s.LeadName
			}
			idsOf := spaces[s.OfficerID]
			if len(idsOf) == 0 {
				idsOf = []string{s.OfficerID}
			}
			add(leadFor(key, name), s.OfficerID, s.OfficerName, roles[s.OfficerID], idsOf, rules.VisitTargets[roles[s.OfficerID]])
		}
	}
	if unassigned {
		add(leadFor(rules.Unassigned[0], rules.Unassigned[1]), rules.Unassigned[0], rules.Unassigned[1], "", nil, 0)
	}
	return nil
}

func keysOf(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	return out
}

// rolesAndIDs is roles_of and _both_ids: each profile's planning role code,
// and its ids in both spaces.
func (m *monitor) rolesAndIDs(ctx context.Context, staff []string) (map[string]string, map[string][]string, error) {
	roles, spaces := map[string]string{}, map[string][]string{}
	for _, id := range staff {
		spaces[id] = []string{id}
	}
	rows, err := m.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.roles, '{}'), COALESCE(u.active_role, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1)`, staff)
	if err != nil {
		return nil, nil, fmt.Errorf("planningmonitor: the holders' roles: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user, active string
		var held []string
		if err := rows.Scan(&id, &user, &held, &active); err != nil {
			return nil, nil, fmt.Errorf("planningmonitor: the holders' roles: %w", err)
		}
		if user != "" {
			spaces[id] = append(spaces[id], user)
		}
		if role := planningRole(held, active); role != "" {
			roles[id] = rules.RoleCodes[role]
		}
	}
	return roles, spaces, rows.Err()
}

// countPlannedVisits is _count_planned_visits (staff_plan.visit_tallies):
// each person's own counted staff visits in the year, wherever they are,
// Core or Client by the school's type, and those delivered.
func (m *monitor) countPlannedVisits(ctx context.Context) error {
	byID := map[string]*Officer{}
	ids := []string{}
	for _, o := range m.allOfficers() {
		for _, id := range o.IDs {
			byID[id] = o
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return nil
	}
	b := &sql{}
	q := fmt.Sprintf(`SELECT a.responsible_staff_id, COALESCE(s.school_type, ''), COALESCE(a.status, ''), count(*)
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.responsible_staff_id = ANY(%s) AND a.fy = %s AND %s AND %s AND a.delivery_type IS DISTINCT FROM 'partner'
GROUP BY 1, 2, 3`, b.arg(ids), b.arg(m.fy), b.planned(), b.countedVisit(m.outside))
	return m.each(ctx, q, b.args, func(scan func(...any) error) error {
		var who, schoolType, status string
		var n int
		if err := scan(&who, &schoolType, &status, &n); err != nil {
			return err
		}
		o := byID[who]
		if o == nil {
			return nil
		}
		if isCore(schoolType) {
			o.PlannedCore += n
		} else {
			o.PlannedClient += n
		}
		if slices.Contains(rules.DeliveredStatuses, status) {
			o.PlannedDone += n
		}
		return nil
	})
}

// countPartnerWork is _count_partner_work: each person's Partner work in the
// year as Country Planning Oversight credits it — its monitor, then who
// assigned or is responsible for it, then whoever holds the school.
func (m *monitor) countPartnerWork(ctx context.Context) error {
	byID := map[string]*Officer{}
	ids := []string{}
	for _, o := range m.allOfficers() {
		for _, id := range o.IDs {
			byID[id] = o
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return nil
	}
	ownerOf := func(candidates ...string) *Officer {
		for _, c := range candidates {
			if c != "" {
				return byID[c]
			}
		}
		return nil
	}
	schools := map[*Officer]map[string]bool{}
	note := func(o *Officer, school string) {
		if school == "" {
			return
		}
		if schools[o] == nil {
			schools[o] = map[string]bool{}
		}
		schools[o][school] = true
	}
	b := &sql{}
	q := fmt.Sprintf(`SELECT COALESCE(a.monitored_by_staff_id, ''), COALESCE(a.responsible_staff_id, ''), COALESCE(s.account_owner_id, ''),
  COALESCE(a.school_id, ''), COALESCE(a.status, ''), COALESCE(%s, false)
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.fy = %s AND a.deleted_at IS NULL AND %s AND %s
AND (a.monitored_by_staff_id = ANY(%s) OR a.responsible_staff_id = ANY(%[5]s) OR s.account_owner_id = ANY(%[5]s))
AND a.id NOT IN (SELECT h.source_activity_id FROM partner_assignment h WHERE h.status = ANY(%s) AND h.source_activity_id IS NOT NULL)`,
		b.partnerPlanned(), b.arg(m.fy), b.partnerHeld(), b.notOutside("a.project_id", m.outside), b.arg(ids),
		b.arg(rules.UnscheduledHandoverStatuses))
	if err := m.each(ctx, q, b.args, func(scan func(...any) error) error {
		var monitor, responsible, holder, school, status string
		var dated bool
		if err := scan(&monitor, &responsible, &holder, &school, &status, &dated); err != nil {
			return err
		}
		o := ownerOf(monitor, responsible, holder)
		if o == nil {
			return nil
		}
		if dated {
			o.PartnerScheduled++
			if slices.Contains(rules.OfficerCompletedStatuses, status) {
				o.PartnerDelivered++
			}
		} else {
			o.PartnerAwaiting++
		}
		note(o, school)
		return nil
	}); err != nil {
		return err
	}
	b = &sql{}
	q = fmt.Sprintf(`SELECT COALESCE(h.monitoring_staff_id, ''), COALESCE(h.assigning_staff_id, ''), COALESCE(s.account_owner_id, ''), COALESCE(h.school_id, '')
FROM partner_assignment h LEFT JOIN school s ON s.id = h.school_id
WHERE (h.monitoring_staff_id = ANY(%s) OR h.assigning_staff_id = ANY(%[1]s) OR s.account_owner_id = ANY(%[1]s))
AND h.status = ANY(%s) AND %s`, b.arg(ids), b.arg(rules.UnscheduledHandoverStatuses), b.notOutside("h.project_id", m.outside))
	if err := m.each(ctx, q, b.args, func(scan func(...any) error) error {
		var monitor, assigner, holder, school string
		if err := scan(&monitor, &assigner, &holder, &school); err != nil {
			return err
		}
		if o := ownerOf(monitor, assigner, holder); o != nil {
			o.PartnerAwaiting++
			note(o, school)
		}
		return nil
	}); err != nil {
		return err
	}
	for _, o := range m.allOfficers() {
		o.PartnerAssignedSchools = len(schools[o])
	}
	return nil
}

// countProjectPlaces is _count_project_places: each person's project
// ceilings put together, and the schools they added to projects.
func (m *monitor) countProjectPlaces(ctx context.Context) error {
	byID := map[string]*Officer{}
	ids := []string{}
	held := map[*Officer]map[string]*School{}
	for _, o := range m.allOfficers() {
		for _, id := range o.IDs {
			byID[id] = o
			ids = append(ids, id)
		}
		held[o] = map[string]*School{}
		for _, s := range append(slices.Clone(o.Schools), o.Outreach...) {
			s.ProjectPlaces = 0
			held[o][s.ID] = s
		}
	}
	if len(ids) == 0 {
		return nil
	}
	if err := m.each(ctx, `SELECT c.staff_id, COALESCE(sum(c.max_schools), 0) FROM project_staff_capacity c JOIN project p ON p.id = c.project_id
WHERE c.staff_id = ANY($1) AND p.deleted_at IS NULL GROUP BY 1`, []any{ids}, func(scan func(...any) error) error {
		var staff string
		var ceiling int
		if err := scan(&staff, &ceiling); err != nil {
			return err
		}
		byID[staff].ProjectCeiling += ceiling
		return nil
	}); err != nil {
		return err
	}
	return m.each(ctx, `SELECT e.assigned_staff_id, e.school_id FROM project_school_assignment e JOIN project p ON p.id = e.project_id
WHERE e.assigned_staff_id = ANY($1) AND p.deleted_at IS NULL`, []any{ids}, func(scan func(...any) error) error {
		var staff, school string
		if err := scan(&staff, &school); err != nil {
			return err
		}
		o := byID[staff]
		o.ProjectAdded++
		if s := held[o][school]; s != nil {
			s.ProjectPlaces++
		}
		return nil
	})
}
