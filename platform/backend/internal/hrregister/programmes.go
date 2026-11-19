package hrregister

import (
	"context"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Four registers over the People records in reach (_profile_scope), as
// hr_views draws them: Culture & Engagement (culture_engagement_view),
// Payroll Readiness (payroll_readiness_view), Succession Planning
// (succession_planning_view) and Staff Wellness & Support (wellness_view).

const humanCapital = "Human Capital Operations"

// inReach is the People records in reach as a sub-select of their ids.
func inReach(in input, args []any) (string, []any) {
	where, args := in.reach.profiles(args)
	return `(SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND ` + where + `)`, args
}

// cultureEngagement groups the People records in reach (and the search) by
// country and team, each team's activation, beside the employee-relations
// cases the viewer may see.
func cultureEngagement(ctx context.Context, in input) (register, error) {
	reachSQL, args := in.reach.profiles(nil)
	searchSQL, args := searched(in.search, args)
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT COALESCE(sp.department, ''), COALESCE(sp.country, ''), count(*), count(*) FILTER (WHERE sp.onboarding_state = 'active')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND %s AND %s
GROUP BY sp.department, sp.country ORDER BY sp.country, sp.department`, reachSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the teams: %w", err)
	}
	type team struct {
		department, country string
		people, active      int
	}
	teams, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (team, error) {
		var t team
		return t, r.Scan(&t.department, &t.country, &t.people, &t.active)
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the teams: %w", err)
	}
	reg := register{path: "/culture-engagement", primary: &action{label: "Open People Directory", href: "/staff"}, title: "Culture & Engagement", eyebrow: humanCapital,
		description: "A conservative workforce-experience view using real activation and employee-relations signals. Survey and eNPS values are intentionally absent until a survey workflow exists.",
		columns:     []string{"Team", "Country", "People", "Active", "Activation"},
		emptyTitle:  "No workforce experience data in this scope", emptyBody: defaultEmptyBody}
	people, active := 0, 0
	for _, t := range teams {
		people += t.people
		active += t.active
		share := 0
		if t.people > 0 {
			share = int(math.RoundToEven(float64(t.active) / float64(t.people) * 100))
		}
		department := t.department
		if department == "" {
			department = "Unassigned"
		}
		reg.rows = append(reg.rows, []string{department, dash(t.country), count(t.people), count(t.active), strconv.Itoa(share) + "%"})
	}
	// The cases count every status: the view excludes "Resolved" and "Closed"
	// while the register stores lowercase codes.
	caseSQL, cargs := erVisible(in, nil)
	var open, critical int
	if err := in.db.QueryRow(ctx, `SELECT count(*), count(*) FILTER (WHERE c.severity = 'critical')
FROM hr_relations_case c WHERE `+caseSQL+` AND c.status <> ALL(ARRAY['Resolved', 'Closed'])`, cargs...).Scan(&open, &critical); err != nil {
		return register{}, fmt.Errorf("hrregister: counting the relations cases: %w", err)
	}
	reg.metrics = []metric{
		{"People", count(people), "in the visible workforce", "info"},
		{"Active", count(active), "activated team members", "success"},
		{"Open relations cases", count(open), "confidential follow-up", "warning"},
		{"Critical cases", count(critical), "leadership attention", "danger"},
	}
	return reg, nil
}

// payrollReadiness is the payroll checks of the People in reach, the latest
// period first; the latest period's checks counted.
func payrollReadiness(ctx context.Context, in input) (register, error) {
	who, args := inReach(in, nil)
	searchSQL, args := contains(in.search, args, "u.name", "p.payroll_period", "p.exception_notes")
	rows, err := in.db.Query(ctx, `
SELECT u.name, COALESCE(NULLIF(sp.title, ''), u.active_role, ''), COALESCE(sp.country, ''), p.payroll_period,
  p.has_exceptions, p.is_payroll_ready
FROM hr_payroll_readiness p JOIN staff_profile sp ON sp.id = p.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE p.staff_id IN `+who+` AND `+searchSQL+`
ORDER BY p.payroll_period DESC, u.name`, args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the payroll checks: %w", err)
	}
	type check struct {
		name, role, country, period string
		exceptions, ready           bool
	}
	checks, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (check, error) {
		var c check
		return c, r.Scan(&c.name, &c.role, &c.country, &c.period, &c.exceptions, &c.ready)
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the payroll checks: %w", err)
	}
	reg := register{path: "/payroll-readiness", primary: &action{label: "Open the People Directory", href: "/staff"}, title: "Payroll Readiness", eyebrow: humanCapital,
		description: "Period-specific payroll checks that expose exceptions and readiness without revealing banking or salary details.",
		columns:     []string{"Team member", "Role", "Country", "Payroll period", "Exceptions", "Readiness"},
		emptyTitle:  "No payroll-readiness checks in this scope", emptyBody: defaultEmptyBody}
	latest := ""
	staffChecked, ready, exceptions := 0, 0, 0
	for i, c := range checks {
		if i == 0 {
			latest = c.period
		}
		if latest != "" && c.period == latest {
			staffChecked++
			if c.ready {
				ready++
			}
			if c.exceptions {
				exceptions++
			}
		}
		exc, rd := "None", "Pending"
		if c.exceptions {
			exc = "Yes"
		}
		if c.ready {
			rd = "Ready"
		}
		reg.rows = append(reg.rows, []string{dash(c.name), dash(c.role), dash(c.country), dash(c.period), exc, rd})
	}
	reg.metrics = []metric{
		{"Current period", dash(latest), "latest configured payroll run", "info"},
		{"Staff checked", count(staffChecked), "records in latest period", "info"},
		{"Ready", count(ready), "cleared for payroll", "success"},
		{"Exceptions", count(exceptions), "requiring resolution", "danger"},
	}
	return reg, nil
}

// successionPlanning is the successors named from the People in reach, by
// position and successor.
func successionPlanning(ctx context.Context, in input) (register, error) {
	who, args := inReach(in, nil)
	searchSQL, args := contains(in.search, args, "c.position_name", "u.name", "c.readiness")
	rows, err := in.db.Query(ctx, `
SELECT c.position_name, u.name, COALESCE(sp.title, ''), COALESCE(sp.country, ''), COALESCE(c.readiness, ''), c.updated_at
FROM hr_succession_candidate c JOIN staff_profile sp ON sp.id = c.staff_successor_id JOIN "user" u ON u.id = sp.user_id
WHERE c.staff_successor_id IN `+who+` AND `+searchSQL+`
ORDER BY c.position_name, u.name`, args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the successors: %w", err)
	}
	type candidate struct {
		position, name, title, country, readiness string
		updated                                   time.Time
	}
	candidates, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (candidate, error) {
		var c candidate
		return c, r.Scan(&c.position, &c.name, &c.title, &c.country, &c.readiness, &c.updated)
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the successors: %w", err)
	}
	reg := register{path: "/succession-planning", primary: &action{label: "Review Professional Development", href: "/cpd-learning"}, title: "Succession Planning", eyebrow: humanCapital,
		description: "Critical-position continuity built from named successors and explicit readiness assessments—not inferred talent labels.",
		columns:     []string{"Critical position", "Successor", "Current role", "Country", "Readiness", "Updated"},
		emptyTitle:  "No succession nominations in this scope", emptyBody: defaultEmptyBody}
	by := map[string]int{}
	for _, c := range candidates {
		by[c.readiness]++
		// updated_at.date(): the stored instant's UTC day.
		reg.rows = append(reg.rows, []string{dash(c.position), dash(c.name), dash(c.title), dash(c.country), dash(c.readiness),
			c.updated.UTC().Format(time.DateOnly)})
	}
	reg.metrics = []metric{
		{"Nominations", count(len(candidates)), "successor records in scope", "info"},
		{"Ready now", count(by["Ready Now"]), "immediate successors", "success"},
		{"6–12 months", count(by["Ready in 6-12 Months"]), "near-term pipeline", "info"},
		{"Development required", count(by["Development Required"]), "requires action", "warning"},
	}
	return reg, nil
}

// wellness is the leave of the People in reach, the newest first, with who
// covers it.
func wellness(ctx context.Context, in input) (register, error) {
	who, args := inReach(in, nil)
	searchSQL, args := contains(in.search, args, "u.name", "l.type", "l.status")
	rows, err := in.db.Query(ctx, `
SELECT u.name, COALESCE(l.type, ''), COALESCE(l.start_date, ''), COALESCE(l.end_date, ''), COALESCE(l.days_charged, l.days),
  cu.name, COALESCE(l.coverage_status, ''), COALESCE(l.status, '')
FROM leave l JOIN staff_profile sp ON sp.id = l.staff_id JOIN "user" u ON u.id = sp.user_id
LEFT JOIN staff_profile csp ON csp.id = l.covering_staff_id LEFT JOIN "user" cu ON cu.id = csp.user_id
WHERE l.staff_id IN `+who+` AND `+searchSQL+`
ORDER BY l.created_at DESC`, args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the leave: %w", err)
	}
	type away struct {
		name, kind, start, end, coverage, status string
		days                                     int
		cover                                    *string
	}
	leaves, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (away, error) {
		var a away
		return a, r.Scan(&a.name, &a.kind, &a.start, &a.end, &a.days, &a.cover, &a.coverage, &a.status)
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the leave: %w", err)
	}
	reg := register{path: "/wellness", primary: &action{label: "Open Personal Time Off", href: "/personal-time-off/"}, title: "Staff Wellness & Support", eyebrow: humanCapital,
		description: "Real leave, workload-continuity, and coverage signals. Clinical or counseling data is not collected on this platform.",
		columns:     []string{"Team member", "Leave type", "Dates", "Days", "Coverage", "Status"},
		emptyTitle:  "No leave or coverage records in this scope", emptyBody: defaultEmptyBody}
	pending, approved, gaps := 0, 0, 0
	for _, a := range leaves {
		switch a.status {
		case "pending":
			pending++
		case "approved":
			approved++
		}
		if a.cover == nil && a.status != "rejected" && a.status != "cancelled" {
			gaps++
		}
		cover := a.coverage
		if a.cover != nil {
			cover = *a.cover
		}
		reg.rows = append(reg.rows, []string{dash(a.name), dash(pyTitle(strings.ReplaceAll(a.kind, "_", " "))), a.start + " – " + a.end,
			count(a.days), dash(cover), dash(pyTitle(a.status))})
	}
	reg.metrics = []metric{
		{"Leave records", count(len(leaves)), "visible requests", "info"},
		{"Pending", count(pending), "awaiting a decision", "warning"},
		{"Approved", count(approved), "confirmed time away", "success"},
		{"Coverage gaps", count(gaps), "without a named cover", "danger"},
	}
	return reg, nil
}
