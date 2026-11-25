package planningmonitor

import (
	"math"
	"sort"
	"strings"
)

// cpoFilters is service.Filters: everything that narrows the page.
type cpoFilters struct {
	fy, period, quarter, week                                string
	month                                                    int
	region, district, programLead, cceo, schoolType, channel string
	partner, clusterStatus, planningStatus                   string
}

// activeSchoolFilters is Filters.active_school_filters.
func (f cpoFilters) activeSchoolFilters() int {
	n := 0
	for _, v := range []string{f.region, f.district, f.programLead, f.cceo, f.schoolType, f.channel, f.partner, f.clusterStatus, f.planningStatus} {
		if v != "" {
			n++
		}
	}
	return n
}

// cpoOwnerRow is hierarchy.OwnerRow.
type cpoOwnerRow struct {
	key, name, kind, role, leadKey string
	tally                          []int
	ceiling                        int
	partners                       map[string][]int
	partnerOrder                   []string
	assigned                       map[string][]int
	assignedOrder                  []string
}

// cpoLeadRow is hierarchy.LeadRow.
type cpoLeadRow struct {
	key, name string
	tally     []int
	owners    []*cpoOwnerRow
	noLead    bool
}

// cpoTree is hierarchy.Tree.
type cpoTree struct {
	country []int
	leads   []*cpoLeadRow
	window  cpoWindow
	byType  map[string][]int
}

func addInto(total, values []int) {
	for i, v := range values {
		total[i] += v
	}
}

func sumVectors(vs [][]int) []int {
	out := cpoBlank()
	for _, v := range vs {
		addInto(out, v)
	}
	return out
}

// phasedMonths is performance_engine._phased_split: an annual figure over the
// twelve FY months by the approved phasing, the total kept (largest
// remainder).
func phasedMonths(annual int) []int {
	shares := make([]float64, 12)
	for m := 1; m <= 12; m++ {
		shares[m-1] = rules.CountryOversight.Phasing[string(rune('0'+(m-1)/3+1))] / 3.0
	}
	raw := make([]float64, 12)
	base := make([]int, 12)
	sum := 0
	for i := range raw {
		raw[i] = float64(annual) * shares[i]
		base[i] = int(raw[i]) // int() truncates toward zero
		sum += base[i]
	}
	remainder := annual - sum
	order := []int{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}
	sort.SliceStable(order, func(i, j int) bool {
		return raw[order[i]]-float64(base[order[i]]) > raw[order[j]]-float64(base[order[j]])
	})
	for _, i := range order[:max(0, min(remainder, 12))] {
		base[i]++
	}
	return base
}

// phase is hierarchy.phase: a quarter's or a month's share of the
// requirement, the gaps read again against it.
func phase(values []int, w cpoWindow) []int {
	if !w.hasPhasedTarget() {
		return values
	}
	idx := cpoIdx
	g := append([]int{}, values...)
	for _, name := range rules.CountryOversight.PhasedFields {
		split := phasedMonths(values[idx[name]])
		n := 0
		for _, m := range w.monthsOfFY {
			n += split[m-1]
		}
		g[idx[name]] = n
	}
	g[idx["unallocated"]] = max(0, g[idx["visit_slots"]]-g[idx["staff"]]-g[idx["partner_assigned"]])
	g[idx["staff_gap"]] = max(0, g[idx["staff_expected"]]-g[idx["staff"]])
	g[idx["partner_gap"]] = max(0, g[idx["partner_expected"]]-g[idx["partner_assigned"]])
	g[idx["training_gap"]] = max(0, g[idx["training_slots"]]-g[idx["training"]])
	return g
}

// ownerKind is OwnerInfo.kind.
func ownerKind(key, role string) string {
	switch {
	case key == rules.CountryOversight.NoOwner[0]:
		return "unassigned"
	case role == rules.ProgramLeadRole:
		return "pl_personal"
	case role == rules.CCEORole:
		return "cceo"
	}
	return "other"
}

// planValues is service._plan_values: a person's own plan as the row's
// people fields.
func planValues(p *cpoPerson) []int {
	v := cpoBlank()
	set := func(name string, n int) { v[cpoIdx[name]] = n }
	set("p_visits", p.visitsPlanned())
	set("p_follow_up", p.visits[kindFollowUp])
	set("p_in_school", p.visits["in_school_training"])
	set("p_ssa", p.visits[rules.KindSSA])
	set("p_outreach", p.outreach)
	set("p_trainings", p.trainings)
	set("p_cluster_trainings", p.clusterTrainings)
	set("p_meetings", p.meetings)
	set("pa_work", p.partnerAssigned)
	set("pp_work", p.partnerPlanned)
	set("pa_schools", len(p.partnerSchools))
	core := p.visitsByType["core"]
	set("p_core_visits", core)
	set("p_client_visits", p.visitsPlanned()-core)
	return v
}

// ceilingFlags is service._ceiling_flags.
func ceilingFlags(v []int, ceiling int, w cpoWindow) {
	if ceiling == 0 || w.hasPhasedTarget() {
		return
	}
	if over := max(0, v[cpoIdx["p_visits"]]-ceiling); over > 0 {
		v[cpoIdx["over_cap"]] = over
		v[cpoIdx["over_cap_people"]] = 1
	}
	share := workload{cap: ceiling, core: v[cpoIdx["core_schools"]],
		client: v[cpoIdx["client_schools"]] + v[cpoIdx["core_trained_schools"]] + v[cpoIdx["core_graduate_schools"]]}
	if share.coreOnly() {
		v[cpoIdx["core_only_people"]] = 1
	}
}

// cpoRosterOwner is requirements.roster_for's OwnerInfo for a roster person.
type cpoRosterOwner struct {
	key, name, role, leadKey string
}

// foldTree is service.fold school by school (the rollup reads the same
// cells) and _tree: each person's schools and own plan, phased per person,
// filed under their Lead.
func foldTree(d *cpoDataset, f cpoFilters, people []*cpoTeam, roster []cpoRosterOwner, leads [][2]string) *cpoTree {
	w := d.window
	c := rules.CountryOversight
	ownerValues := map[string][]int{}
	typeValues := map[[2]string][]int{}
	partnerValues := map[[2]string][]int{}
	partnerSeen := map[string][]string{}
	unmapped := 0
	var only *string
	if f.partner != "" {
		only = &f.partner
	}
	for _, s := range d.schools {
		owner := d.owners[s.ownerKey]
		leadKey := c.NoLead[0]
		if owner != nil {
			leadKey = owner.leadKey
		}
		if !keepsPlace(f, s, leadKey) {
			continue
		}
		if !s.governed() {
			unmapped++
			continue
		}
		cl := d.claims[s.id]
		values := d.vectors[s.id]
		if f.channel != "" || only != nil {
			cl = claimsFor(s, d.allocations[s.id], w, f.channel, only)
			values = schoolValues(s, cl)
		}
		if !statusMatches(cl, f) {
			continue
		}
		if ownerValues[s.ownerKey] == nil {
			ownerValues[s.ownerKey] = cpoBlank()
		}
		addInto(ownerValues[s.ownerKey], values)
		tk := [2]string{s.ownerKey, s.schoolType}
		if typeValues[tk] == nil {
			typeValues[tk] = cpoBlank()
		}
		addInto(typeValues[tk], values)
		involved := []string{}
		for _, pid := range s.partnerOrder {
			if only == nil || pid == *only {
				involved = append(involved, pid)
			}
		}
		add := func(pid string, v []int) {
			k := [2]string{s.ownerKey, pid}
			if partnerValues[k] == nil {
				partnerValues[k] = cpoBlank()
				partnerSeen[s.ownerKey] = append(partnerSeen[s.ownerKey], pid)
			}
			addInto(partnerValues[k], v)
		}
		if len(involved) > 0 && f.channel != "staff" {
			for _, pid := range involved {
				share, ok := cl.byPartner[pid]
				if !ok {
					share = [4]int{0, 0, 0, s.partners[pid][pReturned]}
				}
				add(pid, partnerVector(values, share))
			}
		} else {
			add("__staff__", values)
		}
	}
	plans := map[string]*cpoPerson{}
	for _, t := range people {
		for _, p := range t.people {
			plans[p.key] = p
		}
	}
	rosterBy := map[string]cpoRosterOwner{}
	for _, r := range roster {
		rosterBy[r.key] = r
	}
	showRoster := f.activeSchoolFilters() == 0 || (f.activeSchoolFilters() == 1 && f.programLead != "")
	keys := map[string]bool{}
	for k := range ownerValues {
		keys[k] = true
	}
	for k, p := range plans {
		if p.hasAnything() {
			keys[k] = true
		}
	}
	if showRoster {
		for k := range rosterBy {
			keys[k] = true
		}
	}
	rows := map[string]*cpoOwnerRow{}
	for key := range keys {
		person := plans[key]
		var name, kind, role, leadKey string
		ceiling := 0
		if o := d.owners[key]; o != nil {
			name, kind, role, leadKey, ceiling = o.name, ownerKind(o.key, o.role), o.role, o.leadKey, o.ceiling()
		} else if r, ok := rosterBy[key]; ok {
			name, kind, role, leadKey = r.name, ownerKind(r.key, r.role), r.role, r.leadKey
			ceiling = c.StaffCeilings[r.role]
		} else if person == nil {
			name, kind, leadKey = c.NoOwner[1], "unassigned", c.NoLead[0]
		} else {
			name, leadKey = person.name, c.NoLead[0]
			kind = "other"
			if strings.HasPrefix(key, "__") {
				kind = "unassigned"
			}
		}
		if f.programLead != "" && leadKey != f.programLead {
			continue
		}
		if f.cceo != "" && key != f.cceo {
			continue
		}
		values := cpoBlank()
		if v := ownerValues[key]; v != nil {
			copy(values, v)
		}
		if person != nil {
			pv := planValues(person)
			for _, name := range rules.CountryOversight.PeopleFields {
				values[cpoIdx[name]] += pv[cpoIdx[name]]
			}
		}
		values[cpoIdx["target"]] = ceiling
		ceilingFlags(values, ceiling, w)
		row := &cpoOwnerRow{key: key, name: name, kind: kind, role: role, leadKey: leadKey, tally: phase(values, w), ceiling: ceiling,
			partners: map[string][]int{}, assigned: map[string][]int{}}
		if person != nil {
			for _, pid := range person.partnerOrder {
				h := person.byPartner[pid]
				hands := cpoBlank()
				hands[cpoIdx["pa_work"]], hands[cpoIdx["pp_work"]], hands[cpoIdx["pa_schools"]] = h.assigned, h.planned, len(h.schools)
				row.assigned[pid] = hands
				row.assignedOrder = append(row.assignedOrder, pid)
			}
		}
		rows[key] = row
	}
	for owner, pids := range partnerSeen {
		row := rows[owner]
		if row == nil {
			continue
		}
		for _, pid := range pids {
			row.partners[pid] = phase(partnerValues[[2]string{owner, pid}], w)
			row.partnerOrder = append(row.partnerOrder, pid)
		}
	}
	t := &cpoTree{window: w, byType: map[string][]int{}}
	seen := map[string]bool{}
	for _, l := range leads {
		if f.programLead != "" && l[0] != f.programLead {
			continue
		}
		seen[l[0]] = true
		t.leads = append(t.leads, leadRow(l[0], l[1], membersOf(rows, l[0])))
	}
	orphans := map[string][]*cpoOwnerRow{}
	orphanOrder := []string{}
	for _, r := range sortedRows(rows) {
		if !seen[r.leadKey] {
			if _, ok := orphans[r.leadKey]; !ok {
				orphanOrder = append(orphanOrder, r.leadKey)
			}
			orphans[r.leadKey] = append(orphans[r.leadKey], r)
		}
	}
	for _, key := range orphanOrder {
		if key == c.NoLead[0] {
			continue
		}
		name := c.NoLead[1]
		for _, m := range orphans[key] {
			if o := d.owners[m.key]; o != nil {
				name = o.leadName
				break
			}
		}
		t.leads = append(t.leads, leadRow(key, name, orphans[key]))
	}
	if members, ok := orphans[c.NoLead[0]]; ok {
		l := leadRow(c.NoLead[0], c.NoLead[1], members)
		l.noLead = true
		t.leads = append(t.leads, l)
	}
	all := [][]int{}
	for _, l := range t.leads {
		all = append(all, l.tally)
	}
	t.country = sumVectors(all)
	t.country[cpoIdx["unmapped_schools"]] += unmapped
	for k, v := range typeValues {
		if rows[k[0]] != nil {
			if t.byType[k[1]] == nil {
				t.byType[k[1]] = cpoBlank()
			}
			addInto(t.byType[k[1]], phase(v, w))
		}
	}
	return t
}

// sortedRows is the rows in a stable order (Python's dict order is the
// order owners were first met; only the orphan Leads' order reads it).
func sortedRows(rows map[string]*cpoOwnerRow) []*cpoOwnerRow {
	out := make([]*cpoOwnerRow, 0, len(rows))
	for _, r := range rows {
		out = append(out, r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].key < out[j].key })
	return out
}

func membersOf(rows map[string]*cpoOwnerRow, lead string) []*cpoOwnerRow {
	out := []*cpoOwnerRow{}
	for _, r := range sortedRows(rows) {
		if r.leadKey == lead {
			out = append(out, r)
		}
	}
	return out
}

// leadRow is service._lead_row: the Lead's own row first, then the CCEOs by
// name, the total their sum.
func leadRow(key, name string, members []*cpoOwnerRow) *cpoLeadRow {
	order := map[string]int{"pl_personal": 0, "cceo": 1, "other": 2, "unassigned": 3}
	rank := func(r *cpoOwnerRow) int {
		if n, ok := order[r.kind]; ok {
			return n
		}
		return 2
	}
	sort.SliceStable(members, func(i, j int) bool {
		if rank(members[i]) != rank(members[j]) {
			return rank(members[i]) < rank(members[j])
		}
		return strings.ToLower(members[i].name) < strings.ToLower(members[j].name)
	})
	vs := [][]int{}
	for _, m := range members {
		vs = append(vs, m.tally)
	}
	return &cpoLeadRow{key: key, name: name, tally: sumVectors(vs), owners: members}
}

// keepsPlace is service._keeps (_keeps_place and the one-Partner filter).
func keepsPlace(f cpoFilters, s *cpoSchool, leadKey string) bool {
	if f.partner != "" {
		if _, ok := s.partners[f.partner]; !ok {
			return false
		}
	}
	switch {
	case f.region != "" && s.regionID != f.region,
		f.district != "" && s.districtID != f.district,
		f.schoolType != "" && s.schoolType != f.schoolType,
		f.clusterStatus == "clustered" && !s.clustered(),
		f.clusterStatus == "unclustered" && s.clustered(),
		f.cceo != "" && s.ownerKey != f.cceo,
		f.programLead != "" && leadKey != f.programLead:
		return false
	}
	return true
}

// statusMatches is service._status_matches.
func statusMatches(cl cpoClaims, f cpoFilters) bool {
	switch f.planningStatus {
	case "":
		return true
	case "awaiting":
		return cl.cumPartnerAssigned > cl.cumPartnerScheduled
	}
	return planningState(cl) == f.planningStatus
}

// partnerVector is service._partner_values: a school's vector with the
// Partner claims one Partner holds.
func partnerVector(values []int, share [4]int) []int {
	v := append([]int{}, values...)
	assigned, scheduled, verified, returned := share[0], share[1], share[2], share[3]
	core := values[cpoIdx["core_schools"]] == 1
	v[cpoIdx["partner_assigned"]], v[cpoIdx["partner_scheduled"]] = assigned, scheduled
	v[cpoIdx["partner_verified"]], v[cpoIdx["returned"]] = verified, returned
	if core {
		v[cpoIdx["partner_core_assigned"]], v[cpoIdx["partner_core_scheduled"]] = assigned, scheduled
		v[cpoIdx["partner_client_assigned"]], v[cpoIdx["partner_client_scheduled"]] = 0, 0
	} else {
		v[cpoIdx["partner_core_assigned"]], v[cpoIdx["partner_core_scheduled"]] = 0, 0
		v[cpoIdx["partner_client_assigned"]], v[cpoIdx["partner_client_scheduled"]] = assigned, scheduled
	}
	return v
}

// share is Tally.share: round(100 × part / whole), half to even, or none.
func share(part, whole int) (int, bool) {
	if whole == 0 {
		return 0, false
	}
	return int(math.RoundToEven(100 * float64(part) / float64(whole))), true
}
