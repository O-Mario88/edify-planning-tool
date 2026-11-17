package targetdistribution

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The allocation methods (MilestoneAllocationMethod).
const (
	fieldCascade = "field_cascade"
	specialist   = "specialist"
	countryOwned = "country_owned"
	nonScoreable = "non_scoreable"
)

// priority is one country priority of the master. A priority without a
// code is drawn with the template's "None" and matches no group filter.
type priority struct {
	id, code, title, status string
	hasCode                 bool
	sequence                int
	rows                    []*row
}

// row is one milestone of the master as the view reads it
// (country_distribution_workspace's milestone rows).
type row struct {
	priority                                               *priority
	id, title, unit, method, role, measurement, sourceText string
	target, core, client                                   *big.Rat
	needsConfirmation                                      bool
	activity                                               string
	state                                                  *reconciliation
	progress                                               *holderProgress
	plan                                                   *allocations.Progress
	status                                                 string
	remaining                                              *big.Rat
}

// allocation is a live (not rejected or superseded) allocation of a milestone.
type allocation struct {
	id, kind, status, quarterStatus, team, employee, project string
	parent                                                   bool
	allocated, core, client                                  *big.Rat
	split                                                    map[string]*big.Rat
}

// component is one of a milestone's target components.
type component struct {
	code   string
	target *big.Rat
}

// reconciliation is _reconcile_rows over a milestone's Programme Lead rows.
type reconciliation struct {
	rows                   []allocation
	allocated, unallocated *big.Rat
	summable, balanced     bool
	errors                 int
}

// holderProgress is _milestone_progress: the approved allocations' roll-up.
type holderProgress struct {
	summable                  bool
	plan, actual              *big.Rat
	pct                       *float64
	holders, quartersAchieved int
}

// kpis are the workspace's figures.
type kpis struct {
	milestones, groups, needsConfirmation, fieldCascade, balanced, locked int
	tracking, delivering                                                  int
	total, distributable, countryProject, core, client, allocated, left   *big.Rat
	verifiedPlan, verifiedActual                                          *big.Rat
}

// workspace is country_distribution_workspace(fy).
type workspace struct {
	fy        string
	groups    []*priority
	k         kpis
	published bool
	plan      map[string]*allocations.Progress
}

func zero() *big.Rat { return new(big.Rat) }

// cents is _q2: the figure (nothing is 0) to the cent, half to even.
func cents(r *big.Rat) *big.Rat {
	if r == nil {
		return zero()
	}
	scaled := new(big.Rat).Mul(r, big.NewRat(100, 1))
	q, m := new(big.Int).QuoRem(scaled.Num(), scaled.Denom(), new(big.Int))
	twice := new(big.Int).Mul(new(big.Int).Abs(m), big.NewInt(2))
	switch c := twice.Cmp(scaled.Denom()); {
	case c > 0, c == 0 && q.Bit(0) == 1:
		if scaled.Sign() < 0 {
			q.Sub(q, big.NewInt(1))
		} else {
			q.Add(q, big.NewInt(1))
		}
	}
	return new(big.Rat).SetFrac(q, big.NewInt(100))
}

// pyRound1 is Python's round(float(x), 1).
func pyRound1(x *big.Rat) float64 {
	f, _ := x.Float64()
	r, _ := strconv.ParseFloat(strconv.FormatFloat(f, 'f', 1, 64), 64)
	return r
}

func add(a, b *big.Rat) *big.Rat { return new(big.Rat).Add(a, b) }
func sub(a, b *big.Rat) *big.Rat { return new(big.Rat).Sub(a, b) }

func (r *row) summable() bool { return slices.Contains(rules.Summable, r.measurement) }

// readWorkspace is country_distribution_workspace for the master of fy, or
// nil when the year has no master.
func readWorkspace(ctx context.Context, db schooldirectory.Querier, fy string, today time.Time) (*workspace, error) {
	ws := &workspace{fy: fy, k: kpis{total: zero(), distributable: zero(), countryProject: zero(), core: zero(),
		client: zero(), allocated: zero(), left: zero(), verifiedPlan: zero(), verifiedActual: zero()}}
	if err := ws.readPriorities(ctx, db); err != nil || len(ws.groups) == 0 {
		return nil, err
	}
	rows, ids := []*row{}, []string{}
	for _, g := range ws.groups {
		for _, r := range g.rows {
			rows = append(rows, r)
			ids = append(ids, r.id)
		}
	}
	if err := readActivities(ctx, db, rows, ids); err != nil {
		return nil, err
	}
	components, err := readComponents(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	allocs, err := readAllocations(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	targets := map[string]*big.Rat{}
	for _, r := range rows {
		targets[r.id] = r.target
	}
	if ws.plan, err = allocations.MasterPlanProgress(ctx, db, ids, fy, targets, today); err != nil {
		return nil, err
	}
	ws.published = true
	for _, g := range ws.groups {
		ws.published = ws.published && g.status == rules.Published
	}
	ws.k.groups = len(ws.groups)
	for _, r := range rows {
		r.plan = ws.plan[r.id]
		if err := ws.measure(ctx, db, r, allocs[r.id], components[r.id]); err != nil {
			return nil, err
		}
	}
	for _, r := range rows {
		ws.statusOf(r)
	}
	return ws, nil
}

func (ws *workspace) readPriorities(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `
SELECT id, coalesce(code, 'None'), code IS NOT NULL, title, status, sequence FROM hr_strategic_priority
WHERE fy = $1 AND level = 'country' AND country_id = $2 AND cycle_id IS NOT NULL
ORDER BY sequence, title`, ws.fy, country)
	if err != nil {
		return fmt.Errorf("targetdistribution: reading the master's priorities: %w", err)
	}
	byID := map[string]*priority{}
	for rows.Next() {
		p := &priority{}
		if err := rows.Scan(&p.id, &p.code, &p.hasCode, &p.title, &p.status, &p.sequence); err != nil {
			rows.Close()
			return fmt.Errorf("targetdistribution: reading a priority: %w", err)
		}
		ws.groups = append(ws.groups, p)
		byID[p.id] = p
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(ws.groups) == 0 {
		return err
	}
	ids := []string{}
	for _, p := range ws.groups {
		ids = append(ids, p.id)
	}
	// priority.milestones.all(): PriorityMilestone's ordering, the priority's
	// own (level, sequence, title) and then the source order.
	mrows, err := db.Query(ctx, `
SELECT m.id, m.priority_id, m.title, coalesce(m.target_unit, ''), coalesce(m.allocation_method, ''),
       coalesce(m.responsible_role, ''), coalesce(m.measurement_type, ''), coalesce(m.source_text, ''),
       m.target_value::text, m.core_target::text, m.client_target::text, m.needs_confirmation
FROM hr_priority_milestone m JOIN hr_strategic_priority sp ON sp.id = m.priority_id
WHERE m.priority_id = ANY($1)
ORDER BY sp.level, sp.sequence, sp.title, m.source_order`, ids)
	if err != nil {
		return fmt.Errorf("targetdistribution: reading the master's milestones: %w", err)
	}
	defer mrows.Close()
	for mrows.Next() {
		r := &row{}
		var pid string
		var target, core, client *string
		if err := mrows.Scan(&r.id, &pid, &r.title, &r.unit, &r.method, &r.role, &r.measurement, &r.sourceText,
			&target, &core, &client, &r.needsConfirmation); err != nil {
			return fmt.Errorf("targetdistribution: reading a milestone: %w", err)
		}
		r.target, r.core, r.client = ratOf(target), ratOf(core), ratOf(client)
		r.priority = byID[pid]
		r.priority.rows = append(r.priority.rows, r)
	}
	return mrows.Err()
}

func ratOf(s *string) *big.Rat {
	if s == nil {
		return nil
	}
	r, ok := new(big.Rat).SetString(*s)
	if !ok {
		return nil
	}
	return r
}

// readActivities is each milestone's activityDisplay: its rules' catalogue
// names, in the order the rules come, once each; else its title. The
// rules carry no order of their own, so they are read as the existing
// prefetch reads them.
func readActivities(ctx context.Context, db schooldirectory.Querier, rows []*row, ids []string) error {
	rs, err := db.Query(ctx, `SELECT milestone_id, catalogue_item_id FROM hr_milestone_activity_rule WHERE milestone_id = ANY($1)`, ids)
	if err != nil {
		return fmt.Errorf("targetdistribution: reading the activity rules: %w", err)
	}
	type rule struct{ milestone, item string }
	list, items := []rule{}, []string{}
	for rs.Next() {
		var r rule
		var item *string
		if err := rs.Scan(&r.milestone, &item); err != nil {
			rs.Close()
			return fmt.Errorf("targetdistribution: reading an activity rule: %w", err)
		}
		if item != nil {
			r.item = *item
			items = append(items, *item)
		}
		list = append(list, r)
	}
	rs.Close()
	if err := rs.Err(); err != nil {
		return fmt.Errorf("targetdistribution: reading the activity rules: %w", err)
	}
	names := map[string]string{}
	ns, err := db.Query(ctx, `SELECT id, coalesce(display_name, '') FROM activity_catalogue_item WHERE id = ANY($1)`, items)
	if err != nil {
		return fmt.Errorf("targetdistribution: reading the catalogue: %w", err)
	}
	for ns.Next() {
		var id, name string
		if err := ns.Scan(&id, &name); err != nil {
			ns.Close()
			return fmt.Errorf("targetdistribution: reading a catalogue item: %w", err)
		}
		names[id] = name
	}
	ns.Close()
	if err := ns.Err(); err != nil {
		return fmt.Errorf("targetdistribution: reading the catalogue: %w", err)
	}
	byMilestone := map[string][]string{}
	for _, r := range list {
		name := names[r.item]
		if name != "" && !slices.Contains(byMilestone[r.milestone], name) {
			byMilestone[r.milestone] = append(byMilestone[r.milestone], name)
		}
	}
	for _, r := range rows {
		r.activity = strings.Join(byMilestone[r.id], ", ")
		if r.activity == "" {
			r.activity = r.title
		}
	}
	return nil
}

func readComponents(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string][]component, error) {
	rows, err := db.Query(ctx, `SELECT milestone_id, code, target_value::text FROM hr_milestone_target_component WHERE milestone_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("targetdistribution: reading the target components: %w", err)
	}
	defer rows.Close()
	out := map[string][]component{}
	for rows.Next() {
		var mid string
		var c component
		var target *string
		if err := rows.Scan(&mid, &c.code, &target); err != nil {
			return nil, fmt.Errorf("targetdistribution: reading a target component: %w", err)
		}
		c.target = ratOf(target)
		out[mid] = append(out[mid], c)
	}
	return out, rows.Err()
}

func readAllocations(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string][]allocation, error) {
	rows, err := db.Query(ctx, `
SELECT id, milestone_id, coalesce(allocated_to_type, ''), coalesce(status, ''), coalesce(quarter_status, ''),
       coalesce(team_id, ''), coalesce(employee_id, ''), coalesce(project_id, ''), parent_id IS NOT NULL,
       allocated_target::text, core_target::text, client_target::text, coalesce(component_split::text, '')
FROM hr_milestone_allocation
WHERE milestone_id = ANY($1) AND status NOT IN ('rejected', 'superseded')`, ids)
	if err != nil {
		return nil, fmt.Errorf("targetdistribution: reading the allocations: %w", err)
	}
	defer rows.Close()
	out := map[string][]allocation{}
	for rows.Next() {
		var a allocation
		var mid, split string
		var allocated, core, client *string
		if err := rows.Scan(&a.id, &mid, &a.kind, &a.status, &a.quarterStatus, &a.team, &a.employee, &a.project, &a.parent,
			&allocated, &core, &client, &split); err != nil {
			return nil, fmt.Errorf("targetdistribution: reading an allocation: %w", err)
		}
		a.allocated, a.core, a.client = ratOf(allocated), ratOf(core), ratOf(client)
		if a.split, err = splitOf(split); err != nil {
			return nil, err
		}
		out[mid] = append(out[mid], a)
	}
	return out, rows.Err()
}

// splitOf is a component split's figures by component code.
func splitOf(raw string) (map[string]*big.Rat, error) {
	out := map[string]*big.Rat{}
	if raw == "" || raw == "null" {
		return out, nil
	}
	var values map[string]json.RawMessage
	if err := json.Unmarshal([]byte(raw), &values); err != nil {
		return nil, fmt.Errorf("%w: a component split that is not an object", errPassOn)
	}
	for code, v := range values {
		text := strings.Trim(string(v), `"`)
		if text == "null" {
			continue
		}
		r, ok := new(big.Rat).SetString(text)
		if !ok {
			return nil, fmt.Errorf("%w: a component split figure %s", errPassOn, v)
		}
		out[code] = r
	}
	return out, nil
}

// measure is one milestone's turn of country_distribution_workspace's loop:
// its reconciliation, its figures in the KPIs and its holders' progress.
func (ws *workspace) measure(ctx context.Context, db schooldirectory.Querier, r *row, allocs []allocation, components []component) error {
	team := []allocation{}
	approved := []allocation{}
	for _, a := range allocs {
		if a.kind == "team" && !a.parent {
			team = append(team, a)
		}
		if a.status == "approved" {
			approved = append(approved, a)
		}
	}
	if r.method == fieldCascade {
		r.state = reconcile(r, team, components)
	}
	k := &ws.k
	k.milestones++
	if r.needsConfirmation {
		k.needsConfirmation++
	}
	if r.method == fieldCascade {
		k.fieldCascade++
		if r.state.balanced {
			k.balanced++
		}
	}
	if r.summable() && r.target != nil {
		target := cents(r.target)
		k.total = add(k.total, target)
		k.core = add(k.core, cents(r.core))
		k.client = add(k.client, cents(r.client))
		switch r.method {
		case fieldCascade:
			allocated := zero()
			if r.state.allocated != nil {
				allocated = r.state.allocated
			}
			k.distributable = add(k.distributable, target)
			k.allocated = add(k.allocated, allocated)
			k.left = add(k.left, sub(target, allocated))
		case specialist, countryOwned:
			k.countryProject = add(k.countryProject, target)
		}
	}
	p, err := holderRollup(ctx, db, r, approved)
	if err != nil {
		return err
	}
	r.progress = p
	if p != nil {
		k.tracking++
		if p.summable {
			k.verifiedPlan = add(k.verifiedPlan, p.plan)
			k.verifiedActual = add(k.verifiedActual, p.actual)
			if p.actual.Sign() > 0 {
				k.delivering++
			}
		} else if p.quartersAchieved > 0 {
			k.delivering++
		}
	}
	return nil
}

// reconcile is _reconcile_rows at the Programme Lead level.
func reconcile(r *row, rows []allocation, components []component) *reconciliation {
	expected := cents(r.target)
	st := &reconciliation{rows: rows, summable: r.summable()}
	if st.summable {
		allocated := zero()
		for _, a := range rows {
			allocated = add(allocated, cents(a.allocated))
		}
		st.allocated, st.unallocated = allocated, sub(expected, allocated)
		if st.unallocated.Sign() != 0 {
			st.errors++
		}
		for _, col := range []struct {
			expected *big.Rat
			of       func(allocation) *big.Rat
		}{{r.core, func(a allocation) *big.Rat { return a.core }}, {r.client, func(a allocation) *big.Rat { return a.client }}} {
			if col.expected == nil {
				continue
			}
			total := zero()
			for _, a := range rows {
				total = add(total, cents(col.of(a)))
			}
			if total.Cmp(cents(col.expected)) != 0 {
				st.errors++
			}
		}
		anySplit := false
		for _, a := range rows {
			anySplit = anySplit || len(a.split) > 0
		}
		if len(components) > 0 && (len(rows) > 1 || anySplit) {
			for _, c := range components {
				total := zero()
				for _, a := range rows {
					total = add(total, cents(a.split[c.code]))
				}
				if total.Cmp(cents(c.target)) != 0 {
					st.errors++
				}
			}
		}
	} else {
		for _, a := range rows {
			if cents(a.allocated).Cmp(expected) != 0 {
				st.errors++
			}
		}
	}
	st.balanced = st.errors == 0 && len(rows) > 0
	return st
}

// holderRollup is _milestone_progress over the approved allocations.
func holderRollup(ctx context.Context, db schooldirectory.Querier, r *row, approved []allocation) (*holderProgress, error) {
	if len(approved) == 0 {
		return nil, nil
	}
	ids := []string{}
	for _, a := range approved {
		ids = append(ids, a.id)
	}
	periods, err := db.Query(ctx, `
SELECT allocation_id, period_type, coalesce(planned_value, 0)::text, period_start, period_end, coalesce(achievement_percentage, 0)::text
FROM hr_milestone_period_target WHERE allocation_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("targetdistribution: reading the period targets: %w", err)
	}
	type span struct {
		start, end time.Time
		plan       *big.Rat
		any        bool
	}
	months := map[string]*span{}
	achieved := 0
	for periods.Next() {
		var id, kind, planned, achievement string
		var start, end time.Time
		if err := periods.Scan(&id, &kind, &planned, &start, &end, &achievement); err != nil {
			periods.Close()
			return nil, fmt.Errorf("targetdistribution: reading a period target: %w", err)
		}
		switch kind {
		case "quarter":
			if a, _ := new(big.Rat).SetString(achievement); a != nil && a.Cmp(big.NewRat(100, 1)) >= 0 {
				achieved++
			}
		case "month":
			s := months[id]
			if s == nil {
				s = &span{start: start, end: end, plan: zero()}
				months[id] = s
			}
			if start.Before(s.start) {
				s.start = start
			}
			if end.After(s.end) {
				s.end = end
			}
			p, _ := new(big.Rat).SetString(planned)
			s.plan = add(s.plan, p)
			s.any = true
		}
	}
	periods.Close()
	if err := periods.Err(); err != nil {
		return nil, fmt.Errorf("targetdistribution: reading the period targets: %w", err)
	}
	if !r.summable() {
		return &holderProgress{holders: len(approved), quartersAchieved: achieved}, nil
	}
	p := &holderProgress{summable: true, plan: zero(), actual: zero()}
	for _, a := range approved {
		s := months[a.id]
		if s == nil || !s.any {
			continue
		}
		p.plan = add(p.plan, s.plan)
		var holder string
		team := false
		switch {
		case a.kind == "team" && a.team != "":
			holder, team = a.team, true
		case a.kind == "employee" && a.employee != "":
			holder = a.employee
		default:
			// A Project's or the country's allocation reads another scope.
			return nil, fmt.Errorf("%w: an approved %s allocation", errPassOn, a.kind)
		}
		actual, err := allocations.HolderActual(ctx, db, r.id, holder, team, s.start, s.end)
		if err != nil {
			return nil, err
		}
		p.actual = add(p.actual, actual.Rat())
	}
	if p.plan.Sign() != 0 {
		pct := pyRound1(new(big.Rat).Mul(new(big.Rat).Quo(p.actual, p.plan), big.NewRat(100, 1)))
		p.pct = &pct
	}
	return p, nil
}

// statusOf is the workspace's second pass: each milestone's status and the
// balance the table shows.
func (ws *workspace) statusOf(r *row) {
	st := r.state
	switch {
	case r.needsConfirmation:
		r.status = "Needs confirmation"
	case !ws.published:
		r.status = "Draft"
	case r.method == fieldCascade:
		allApproved := true
		for _, a := range st.rows {
			allApproved = allApproved && a.status == "approved"
		}
		switch {
		case st.balanced && allApproved:
			r.status = "Distributed"
			ws.k.locked++
		case st.balanced:
			r.status = "Ready to approve"
		case len(st.rows) > 0:
			r.status = "Balance open"
		default:
			r.status = "Published"
		}
	case r.method == nonScoreable:
		r.status = "Non-scoreable"
	default:
		r.status = "Published"
	}
	if st != nil && st.summable {
		r.remaining = st.unallocated
	}
}
