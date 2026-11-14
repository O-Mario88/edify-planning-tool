package teamperformance

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// scope is targets.Scope: the country, a lead's team, or one officer.
type scope struct {
	kind  string // country | region | officer
	lead  string
	staff map[string]bool
}

func countryScope() scope { return scope{kind: "country"} }

func regionScope(lead string, staff map[string]bool) scope {
	if staff == nil {
		staff = map[string]bool{}
	}
	return scope{kind: "region", lead: lead, staff: staff}
}

func officerScope(id string) scope {
	return scope{kind: "officer", lead: id, staff: map[string]bool{id: true}}
}

// months is a target's monthly phasing, in the order its months were met
// (a dict's insertion order, which the sums follow).
type months struct {
	order []int
	by    map[int]float64
}

func (m *months) Add(month int, v float64) {
	if m.by == nil {
		m.by = map[int]float64{}
	}
	if _, ok := m.by[month]; !ok {
		m.order = append(m.order, month)
	}
	m.by[month] = float64(m.by[month] + v)
}

func (m *months) set(month int, v float64) {
	if m.by == nil {
		m.by = map[int]float64{}
	}
	if _, ok := m.by[month]; !ok {
		m.order = append(m.order, month)
	}
	m.by[month] = v
}

// target is targets.Target.
type target struct {
	annual *float64
	source string
	months *months
	rate   *float64
}

func (t target) month(m int) *float64 {
	if t.months == nil {
		return nil
	}
	return ptr(t.months.by[m])
}

func (t target) over(ms []int) *float64 {
	if t.months == nil || len(ms) == 0 {
		return nil
	}
	values := []float64{}
	for _, m := range ms {
		values = append(values, t.months.by[m])
	}
	return ptr(pySumFrom0(values))
}

func (t target) through(month int) *float64 {
	if t.months == nil {
		return nil
	}
	values := []float64{}
	for _, m := range t.months.order {
		if m <= month {
			values = append(values, t.months.by[m])
		}
	}
	return ptr(pySumFrom0(values))
}

// pySumFrom0 is sum() of floats from its integer start.
func pySumFrom0(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	return schooldirectory.PySum(values)
}

type milestone struct {
	id, code, measurement string
	value, core, client   *float64
}

type allocation struct {
	id, kind, team, employee, milestone string
	allocated, core, client             *float64
}

type countryTarget struct {
	annual float64
	months *months
	source string
}

// targetBook is targets.TargetBook.
type targetBook struct {
	fy      string
	byCode  map[string]*milestone
	codes   map[string]string
	country map[string]countryTarget
	team    map[[2]string]*allocation
	staff   map[[2]string]*allocation
	teamsOf map[string][]*allocation
	staffOf map[string][]*allocation
	phasing map[string]*months
}

func parseNum(text *string) *float64 {
	if text == nil {
		return nil
	}
	v, err := strconv.ParseFloat(*text, 64)
	if err != nil {
		return nil
	}
	return &v
}

func loadTargets(ctx context.Context, db schooldirectory.Querier, fy string) (*targetBook, error) {
	b := &targetBook{fy: fy, byCode: map[string]*milestone{}, codes: map[string]string{}, country: map[string]countryTarget{},
		team: map[[2]string]*allocation{}, staff: map[[2]string]*allocation{}, teamsOf: map[string][]*allocation{},
		staffOf: map[string][]*allocation{}, phasing: map[string]*months{}}
	if err := b.loadCountry(ctx, db); err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT id FROM hr_strategic_priority WHERE country_id = $1 AND cycle_id IS NOT NULL AND fy = $2 AND level = 'country'
		ORDER BY sequence ASC, title ASC`, rules.CountryID, fy)
	if err != nil {
		return nil, fmt.Errorf("teamperformance: priorities: %w", err)
	}
	priorities := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		priorities = append(priorities, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	ids := []string{}
	if len(priorities) > 0 {
		rows, err = db.Query(ctx, `SELECT m.id, m.priority_id, COALESCE(m.code, ''), COALESCE(m.measurement_type, ''),
			m.target_value::text, m.core_target::text, m.client_target::text
			FROM hr_priority_milestone m JOIN hr_strategic_priority p ON m.priority_id = p.id
			WHERE m.priority_id = ANY($1::varchar[]) ORDER BY p.level ASC, p.sequence ASC, p.title ASC, m.source_order ASC`, priorities)
		if err != nil {
			return nil, fmt.Errorf("teamperformance: milestones: %w", err)
		}
		of := map[string][]*milestone{}
		for rows.Next() {
			var m milestone
			var priority string
			var value, core, client *string
			if err := rows.Scan(&m.id, &priority, &m.code, &m.measurement, &value, &core, &client); err != nil {
				rows.Close()
				return nil, err
			}
			m.value, m.core, m.client = parseNum(value), parseNum(core), parseNum(client)
			of[priority] = append(of[priority], &m)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		for _, p := range priorities {
			for _, m := range of[p] {
				ids = append(ids, m.id)
				b.codes[m.id] = m.code
				if _, ok := b.byCode[m.code]; !ok {
					b.byCode[m.code] = m
				}
			}
		}
	}
	if len(ids) == 0 {
		return b, nil
	}
	rows, err = db.Query(ctx, `SELECT id, COALESCE(allocated_to_type, ''), COALESCE(team_id, ''), COALESCE(employee_id, ''), milestone_id,
		allocated_target::text, core_target::text, client_target::text
		FROM hr_milestone_allocation WHERE milestone_id = ANY($1::varchar[]) AND status = 'approved'`, ids)
	if err != nil {
		return nil, fmt.Errorf("teamperformance: allocations: %w", err)
	}
	for rows.Next() {
		var a allocation
		var allocated, core, client *string
		if err := rows.Scan(&a.id, &a.kind, &a.team, &a.employee, &a.milestone, &allocated, &core, &client); err != nil {
			rows.Close()
			return nil, err
		}
		a.allocated, a.core, a.client = parseNum(allocated), parseNum(core), parseNum(client)
		code := b.codes[a.milestone]
		switch {
		case a.kind == "team" && a.team != "":
			b.team[[2]string{code, a.team}] = &a
			b.teamsOf[code] = append(b.teamsOf[code], &a)
		case a.employee != "":
			b.staff[[2]string{code, a.employee}] = &a
			b.staffOf[code] = append(b.staffOf[code], &a)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	start, _ := fyRange(fy)
	rows, err = db.Query(ctx, `SELECT t.allocation_id, t.period_start, t.planned_value::text FROM hr_milestone_period_target t
		JOIN hr_milestone_allocation a ON t.allocation_id = a.id
		WHERE a.milestone_id = ANY($1::varchar[]) AND a.status = 'approved' AND t.period_type = 'month'`, ids)
	if err != nil {
		return nil, fmt.Errorf("teamperformance: phasing: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var periodStart *day
		var value *string
		if err := rows.Scan(&id, &periodStart, &value); err != nil {
			return nil, err
		}
		if periodStart == nil || value == nil {
			continue
		}
		month := (periodStart.Year()-start.Year())*12 + int(periodStart.Month()) - int(start.Month()) + 1
		if month >= 1 && month <= 12 {
			if b.phasing[id] == nil {
				b.phasing[id] = &months{}
			}
			b.phasing[id].set(month, *parseNum(value))
		}
	}
	return b, rows.Err()
}

// loadCountry is country_targets.load: the targets IA or Admin set.
func (b *targetBook) loadCountry(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `SELECT key, annual_target::text, monthly_targets::text, COALESCE(set_by_role, '') FROM country_report_target WHERE fy = $1`, b.fy)
	if err != nil {
		return fmt.Errorf("teamperformance: country targets: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var key, role string
		var annual, monthly *string
		if err := rows.Scan(&key, &annual, &monthly, &role); err != nil {
			return err
		}
		ct := countryTarget{source: "Country target (" + setterOf(role) + ")"}
		if a := parseNum(annual); a != nil {
			ct.annual = *a
		}
		if monthly != nil {
			ms, err := orderedMonths(*monthly)
			if err != nil {
				return fmt.Errorf("teamperformance: country target %s: %w", key, err)
			}
			if ms != nil {
				ct.months = ms
			}
		}
		b.country[key] = ct
	}
	return rows.Err()
}

func setterOf(role string) string {
	if label, ok := rules.Setters[role]; ok {
		return label
	}
	return role
}

// orderedMonths reads a monthly_targets object in its stored key order, as
// Python's json.loads keeps it: {int(m): float(v)}. nil for an empty or
// non-object value (falsy in Python).
func orderedMonths(text string) (*months, error) {
	dec := json.NewDecoder(strings.NewReader(text))
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	if delim, ok := tok.(json.Delim); !ok || delim != '{' {
		return nil, nil
	}
	out := &months{}
	for dec.More() {
		keyTok, err := dec.Token()
		if err != nil {
			return nil, err
		}
		var raw any
		if err := dec.Decode(&raw); err != nil {
			return nil, err
		}
		m, ok := parsePyInt(fmt.Sprint(keyTok))
		if !ok {
			return nil, fmt.Errorf("month %v", keyTok)
		}
		var v float64
		switch x := raw.(type) {
		case string:
			f, err := strconv.ParseFloat(x, 64)
			if err != nil {
				return nil, err
			}
			v = f
		case float64:
			v = x
		default:
			return nil, fmt.Errorf("month %d value", m)
		}
		out.set(m, v)
	}
	if len(out.order) == 0 {
		return nil, nil
	}
	return out, nil
}

// ── Reading ─────────────────────────────────────────────────────────────────

// targetOf is TargetBook.target.
func (b *targetBook) targetOf(m *measure, s scope, eligible *int) target {
	var ms *milestone
	if m.Milestone != "" {
		ms = b.byCode[m.Milestone]
	}
	if s.kind == "country" {
		if ct, ok := b.country[m.Key]; ok {
			return target{annual: ptr(ct.annual), source: ct.source, months: ct.months}
		}
	}
	if ms != nil {
		if rateMeasurements[ms.measurement] {
			return b.rate(ms, s, eligible)
		}
		if found := b.count(ms, m, s); found != nil {
			return *found
		}
	}
	if m.Basis != "" && m.Milestone == "" && eligible != nil {
		return target{annual: ptr(float64(*eligible)), source: rules.Eligible}
	}
	return target{source: rules.NotSet}
}

// forCode is TargetBook.for_code: a Strategic Milestones row's target.
func (b *targetBook) forCode(code string, s scope, slice, basis string, eligible *int, key string) target {
	probe := &measure{Key: key, Milestone: code, Slice: slice, Basis: basis, Tracked: true}
	return b.targetOf(probe, s, eligible)
}

func (b *targetBook) holders(code string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, a := range b.staffOf[code] {
		if !seen[a.employee] {
			seen[a.employee] = true
			out = append(out, a.employee)
		}
	}
	sort.Strings(out)
	return out
}

func (b *targetBook) allocations(code string, s scope) []*allocation {
	switch s.kind {
	case "officer":
		if a := b.staff[[2]string{code, s.lead}]; a != nil {
			return []*allocation{a}
		}
		return nil
	case "region":
		if a := b.team[[2]string{code, s.lead}]; a != nil {
			return []*allocation{a}
		}
		ids := []string{}
		for id := range s.staff {
			ids = append(ids, id)
		}
		sort.Strings(ids)
		out := []*allocation{}
		for _, id := range ids {
			if a := b.staff[[2]string{code, id}]; a != nil {
				out = append(out, a)
			}
		}
		return out
	}
	return nil
}

func sliceOfMilestone(ms *milestone, m *measure) *float64 {
	switch m.Slice {
	case "core":
		return ms.core
	case "client":
		return ms.client
	}
	return ms.value
}

func sliceOfAllocation(a *allocation, m *measure) *float64 {
	switch m.Slice {
	case "core":
		return a.core
	case "client":
		return a.client
	}
	return a.allocated
}

func sourceOf(a *allocation) string {
	if a.kind == "team" {
		return "Team allocation"
	}
	return "Allocation"
}

func (b *targetBook) count(ms *milestone, m *measure, s scope) *target {
	if s.kind == "country" {
		annual := sliceOfMilestone(ms, m)
		if annual == nil {
			return nil
		}
		spread := b.teamsOf[ms.code]
		if len(spread) == 0 {
			spread = b.staffOf[ms.code]
		}
		t := target{annual: annual, source: "Country milestone"}
		if len(spread) > 0 {
			t.months = b.phase(spread, m)
		}
		return &t
	}
	allocations := b.allocations(ms.code, s)
	if len(allocations) == 0 {
		return nil
	}
	values := []float64{}
	any := false
	for _, a := range allocations {
		v := sliceOfAllocation(a, m)
		if v != nil {
			any = true
			values = append(values, *v)
		} else {
			values = append(values, 0)
		}
	}
	if !any {
		return nil
	}
	return &target{annual: ptr(pySumFrom0(values)), source: sourceOf(allocations[0]), months: b.phase(allocations, m)}
}

// phase is TargetBook._phasing.
func (b *targetBook) phase(allocations []*allocation, m *measure) *months {
	out := &months{}
	phased := false
	for _, a := range allocations {
		rows := b.phasing[a.id]
		if rows == nil || len(rows.order) == 0 {
			continue
		}
		phased = true
		portion := 1.0
		whole := a.allocated
		part := sliceOfAllocation(a, m)
		if m.Slice != "" && whole != nil && *whole != 0 && part != nil {
			portion = *part / *whole
		}
		for _, month := range rows.order {
			out.Add(month, float64(rows.by[month]*portion))
		}
	}
	if !phased {
		return nil
	}
	return out
}

func (b *targetBook) rate(ms *milestone, s scope, eligible *int) target {
	rate := ms.value
	source := "Country milestone"
	allocations := b.allocations(ms.code, s)
	if len(allocations) > 0 && allocations[0].allocated != nil {
		rate = allocations[0].allocated
		source = sourceOf(allocations[0])
	}
	if rate == nil || eligible == nil {
		return target{source: rules.NotSet, rate: rate}
	}
	annual := pyRoundInt(*rate / 100.0 * float64(*eligible))
	return target{annual: &annual, source: fmtG(*rate) + "% of eligible schools (" + lowerASCII(source) + ")", rate: rate}
}

func lowerASCII(s string) string { return pyLower(s) }
