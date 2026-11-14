// Package allocations is the approved priority contract
// (apps.hr.accountability.allocation_priorities, for the reader's own
// contract): the approved allocations of a year on live, approved
// milestones, scoped as the existing engine scopes them (a Programme Lead's
// team root and the officers' own allocations it does not cover; a country
// reader's top-level allocations in their country; anyone else's own), each
// milestone's target for the period, the verified credits of the activities
// that count, the plan's progress, and the weighted overall share.
//
// It reads; it never writes. The constants are exported to rules.json by
// `manage.py export_allocations_rules`;
// apps/hr/test_allocations_rules_export.py fails when the two differ.
package allocations

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	RateTypes          []string            `json:"rate_measurement_types"`
	SchoolBases        []string            `json:"school_bases"`
	TeacherBases       []string            `json:"teacher_bases"`
	LeaderBases        []string            `json:"leader_bases"`
	PlannedStatuses    []string            `json:"planned_output_statuses"`
	CompletedStatuses  []string            `json:"completed_work_statuses"`
	SchoolTypeFamilies map[string][]string `json:"school_type_families"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.RateTypes) == 0 || len(r.SchoolBases) == 0 || len(r.PlannedStatuses) == 0 {
		panic(fmt.Sprintf("allocations: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var countryRoles = []string{"CountryDirector", "RegionalVicePresident", "Admin"}

// Progress is one milestone's plan progress (milestone_plan_progress), as
// the contract leaves it.
type Progress struct {
	Unit, Year         string
	Target             *big.Rat
	Planned, Completed int64
	Verified           *big.Rat
	HasWork, Started   bool
	Pct, PlannedPct    *float64
}

// Row is one milestone of the contract.
type Row struct {
	ID, Title, Priority, Unit, Source string
	Target, Actual                    *big.Rat
	Pct                               *float64
	Weight                            float64
	Progress                          *Progress
}

// Contract is the reader's approved contract for the year.
type Contract struct {
	Rows  []Row
	Pct   *float64
	Scope string
}

// ScopeLabel is _contract_scope_label for the reader's own contract.
func ScopeLabel(role string) string {
	switch {
	case role == "Program Lead":
		return "You and your team"
	case slices.Contains(countryRoles, role):
		return "Country delivery"
	}
	return "Your delivery and monitored partners"
}

// Exist is _approved_allocations_exist: any approved allocation of the year
// on a live, approved milestone.
func Exist(ctx context.Context, db schooldirectory.Querier, fy string) (bool, error) {
	var found bool
	err := db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM hr_milestone_allocation a JOIN hr_priority_milestone m ON m.id = a.milestone_id
               JOIN hr_strategic_priority sp ON sp.id = m.priority_id
               WHERE a.status = 'approved' AND sp.fy = $1 AND m.active AND m.definition_status = 'approved')`, fy).Scan(&found)
	if err != nil {
		return false, fmt.Errorf("allocations: reading the year's allocations: %w", err)
	}
	return found, nil
}

type allocation struct {
	id, milestoneID, title, priority, unit, measurement, countryID, priorityFY string
	// The plan's order: the priority's sequence, then the milestone's.
	sequence, sourceOrder                                            int
	code                                                             string
	allocated, denominator, weight, milestoneWeight, milestoneTarget *big.Rat
	capAt100                                                         bool
	periods                                                          []period
}

type period struct {
	start   time.Time
	planned *big.Rat
}

type rule struct {
	milestoneID, basis, catalogue, project, executor, method, schoolType, intervention string
}

// Read is allocation_priorities(user, fy) for the reader's own contract over
// the whole year, with the plan's progress.
func Read(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time, today time.Time) (Contract, error) {
	c := Contract{Scope: ScopeLabel(p.ActiveRole)}
	if p.StaffProfileID == "" {
		return Contract{Scope: "Assigned priorities"}, nil
	}
	exist, err := Exist(ctx, db, fy)
	if err != nil || !exist {
		return c, err
	}
	n, _ := strconv.Atoi(fy)
	start, end := time.Date(n-1, time.October, 1, 0, 0, 0, 0, time.UTC), time.Date(n, time.September, 30, 0, 0, 0, 0, time.UTC)
	countryScope := slices.Contains(countryRoles, p.ActiveRole)
	// The existing queryset sets no order: its rows come in whatever order
	// the planner reaches them, which moves with the select list and the
	// data. Go lists the milestones in the plan's own order instead (the
	// priority's sequence, then the milestone's), a deterministic order the
	// existing page only sometimes shows.
	where, args := `m.active AND m.definition_status = 'approved' AND sp.fy = $1 AND a.status = 'approved'`, []any{fy}
	arg := func(v any) string { args = append(args, v); return fmt.Sprintf("$%d", len(args)) }
	var owners []string
	switch {
	case p.ActiveRole == "Program Lead":
		if owners, err = ownerIDs(ctx, db, p.StaffProfileID, true); err != nil {
			return c, err
		}
		staff := arg(p.StaffProfileID)
		// IN (…), one argument each, as the queryset writes the list.
		list := []string{}
		for _, id := range owners {
			list = append(list, arg(id))
		}
		ids := strings.Join(list, ", ")
		if len(list) == 0 {
			ids = "NULL"
		}
		where += fmt.Sprintf(` AND ((a.allocated_to_type = 'team' AND a.team_id = %[1]s)
 OR (a.allocated_to_type = 'employee' AND a.employee_id IN (%[2]s) AND NOT (a.milestone_id IN (
     SELECT u0.milestone_id FROM hr_milestone_allocation u0 INNER JOIN hr_priority_milestone u1 ON u0.milestone_id = u1.id
     INNER JOIN hr_strategic_priority u2 ON u1.priority_id = u2.id
     WHERE u1.active AND u1.definition_status = 'approved' AND u2.fy = $1 AND u0.status = 'approved'
       AND u0.allocated_to_type = 'team' AND u0.team_id = %[1]s))))`, staff, ids)
	case countryScope:
		country, err := readerCountry(ctx, db, p, now)
		if err != nil {
			return c, err
		}
		where += " AND a.parent_id IS NULL"
		if country != "" {
			cc := arg(country)
			where += fmt.Sprintf(` AND sp.country_id = %[1]s AND (a.employee_id IS NULL OR e.country = %[1]s)`, cc)
		}
	default:
		if owners, err = ownerIDs(ctx, db, p.StaffProfileID, false); err != nil {
			return c, err
		}
		where += " AND a.allocated_to_type = 'employee' AND a.employee_id = " + arg(p.StaffProfileID)
	}
	allocs, err := readAllocations(ctx, db, where, args)
	if err != nil || len(allocs) == 0 {
		return c, err
	}
	// Group by milestone in the allocations' order.
	order, groups := []string{}, map[string][]allocation{}
	for _, a := range allocs {
		if _, ok := groups[a.milestoneID]; !ok {
			order = append(order, a.milestoneID)
		}
		groups[a.milestoneID] = append(groups[a.milestoneID], a)
	}
	rulesOf, err := readRules(ctx, db, order)
	if err != nil {
		return c, err
	}
	type entry struct {
		group       []allocation
		target, den *big.Rat
		bases       map[string]bool
	}
	entries := []entry{}
	byCountry, countryOrder := map[string][]int{}, []string{}
	for _, mid := range order {
		g := groups[mid]
		m := g[0]
		target, den, rateNum := new(big.Rat), new(big.Rat), new(big.Rat)
		rate := slices.Contains(rules.RateTypes, m.measurement)
		for _, a := range g {
			target.Add(target, a.allocated) // the whole year: no quarter or month
			if a.denominator != nil {
				den.Add(den, a.denominator)
				rateNum.Add(rateNum, new(big.Rat).Mul(a.allocated, a.denominator))
			}
		}
		if rate {
			switch {
			case countryScope:
				target = orZero(m.milestoneTarget)
			case den.Sign() != 0:
				target = new(big.Rat).Quo(rateNum, den)
			}
		}
		bases := map[string]bool{}
		for _, r := range rulesOf[mid] {
			bases[r.basis] = true
		}
		if _, ok := byCountry[m.countryID]; !ok {
			countryOrder = append(countryOrder, m.countryID)
		}
		byCountry[m.countryID] = append(byCountry[m.countryID], len(entries))
		entries = append(entries, entry{group: g, target: target, den: den, bases: bases})
	}
	progressOf, verifiedOf := map[string]*Progress{}, map[string]*big.Rat{}
	for _, cid := range countryOrder {
		scope, sargs := activityScope(cid, countryScope, owners, fy, start, end)
		ms := []string{}
		targets := map[string]*big.Rat{}
		for _, i := range byCountry[cid] {
			mid := entries[i].group[0].milestoneID
			ms = append(ms, mid)
			targets[mid] = entries[i].target
		}
		plan, err := planProgress(ctx, db, ms, groups, rulesOf, fy, scope, sargs, targets, today)
		if err != nil {
			return c, err
		}
		for k, v := range plan {
			progressOf[k] = v
		}
		bases := map[string]map[string]bool{}
		for _, i := range byCountry[cid] {
			bases[entries[i].group[0].milestoneID] = entries[i].bases
		}
		verified, err := aggregateCredits(ctx, db, bases, "", scope, sargs)
		if err != nil {
			return c, err
		}
		for k, v := range verified {
			verifiedOf[k] = v
		}
	}
	for _, e := range entries {
		m := e.group[0]
		actual := orZero(verifiedOf[m.milestoneID])
		verifiedUnits := actual
		configured := len(e.bases) > 0 && len(families(e.bases)) == 1
		rate := slices.Contains(rules.RateTypes, m.measurement)
		if rate {
			if e.den.Sign() != 0 {
				actual = new(big.Rat).Mul(new(big.Rat).Quo(actual, e.den), big.NewRat(100, 1))
			} else {
				actual = new(big.Rat)
			}
			configured = configured && e.den.Sign() != 0
			if m.capAt100 && actual.Cmp(big.NewRat(100, 1)) > 0 {
				actual = big.NewRat(100, 1)
			}
		}
		var pct *float64
		if e.target.Sign() != 0 && configured {
			f, _ := new(big.Rat).Mul(new(big.Rat).Quo(actual, e.target), big.NewRat(100, 1)).Float64()
			v := round(f, 2)
			if m.capAt100 && !rate {
				v = math.Min(v, 100)
			}
			pct = &v
		}
		progress := progressOf[m.milestoneID]
		if progress != nil {
			progress.Verified = verifiedUnits
			if rate {
				progress.Pct, progress.PlannedPct = nil, nil
				if e.den.Sign() != 0 && e.target.Sign() != 0 {
					done := new(big.Rat).Quo(new(big.Rat).Mul(new(big.Rat).SetInt64(progress.Completed), big.NewRat(100, 1)), e.den)
					f, _ := new(big.Rat).Mul(new(big.Rat).Quo(done, e.target), big.NewRat(100, 1)).Float64()
					v := math.Min(round(f, 1), 100)
					progress.Pct = &v
				}
				progress.Target = nil
				if e.den.Sign() != 0 {
					progress.Target = new(big.Rat).Quo(new(big.Rat).Mul(e.den, e.target), big.NewRat(100, 1))
				}
				if progress.Target != nil && progress.Target.Sign() != 0 {
					f, _ := new(big.Rat).Quo(new(big.Rat).SetInt64(progress.Planned), progress.Target).Float64()
					v := math.Min(round(f*100, 1), 100)
					progress.PlannedPct = &v
				}
			}
		}
		weight := 0.0
		if !countryScope && m.weight != nil {
			weight, _ = m.weight.Float64()
		}
		if weight == 0 && m.milestoneWeight != nil {
			weight, _ = m.milestoneWeight.Float64()
		}
		c.Rows = append(c.Rows, Row{ID: m.milestoneID, Title: m.title, Priority: m.priority, Unit: m.unit, Source: "Approved allocation",
			Target: e.target, Actual: actual, Pct: pct, Weight: weight, Progress: progress})
	}
	eligible, withTarget, ready := 0, 0, true
	totalW, sum := 0.0, 0.0
	for _, r := range c.Rows {
		if r.Target.Sign() > 0 {
			withTarget++
		}
		if r.Pct != nil {
			eligible++
			if r.Weight <= 0 {
				ready = false
			}
			totalW += r.Weight
			sum += *r.Pct * r.Weight
		}
	}
	if eligible > 0 && eligible == withTarget && ready && totalW != 0 {
		v := round(sum/totalW, 2)
		c.Pct = &v
	}
	return c, nil
}

// inPlanOrder lists allocations in the plan's order: the priority's
// sequence, the milestone's source order and code, then the ids. The
// existing queryset sets no order, so its rows come as the planner reaches
// them; the owner chose the plan's order (2026-11-14: "Yes, plan order").
func inPlanOrder(allocs []allocation) {
	sort.SliceStable(allocs, func(i, j int) bool {
		a, b := allocs[i], allocs[j]
		switch {
		case a.sequence != b.sequence:
			return a.sequence < b.sequence
		case a.sourceOrder != b.sourceOrder:
			return a.sourceOrder < b.sourceOrder
		case a.code != b.code:
			return a.code < b.code
		case a.milestoneID != b.milestoneID:
			return a.milestoneID < b.milestoneID
		}
		return a.id < b.id
	})
}

func orZero(r *big.Rat) *big.Rat {
	if r == nil {
		return new(big.Rat)
	}
	return r
}

// round is Python's round(x, n) on a float: the nearest of the decimal
// values, the binary value read exactly.
func round(x float64, n int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', n, 64), 64)
	return v
}

func families(bases map[string]bool) map[string]bool {
	out := map[string]bool{}
	for b := range bases {
		switch {
		case slices.Contains(rules.SchoolBases, b):
			out["schools"] = true
		case slices.Contains(rules.TeacherBases, b):
			out["teachers"] = true
		case slices.Contains(rules.LeaderBases, b):
			out["leaders"] = true
		default:
			out["credited_value"] = true
		}
	}
	return out
}

func readerCountry(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (string, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", err
	}
	if scope.Country != "" {
		return scope.Country, nil
	}
	var country *string
	err = db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE id = $1`, p.StaffProfileID).Scan(&country)
	if err != nil || country == nil {
		return "", nil
	}
	return *country, nil
}

// ownerIDs is contribution_scope.owner_ids: the People records (and the
// lead's supervisees) and their accounts.
func ownerIDs(ctx context.Context, db schooldirectory.Querier, staffID string, team bool) ([]string, error) {
	rows, err := db.Query(ctx, `
WITH ids AS (SELECT $1::text AS id UNION SELECT supervisee_id FROM staff_supervisor_assignment WHERE $2 AND supervisor_id = $1)
SELECT id FROM ids UNION SELECT sp.user_id FROM staff_profile sp WHERE sp.id IN (SELECT id FROM ids) AND sp.user_id IS NOT NULL AND sp.user_id <> ''`,
		staffID, team)
	if err != nil {
		return nil, fmt.Errorf("allocations: reading whose work counts: %w", err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("allocations: reading whose work counts: %w", err)
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

func rat(s *string) *big.Rat {
	if s == nil {
		return nil
	}
	r, ok := new(big.Rat).SetString(*s)
	if !ok {
		return nil
	}
	return r
}

func readAllocations(ctx context.Context, db schooldirectory.Querier, where string, args []any) ([]allocation, error) {
	rows, err := db.Query(ctx, `
SELECT a.id, a.milestone_id, COALESCE(m.title, ''), COALESCE(sp.title, ''), COALESCE(m.target_unit, ''), COALESCE(m.measurement_type, ''),
       COALESCE(sp.country_id, ''), COALESCE(sp.fy, ''), a.allocated_target::text, a.denominator::text, a.weight::text, m.weight::text,
       m.target_value::text, m.cap_at_100, sp.sequence, m.source_order, COALESCE(m.code, '')
FROM hr_milestone_allocation a INNER JOIN hr_priority_milestone m ON a.milestone_id = m.id
INNER JOIN hr_strategic_priority sp ON m.priority_id = sp.id
LEFT OUTER JOIN staff_profile e ON a.employee_id = e.id
WHERE (`+where+`)`, args...)
	if err != nil {
		return nil, fmt.Errorf("allocations: reading the allocations: %w", err)
	}
	out := []allocation{}
	for rows.Next() {
		var a allocation
		var allocated, den, weight, mweight, mtarget *string
		if err := rows.Scan(&a.id, &a.milestoneID, &a.title, &a.priority, &a.unit, &a.measurement, &a.countryID, &a.priorityFY,
			&allocated, &den, &weight, &mweight, &mtarget, &a.capAt100, &a.sequence, &a.sourceOrder, &a.code); err != nil {
			rows.Close()
			return nil, fmt.Errorf("allocations: reading an allocation: %w", err)
		}
		a.allocated, a.denominator, a.weight, a.milestoneWeight, a.milestoneTarget = orZero(rat(allocated)), rat(den), rat(weight), rat(mweight), rat(mtarget)
		out = append(out, a)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("allocations: reading the allocations: %w", err)
	}
	inPlanOrder(out)
	return out, nil
}

func readRules(ctx context.Context, db schooldirectory.Querier, milestones []string) (map[string][]rule, error) {
	rows, err := db.Query(ctx, `
SELECT milestone_id, COALESCE(counting_basis, ''), COALESCE(catalogue_item_id, ''), COALESCE(project_id, ''), COALESCE(required_executor_type, ''),
       COALESCE(required_delivery_method, ''), COALESCE(school_type, ''), COALESCE(target_intervention, '')
FROM hr_milestone_activity_rule WHERE active AND milestone_id = ANY($1)`, milestones)
	if err != nil {
		return nil, fmt.Errorf("allocations: reading the activity rules: %w", err)
	}
	defer rows.Close()
	out := map[string][]rule{}
	for rows.Next() {
		var r rule
		if err := rows.Scan(&r.milestoneID, &r.basis, &r.catalogue, &r.project, &r.executor, &r.method, &r.schoolType, &r.intervention); err != nil {
			return nil, fmt.Errorf("allocations: reading an activity rule: %w", err)
		}
		out[r.milestoneID] = append(out[r.milestoneID], r)
	}
	return out, rows.Err()
}

// activityScope is scoped_activities(country_id) for the reader's own
// contract, as a condition on activity `a` and its arguments.
func activityScope(countryID string, countryScope bool, owners []string, fy string, start, end time.Time) (string, []any) {
	args := []any{fy, start, end}
	arg := func(v any) string { args = append(args, v); return fmt.Sprintf("$%d", len(args)) }
	clause := `a.fy = $1 AND a.deleted_at IS NULL AND a.planned_date >= $2::date AND a.planned_date <= $3::date`
	if !countryScope {
		ids := arg(owners)
		clause += fmt.Sprintf(` AND ((a.responsible_staff_id = ANY(%[1]s) AND a.delivery_type IS DISTINCT FROM 'partner')
 OR (a.delivery_type = 'partner' AND a.monitored_by_staff_id = ANY(%[1]s)))`, ids)
	}
	if countryID != "" {
		c := arg(countryID)
		clause += fmt.Sprintf(` AND (
  EXISTS (SELECT 1 FROM school s JOIN region r ON r.id = s.region_id WHERE s.id = a.school_id AND r.country = %[1]s)
  OR EXISTS (SELECT 1 FROM school s WHERE s.id = a.school_id AND s.region_id IS NULL AND (
       s.account_owner_id IN (SELECT id FROM staff_profile WHERE country = %[1]s AND deleted_at IS NULL)
       OR s.account_owner_id IS NULL OR s.account_owner_id = ''
       OR s.account_owner_id IN (SELECT id FROM staff_profile WHERE (country IS NULL OR country = '') AND deleted_at IS NULL)))
  OR (a.school_id IS NULL AND EXISTS (SELECT 1 FROM cluster cl JOIN district d ON d.id = cl.district_id JOIN region r ON r.id = d.region_id
                                       WHERE cl.id = a.cluster_id AND r.country = %[1]s))
  OR (a.school_id IS NULL AND a.cluster_id IS NULL AND (
       a.responsible_staff_id IN (SELECT id FROM staff_profile WHERE country = %[1]s UNION SELECT user_id FROM staff_profile WHERE country = %[1]s AND user_id IS NOT NULL)
       OR a.monitored_by_staff_id IN (SELECT id FROM staff_profile WHERE country = %[1]s UNION SELECT user_id FROM staff_profile WHERE country = %[1]s AND user_id IS NOT NULL))))`, c)
	}
	return clause, args
}

// ruleMatch is _rule_activity_filter as a condition on activity `a`.
func ruleMatch(r rule, args *[]any) string {
	arg := func(v any) string { *args = append(*args, v); return fmt.Sprintf("$%d", len(*args)) }
	parts := []string{"a.catalogue_item_id = " + arg(r.catalogue)}
	if r.catalogue == "" {
		parts = []string{"a.catalogue_item_id IS NULL"}
	}
	if r.project != "" {
		parts = append(parts, "a.project_id = "+arg(r.project))
	}
	if r.executor != "" {
		parts = append(parts, "a.delivery_type = "+arg(r.executor))
	}
	if r.method != "" {
		parts = append(parts, "a.delivery_method_snapshot = "+arg(r.method))
	}
	if r.schoolType != "" {
		family := rules.SchoolTypeFamilies[r.schoolType]
		if family == nil {
			family = []string{r.schoolType}
		}
		parts = append(parts, "a.school_id IN (SELECT id FROM school WHERE school_type = ANY("+arg(family)+"))")
	}
	if r.intervention != "" {
		parts = append(parts, "a.focus_intervention = "+arg(r.intervention))
	}
	return "(" + strings.Join(parts, " AND ") + ")"
}
