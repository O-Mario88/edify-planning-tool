package hrregister

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
)

// visible is _profile_scope(request).values("id") as a subquery: the live
// People records of live accounts in reach, exited or not.
func (r reach) visible(args []any) (string, []any) {
	reachSQL, args := r.profiles(args)
	return fmt.Sprintf(`(SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND %s)`, reachSQL), args
}

// onboarding is onboarding_view: the onboarding plans of the people in reach
// whose name, country or status holds the search, the newest first, each
// with its checklist; the figures over them, but Overdue over every plan in
// reach (overdue_onboarding: not closed, target day before today).
func onboarding(ctx context.Context, in input) (register, error) {
	visibleSQL, args := in.reach.visible(nil)
	searchSQL, args := contains(in.search, args, "u.name", "sp.country", "p.status")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT p.id, u.name, COALESCE(NULLIF(sp.title, ''), u.active_role, ''), sp.country, p.start_date::text, p.status,
       (SELECT count(*) FROM hr_onboarding_task t WHERE t.plan_id = p.id),
       (SELECT count(*) FROM hr_onboarding_task t WHERE t.plan_id = p.id AND t.is_completed)
FROM hr_onboarding_plan p JOIN staff_profile sp ON sp.id = p.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE p.staff_id IN %s AND %s ORDER BY p.created_at DESC`, visibleSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the onboarding plans: %w", err)
	}
	type plan struct {
		id, name, role, country, status string
		start                           *string
		tasks, done                     int
	}
	plans, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (plan, error) {
		var p plan
		err := row.Scan(&p.id, &p.name, &p.role, &p.country, &p.start, &p.status, &p.tasks, &p.done)
		return p, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the onboarding plans: %w", err)
	}
	visibleSQL, args = in.reach.visible(nil)
	args = append(args, in.today.Format(time.DateOnly))
	var overdue int
	if err := in.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FROM hr_onboarding_plan p
WHERE p.status <> 'closed' AND p.target_completion_date < $%d::date AND p.staff_id IN %s`, len(args), visibleSQL), args...).Scan(&overdue); err != nil {
		return register{}, fmt.Errorf("hrregister: counting the overdue onboarding plans: %w", err)
	}
	reg := register{
		path: "/onboarding", primary: &action{label: "Candidate Pipeline", href: "/candidate-pipeline"}, title: "Staff Onboarding", eyebrow: "Staffing and recruiting",
		description: "New hires from invitation to activation: checklist, supervisor confirmation, and the probation decision.",
		columns:     []string{"Team member", "Role", "Country", "Start date", "Checklist", "Status"},
		emptyTitle:  "No onboarding plans in this scope",
		emptyBody:   "Hiring a candidate opens their onboarding plan here.",
	}
	open, review, ready := 0, 0, 0
	for _, p := range plans {
		switch p.status {
		case "supervisor_review":
			review++
		case "ready_for_activation":
			ready++
		}
		if p.status != "closed" {
			open++
		}
		reg.rows = append(reg.rows, []string{
			dash(p.name), dash(p.role), dash(p.country), dash(deref(p.start)), fmt.Sprintf("%d of %d", p.done, p.tasks),
			dash(labelOf(rules.OnboardingStatuses, p.status)),
		})
		reg.rowActions = append(reg.rowActions, []action{{label: "Manage", drawer: "/onboarding/" + p.id}})
	}
	reg.metrics = []metric{
		{"Plans", count(open), "onboarding in progress", "info"},
		{"Overdue", count(overdue), "past their target completion", "danger"},
		{"Awaiting supervisor", count(review), "readiness not yet confirmed", "warning"},
		{"Ready for activation", count(ready), "HR can close and activate", "success"},
	}
	return reg, nil
}

// offboarding is offboarding_view: the exits of the people in reach whose
// name, status, reason or handover owner's name holds the search, by last
// working day (none last); the figures over them, but "Past exit date, still
// active" over every exit in reach (accounts_past_last_working_day: a last
// working day before today and a person not yet exited).
func offboarding(ctx context.Context, in input) (register, error) {
	visibleSQL, args := in.reach.visible(nil)
	searchSQL, args := contains(in.search, args, "u.name", "p.status", "p.exit_reason", "hu.name")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT p.id, u.name, sp.country, p.last_working_day::text, p.exit_reason, hu.name, p.status
FROM hr_offboarding p JOIN staff_profile sp ON sp.id = p.staff_id JOIN "user" u ON u.id = sp.user_id
LEFT JOIN staff_profile hp ON hp.id = p.handover_owner_id LEFT JOIN "user" hu ON hu.id = hp.user_id
WHERE p.staff_id IN %s AND %s ORDER BY p.last_working_day`, visibleSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the exits: %w", err)
	}
	type exit struct {
		id, name, country, reason, status string
		lastDay, owner                    *string
	}
	exits, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (exit, error) {
		var e exit
		err := row.Scan(&e.id, &e.name, &e.country, &e.lastDay, &e.reason, &e.owner, &e.status)
		return e, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the exits: %w", err)
	}
	visibleSQL, args = in.reach.visible(nil)
	args = append(args, in.today.Format(time.DateOnly))
	var overdue int
	if err := in.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FROM hr_offboarding p JOIN staff_profile sp ON sp.id = p.staff_id
WHERE p.last_working_day IS NOT NULL AND p.last_working_day < $%d::date AND NOT (sp.onboarding_state = 'exited')
  AND p.staff_id IN %s`, len(args), visibleSQL), args...).Scan(&overdue); err != nil {
		return register{}, fmt.Errorf("hrregister: counting the accounts past their exit: %w", err)
	}
	reg := register{
		path: "/offboarding", primary: &action{label: "Recruitment", href: "/recruitment"}, title: "Staff Offboarding", eyebrow: "Staffing and recruiting",
		description: "Exits across the countries you oversee: the reason for leaving, the handover, and the account closed on the last working day.",
		columns:     []string{"Team member", "Country", "Last working day", "Reason", "Handover owner", "Status"},
		actions:     []action{{label: "Start an offboarding", drawer: "/offboarding/new"}},
		emptyTitle:  "No offboarding in this scope",
		emptyBody:   "Start an offboarding when someone resigns, retires or is leaving.",
	}
	open, gaps, voluntary := 0, 0, 0
	for _, e := range exits {
		if e.status != "Closed" {
			open++
			if e.owner == nil {
				gaps++
			}
		}
		if slices.Contains(rules.VoluntaryExitReasons, e.reason) {
			voluntary++
		}
		reason := "Not recorded"
		if e.reason != "" {
			reason = labelOf(rules.ExitReasons, e.reason)
		}
		owner := "Unassigned"
		if e.owner != nil {
			owner = *e.owner
		}
		reg.rows = append(reg.rows, []string{dash(e.name), dash(e.country), dash(deref(e.lastDay)), reason, dash(owner), dash(e.status)})
		reg.rowActions = append(reg.rowActions, []action{{label: "Open", drawer: "/offboarding/" + e.id}})
	}
	overdueTone := "success"
	if overdue > 0 {
		overdueTone = "danger"
	}
	reg.metrics = []metric{
		{"In progress", count(open), "exits being worked", "warning"},
		{"Handover gaps", count(gaps), "without a named owner", "danger"},
		{"Voluntary exits", count(voluntary), "resignations and retirements", "info"},
		{"Past exit date, still active", count(overdue), "accounts to close now", overdueTone},
	}
	return reg, nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
