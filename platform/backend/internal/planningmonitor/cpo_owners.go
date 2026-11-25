package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"sort"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cpoOwner is requirements.OwnerInfo: the person holding a portfolio and
// where they sit.
type cpoOwner struct {
	key, name, role, userID string
	leadKey, leadName       string
	leadKeys                []string
	active                  bool
	ids                     []string
}

// ceiling is OwnerInfo.ceiling: the role's staff ceiling while active.
func (o *cpoOwner) ceiling() int {
	if o == nil || !o.active {
		return 0
	}
	return rules.CountryOversight.StaffCeilings[o.role]
}

func (o *cpoOwner) leadPersonal() bool { return o.role == rules.ProgramLeadRole }

// cpoOwnerDirectory is requirements.owner_directory: every raw owner id → the
// person, in either id space (soft-deleted People records included: a school
// held by somebody who has left is a finding), filed under the first
// Programme Lead they report to directly, by the Lead's name.
func cpoOwnerDirectory(ctx context.Context, db schooldirectory.Querier, ownerIDs []string) (map[string]*cpoOwner, error) {
	directory := map[string]*cpoOwner{}
	if len(ownerIDs) == 0 {
		return directory, nil
	}
	rows, err := db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), sp.deleted_at IS NULL, COALESCE(u.name, ''), COALESCE(u.email, ''),
  COALESCE(u.active_role, ''), COALESCE(u.roles::text[], '{}'), COALESCE(u.status, 'active'), u.deleted_at IS NULL
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) OR sp.user_id = ANY($1) ORDER BY sp.id`, ownerIDs)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the owners: %w", err)
	}
	type profile struct {
		id, userID, name, email, inUse, status string
		roles                                  []string
		live, userLive                         bool
	}
	profiles := []profile{}
	for rows.Next() {
		var p profile
		if err := rows.Scan(&p.id, &p.userID, &p.live, &p.name, &p.email, &p.inUse, &p.roles, &p.status, &p.userLive); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningmonitor: the owners: %w", err)
		}
		profiles = append(profiles, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(profiles))
	for _, p := range profiles {
		ids = append(ids, p.id)
	}
	type pair struct{ key, name string }
	leads := map[string][]pair{}
	links, err := db.Query(ctx, `
SELECT l.supervisee_id, l.supervisor_id, COALESCE(NULLIF(su.name, ''), su.email, '')
FROM staff_supervisor_assignment l JOIN staff_profile s ON s.id = l.supervisor_id JOIN "user" su ON su.id = s.user_id
WHERE l.supervisee_id = ANY($1) AND l.supervisor_id IS NOT NULL
  AND (COALESCE(su.roles::text[], '{}') && ARRAY[$2]::text[] OR su.active_role = $2)
ORDER BY su.name, l.supervisor_id`, ids, rules.ProgramLeadRole)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the owners' Leads: %w", err)
	}
	for links.Next() {
		var supervisee, supervisor, name string
		if err := links.Scan(&supervisee, &supervisor, &name); err != nil {
			links.Close()
			return nil, err
		}
		if supervisor == supervisee {
			continue
		}
		p := pair{supervisor, name}
		if !slices.Contains(leads[supervisee], p) {
			leads[supervisee] = append(leads[supervisee], p)
		}
	}
	links.Close()
	if err := links.Err(); err != nil {
		return nil, err
	}
	noLead := rules.CountryOversight.NoLead
	for _, p := range profiles {
		role := planningRole(p.roles, p.inUse)
		if role == "" {
			role = p.inUse
		}
		name := p.name
		if name == "" {
			name = p.email
		}
		if name == "" {
			name = p.id
		}
		o := &cpoOwner{key: p.id, name: name, role: role, userID: p.userID, leadKey: noLead[0], leadName: noLead[1],
			active: p.live && p.status == "active" && p.userLive, ids: []string{p.id}}
		if p.userID != "" {
			o.ids = append(o.ids, p.userID)
		}
		if role == rules.ProgramLeadRole {
			o.leadKey, o.leadName, o.leadKeys = p.id, name, []string{p.id}
		} else {
			for _, l := range leads[p.id] {
				o.leadKeys = append(o.leadKeys, l.key)
			}
			if own := leads[p.id]; len(own) > 0 && o.active {
				o.leadKey, o.leadName = own[0].key, own[0].name
			}
		}
		directory[p.id] = o
		if p.userID != "" {
			if _, ok := directory[p.userID]; !ok {
				directory[p.userID] = o
			}
		}
	}
	return directory, nil
}

// cpoAllocation is requirements.Allocation: one school's visit slots by the
// channel expected to deliver them, and the Core staff slots past the ceiling.
type cpoAllocation struct{ staff, partner, deficit int }

// annualPosition is coverage.annual_position: the school's annual staff
// claims and slot holder, for the allocation.
func annualPosition(s *cpoSchool) {
	c := rules.CountryOversight
	req := c.slots(s.family)
	var sched, pend int
	for _, p := range s.partners {
		sched += p[pSchedT]
		pend += p[pPendT]
	}
	st := s.staff[2]
	switch s.family {
	case c.CoreFamily:
		assigned := min(sched+pend, req.Partner)
		s.annualStaffClaims = min(st, req.Staff)
		switch {
		case st > 0:
			s.annualHolder = "staff"
		case assigned > 0:
			s.annualHolder = "partner"
		default:
			s.annualHolder = "open"
		}
	case c.ClientFamily:
		s.annualStaffClaims = min(st, req.Flexible)
		switch {
		case st > 0:
			s.annualHolder = "staff"
		case sched > 0 || pend > 0:
			s.annualHolder = "partner"
		default:
			s.annualHolder = "open"
		}
	default:
		s.annualStaffClaims, s.annualHolder = 0, "open"
	}
}

func codeOr(s *cpoSchool) string {
	if s.code != "" {
		return s.code
	}
	return s.id
}

// allocate is requirements.allocate: an owner's Core staff slots first and in
// full (past the ceiling a deficit, on the least-planned schools), then the
// Client schools staff hold, the open ones and those a Partner holds, as far
// as the ceiling's remainder goes; the rest are the Partner's.
func allocate(owner *cpoOwner, schools []*cpoSchool, out map[string]cpoAllocation) {
	c := rules.CountryOversight
	ceiling := owner.ceiling()
	core, client := []*cpoSchool{}, []*cpoSchool{}
	for _, s := range schools {
		switch s.family {
		case c.CoreFamily:
			core = append(core, s)
		case c.ClientFamily:
			client = append(client, s)
		default:
			out[s.id] = cpoAllocation{}
		}
	}
	perCore, perClient := c.slots(c.CoreFamily), c.slots(c.ClientFamily)
	w := workload{cap: max(0, ceiling), core: len(core), client: len(client)}
	over := w.staffCoreVisits()
	if ceiling > 0 {
		over = max(0, w.staffCoreVisits()-ceiling)
	}
	sort.SliceStable(core, func(i, j int) bool {
		if core[i].annualStaffClaims != core[j].annualStaffClaims {
			return core[i].annualStaffClaims > core[j].annualStaffClaims
		}
		return codeOr(core[i]) < codeOr(core[j])
	})
	deficits := map[string]int{}
	for i := len(core) - 1; i >= 0 && over > 0; i-- {
		take := min(over, perCore.Staff)
		deficits[core[i].id] = take
		over -= take
	}
	for _, s := range core {
		out[s.id] = cpoAllocation{staff: perCore.Staff, partner: perCore.Partner, deficit: deficits[s.id]}
	}
	order := map[string]int{"staff": 0, "open": 1, "partner": 2}
	rank := func(s *cpoSchool) int {
		if r, ok := order[s.annualHolder]; ok {
			return r
		}
		return 1
	}
	sort.SliceStable(client, func(i, j int) bool {
		if rank(client[i]) != rank(client[j]) {
			return rank(client[i]) < rank(client[j])
		}
		return codeOr(client[i]) < codeOr(client[j])
	})
	staffClient := w.staffClientVisits()
	for i, s := range client {
		if i < staffClient {
			out[s.id] = cpoAllocation{staff: perClient.Flexible}
		} else {
			out[s.id] = cpoAllocation{partner: perClient.Flexible}
		}
	}
}
