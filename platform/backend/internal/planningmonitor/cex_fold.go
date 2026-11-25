package planningmonitor

import (
	"context"
	"sort"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cexTally is service.ExecTally: a row's figures by name.
type cexTally []int

func (t cexTally) n(name string) int { return t[cexIdx[name]] }

// share is ExecTally.share (metrics.percentage).
func (t cexTally) share(part, whole int) *int { return percentage(part, whole) }

func (t cexTally) backlog() int {
	sum := 0
	for _, o := range rules.CountryExecution.Stages.OwnerLabels {
		sum += t.n("own_" + o[0])
	}
	return sum
}

// trend is ExecTally.trend: one series' buckets.
func (t cexTally) trend(series string, buckets int) []int {
	i := 0
	for j, s := range rules.CountryExecution.TrendSeries {
		if s == series {
			i = j
		}
	}
	off := len(rules.CountryExecution.BaseFields) + i*buckets
	return t[off : off+buckets]
}

func cexSum(vectors [][]int, width int) cexTally {
	out := make(cexTally, width)
	for _, v := range vectors {
		for i, x := range v {
			out[i] += x
		}
	}
	return out
}

// cexOwnerRow is OwnerExec.
type cexOwnerRow struct {
	key, name, kind, leadKey string
	tally                    cexTally
	partners                 map[string]cexTally
}

func (o *cexOwnerRow) label() string {
	if o.kind == "pl_personal" {
		return "PL Personal Delivery"
	}
	return o.name
}

// cexLeadRow is LeadExec.
type cexLeadRow struct {
	key, name string
	tally     cexTally
	owners    []*cexOwnerRow
	noLead    bool
}

// cexTree is ExecTree.
type cexTree struct {
	country, staff, partner cexTally
	leads                   []*cexLeadRow
	partners                map[string]cexTally
}

func (f cexFilters) activeFilters() int {
	n := 0
	for _, v := range []string{f.region, f.programLead, f.cceo, f.channel, f.partner, f.activType} {
		if v != "" {
			n++
		}
	}
	return n
}

// cellKeeps is _cell_keeps.
func (f cexFilters) cellKeeps(k cexCellKey, leadOf map[string]string) bool {
	lead, ok := leadOf[k.owner]
	if !ok {
		lead = rules.CountryOversight.NoLead[0]
	}
	switch {
	case f.region != "" && k.region != f.region,
		f.cceo != "" && k.owner != f.cceo,
		f.programLead != "" && lead != f.programLead,
		f.channel != "" && k.channel != f.channel,
		f.partner != "" && k.partner != f.partner,
		f.activType != "" && k.activityType != f.activType:
		return false
	}
	return true
}

// cexRoster is the dataset's leads (system_leads) and each Lead's people
// (lead_rosters, without the Lead's own row).
type cexRoster struct {
	leads  [][2]string
	people map[string][][2]string
	ids    map[string][]string // every id each person goes by, the Lead's own included
}

func cexRosterOf(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope) (cexRoster, error) {
	m := &monitor{db: db}
	teams, err := m.roster(ctx, lensOf(scope))
	if err != nil {
		return cexRoster{}, err
	}
	out := cexRoster{people: map[string][][2]string{}, ids: map[string][]string{}}
	for _, t := range teams {
		if t.noLead {
			continue
		}
		out.leads = append(out.leads, [2]string{t.lead.Key, t.lead.Name})
		for _, p := range t.people {
			out.ids[p.key] = append([]string{p.key}, p.ids...)
			if !p.lead {
				out.people[t.lead.Key] = append(out.people[t.lead.Key], [2]string{p.key, p.name})
			}
		}
	}
	return out, nil
}

// cexFold is service.fold: the filtered cells summed up the hierarchy.
func cexFold(d *cexDataset, roster cexRoster, f cexFilters) *cexTree {
	width := d.width
	noLead, noOwner := rules.CountryOversight.NoLead, rules.CountryOversight.NoOwner
	leadOf := map[string]string{}
	for k, o := range d.owners {
		leadOf[k] = o.leadKey
	}
	byOwner, byOwnerPartner, byPartner := map[string][][]int{}, map[[2]string][][]int{}, map[string][][]int{}
	byChannel := map[string][][]int{"staff": nil, "partner": nil}
	ownerOrder, partnerOrder := []string{}, []string{}
	keys := make([]cexCellKey, 0, len(d.cells))
	for k := range d.cells {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		a, b := keys[i], keys[j]
		return strings.Join([]string{a.owner, a.partner, a.channel, a.region, a.district, a.activityType}, "|") <
			strings.Join([]string{b.owner, b.partner, b.channel, b.region, b.district, b.activityType}, "|")
	})
	for _, k := range keys {
		v := d.cells[k]
		if !f.cellKeeps(k, leadOf) {
			continue
		}
		if _, ok := byOwner[k.owner]; !ok {
			ownerOrder = append(ownerOrder, k.owner)
		}
		byOwner[k.owner] = append(byOwner[k.owner], v)
		op := [2]string{k.owner, k.partner}
		byOwnerPartner[op] = append(byOwnerPartner[op], v)
		byChannel[k.channel] = append(byChannel[k.channel], v)
		if k.partner != rules.CountryExecution.StaffKey {
			if _, ok := byPartner[k.partner]; !ok {
				partnerOrder = append(partnerOrder, k.partner)
			}
			byPartner[k.partner] = append(byPartner[k.partner], v)
		}
	}
	rows := map[string]*cexOwnerRow{}
	for _, key := range ownerOrder {
		row := &cexOwnerRow{key: key, name: noOwner[1], kind: "unassigned", leadKey: noLead[0],
			tally: cexSum(byOwner[key], width), partners: map[string]cexTally{}}
		if o := d.owners[key]; o != nil {
			row.name, row.kind, row.leadKey = o.name, ownerKind(o.key, o.role), o.leadKey
		}
		rows[key] = row
	}
	for op, vs := range byOwnerPartner {
		if row := rows[op[0]]; row != nil {
			row.partners[op[1]] = cexSum(vs, width)
		}
	}
	showRoster := f.activeFilters() == 0 || (f.activeFilters() == 1 && f.programLead != "")
	tree := &cexTree{partners: map[string]cexTally{}}
	seen := map[string]bool{}
	for _, lead := range roster.leads {
		if f.programLead != "" && lead[0] != f.programLead {
			continue
		}
		seen[lead[0]] = true
		members := []*cexOwnerRow{}
		present := map[string]bool{}
		for _, key := range ownerOrder {
			if r := rows[key]; r.leadKey == lead[0] {
				members = append(members, r)
				present[key] = true
			}
		}
		if showRoster {
			for _, p := range roster.people[lead[0]] {
				if !present[p[0]] {
					members = append(members, &cexOwnerRow{key: p[0], name: p[1], kind: "cceo", leadKey: lead[0],
						tally: make(cexTally, width), partners: map[string]cexTally{}})
				}
			}
		}
		tree.leads = append(tree.leads, cexLead(lead[0], lead[1], members, width))
	}
	orphans, orphanOrder := map[string][]*cexOwnerRow{}, []string{}
	for _, key := range ownerOrder {
		r := rows[key]
		if !seen[r.leadKey] {
			if _, ok := orphans[r.leadKey]; !ok {
				orphanOrder = append(orphanOrder, r.leadKey)
			}
			orphans[r.leadKey] = append(orphans[r.leadKey], r)
		}
	}
	for _, lk := range orphanOrder {
		if lk == noLead[0] {
			continue
		}
		name := noLead[1]
		for _, m := range orphans[lk] {
			if o := d.owners[m.key]; o != nil {
				name = o.leadName
				break
			}
		}
		tree.leads = append(tree.leads, cexLead(lk, name, orphans[lk], width))
	}
	if members, ok := orphans[noLead[0]]; ok {
		row := cexLead(noLead[0], noLead[1], members, width)
		row.noLead = true
		tree.leads = append(tree.leads, row)
	}
	vs := [][]int{}
	for _, l := range tree.leads {
		vs = append(vs, l.tally)
	}
	tree.country = cexSum(vs, width)
	for _, key := range partnerOrder {
		tree.partners[key] = cexSum(byPartner[key], width)
	}
	tree.staff, tree.partner = cexSum(byChannel["staff"], width), cexSum(byChannel["partner"], width)
	return tree
}

// cexLead is _lead: a Lead's people, PL personal first then by name.
func cexLead(key, name string, members []*cexOwnerRow, width int) *cexLeadRow {
	order := map[string]int{"pl_personal": 0, "cceo": 1, "other": 2, "unassigned": 3}
	rank := func(k string) int {
		if r, ok := order[k]; ok {
			return r
		}
		return 2
	}
	sort.SliceStable(members, func(i, j int) bool {
		if a, b := rank(members[i].kind), rank(members[j].kind); a != b {
			return a < b
		}
		return strings.ToLower(members[i].name) < strings.ToLower(members[j].name)
	})
	vs := [][]int{}
	for _, m := range members {
		vs = append(vs, m.tally)
	}
	return &cexLeadRow{key: key, name: name, tally: cexSum(vs, width), owners: members}
}

// cexSnapshot is ExecSnapshot.
type cexSnapshot struct {
	tree          *cexTree
	filters       cexFilters
	data          *cexDataset
	roster        cexRoster
	remaining     map[[2]string]int
	uniqueSchools int
	required      int
	targets       map[[2]string]int
	plan          *cpoSnapshot
	scope         schooldirectory.Scope
}

// buildCEXSnapshot is snapshot_for.
func buildCEXSnapshot(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, f cexFilters,
	today time.Time) (*cexSnapshot, error) {
	d, err := buildCEXDataset(ctx, db, scope, f.window(), today)
	if err != nil {
		return nil, err
	}
	roster, err := cexRosterOf(ctx, db, scope)
	if err != nil {
		return nil, err
	}
	s := &cexSnapshot{tree: cexFold(d, roster, f), filters: f, data: d, roster: roster, scope: scope}
	if err := s.planningPosition(ctx, db, scope, today); err != nil {
		return nil, err
	}
	schools := map[string]bool{}
	for _, r := range s.records() {
		if r.schoolID != "" && !r.cancelled {
			schools[r.schoolID] = true
		}
	}
	s.uniqueSchools = len(schools)
	return s, nil
}

// records is filtered_records.
func (s *cexSnapshot) records() []cexRecord {
	leadOf := map[string]string{}
	for k, o := range s.data.owners {
		leadOf[k] = o.leadKey
	}
	out := []cexRecord{}
	for _, r := range s.data.records {
		if s.filters.cellKeeps(cexCellKey{r.ownerKey, r.partnerKey, r.channel, r.regionID, r.districtID, r.activityType}, leadOf) {
			out = append(out, r)
		}
	}
	return out
}

// planning is ExecFilters.planning: the same selection on the planning tab.
func (f cexFilters) planning() cpoFilters {
	period := f.period
	if period == "week" {
		period = "fy"
	}
	p := cpoFilters{fy: f.fy, period: period, region: f.region, programLead: f.programLead, cceo: f.cceo, channel: f.channel,
		partner: f.partner}
	switch period {
	case "quarter":
		p.quarter = f.quarter
	case "month":
		p.month = f.month
	}
	return p
}

// planningPosition is planning_position.
func (s *cexSnapshot) planningPosition(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope,
	today time.Time) error {
	plan, err := buildCPOSnapshot(ctx, db, scope, s.filters.planning(), today)
	if err != nil {
		return err
	}
	left := func(v []int) int {
		t := cpoTally(v)
		return max(0, t.n("visit_slots")-t.n("staff_verified")-t.n("partner_verified")) + max(0, t.n("training_slots")-t.n("training_verified"))
	}
	s.plan = plan
	s.remaining = map[[2]string]int{{"country", ""}: left(plan.tree.country)}
	phased := s.filters.period != "week"
	s.targets = map[[2]string]int{}
	if phased {
		s.targets[[2]string{"country", ""}] = cpoTally(plan.tree.country).n("target")
	}
	for _, l := range plan.tree.leads {
		s.remaining[[2]string{"lead", l.key}] = left(l.tally)
		if phased {
			s.targets[[2]string{"lead", l.key}] = cpoTally(l.tally).n("target")
		}
		for _, o := range l.owners {
			s.remaining[[2]string{"owner", o.key}] = left(o.tally)
			if phased {
				s.targets[[2]string{"owner", o.key}] = cpoTally(o.tally).n("target")
			}
		}
	}
	c := cpoTally(plan.tree.country)
	s.required = c.n("visit_slots") + c.n("training_slots")
	return nil
}
