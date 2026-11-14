package hrregister

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
)

// endingDays is how far ahead "Ending in 30 days" looks.
const endingDays = 30

// liveRecovery are the statuses of a plan still under way.
var liveRecovery = []string{"active", "progress_review", "extended"}

// recoveryPlans is recovery_plans_view: the recovery plans of the People
// records in reach (for a Programme Lead, a team register of the people they
// review: those they supervise in the roles they review, never themselves)
// whose person's name, cause code or status code holds the search, by status
// code and review day; a live plan past its review day reads "Past review
// date".
func recoveryPlans(ctx context.Context, in input) (register, error) {
	team := in.principal.ActiveRole == "Program Lead"
	var who string
	args := []any{}
	if team {
		reviewed := rules.Reviews[in.principal.ActiveRole]
		args = append(args, in.principal.StaffProfileID, reviewed)
		who = `(SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.active_role = ANY($2) AND sp.id <> $1
  AND sp.id IN (SELECT l.supervisee_id FROM staff_supervisor_assignment l WHERE l.supervisor_id = $1))`
		if in.principal.StaffProfileID == "" {
			who = "(SELECT NULL::text WHERE FALSE)"
			args = nil
		}
	} else {
		who, args = in.reach.visible(args)
	}
	searchSQL, args := contains(in.search, args, "u.name", "p.cause", "p.status")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT p.id, u.name, p.plan_type, p.cause, p.start_date, p.end_date, p.status
FROM hr_pip_plan p JOIN staff_profile sp ON sp.id = p.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE p.staff_id IN %s AND %s ORDER BY p.status, p.end_date`, who, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the recovery plans: %w", err)
	}
	type plan struct {
		id, name, kind, cause, status string
		start, end                    time.Time
	}
	plans, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (plan, error) {
		var p plan
		err := row.Scan(&p.id, &p.name, &p.kind, &p.cause, &p.start, &p.end, &p.status)
		return p, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the recovery plans: %w", err)
	}
	reg := register{
		path: "/recovery-plans", title: "Performance Recovery Plans", eyebrow: "Performance and talent",
		description: "Informal recovery plans and formal improvement plans: the cause, the support offered, the review date, " +
			"and the decision at the end.",
		columns:    []string{"Team member", "Plan", "Cause", "Start", "Review by", "Status"},
		actions:    []action{{label: "Recommend a formal plan", drawer: "/recovery-plans/new"}},
		teamView:   team,
		emptyTitle: "No recovery plans in this scope",
		emptyBody:  defaultEmptyBody,
	}
	if team {
		reg.emptyBody = "A plan you recommend for someone you review appears here while HR authorises it, and stays while you " +
			"record its check-ins."
	}
	horizon := in.today.AddDate(0, 0, endingDays)
	drafts, live, ending, escalated := 0, 0, 0, 0
	for _, p := range plans {
		isLive := slices.Contains(liveRecovery, p.status)
		switch {
		case p.status == "draft":
			drafts++
		case p.status == "escalated":
			escalated++
		case isLive:
			live++
			if !p.end.Before(in.today) && !p.end.After(horizon) {
				ending++
			}
		}
		status := labelOf(rules.RecoveryStatuses, p.status)
		if isLive && p.end.Before(in.today) {
			status = "Past review date"
		}
		reg.rows = append(reg.rows, []string{dash(p.name), dash(labelOf(rules.RecoveryPlanTypes, p.kind)),
			dash(labelOf(rules.RecoveryCauses, p.cause)), p.start.Format(time.DateOnly), p.end.Format(time.DateOnly), dash(status)})
		reg.rowActions = append(reg.rowActions, []action{{label: "Open", drawer: "/recovery-plans/" + p.id}})
	}
	reg.metrics = []metric{
		{"Awaiting authorisation", count(drafts), "formal plans to authorise", "warning"},
		{"Active", count(live), "under recovery", "info"},
		{"Ending in 30 days", count(ending), "outcome to decide", "warning"},
		{"Escalated", count(escalated), "became conduct cases", "danger"},
	}
	return reg, nil
}
