package teamtargets

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// wouldWrite is whether get_page would write during this render: a risk
// notice raised or closed (_notify_risk, the current year only), or a
// catch-up plan advanced (PLCatchUpPlanService.sync_completion). Go writes
// nothing on a read, so such a render is handed on.
func wouldWrite(ctx context.Context, db schooldirectory.Querier, leadUserID, fy string, current bool, t team) (bool, error) {
	if current {
		if raised, err := riskWouldChange(ctx, db, leadUserID, t); err != nil || raised {
			return raised, err
		}
	}
	return plansWouldAdvance(ctx, db, leadUserID, fy)
}

func riskWouldChange(ctx context.Context, db schooldirectory.Querier, leadUserID string, t team) (bool, error) {
	atRisk := map[string]bool{}
	for _, r := range t.where("High Risk", "Critical") {
		atRisk[r.member.UserID] = true
		var live bool
		if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE recipient_id = $1 AND source_event_type = $2
			AND context_type = 'staff_risk' AND context_id = $3 AND title = $4 AND resolved_at IS NULL AND status <> 'archived')`,
			leadUserID, rules.RiskEvents[0], r.member.UserID, r.member.Name+" is "+r.Status+" on targets").Scan(&live); err != nil {
			return false, fmt.Errorf("teamtargets: the risk notices: %w", err)
		}
		if !live {
			return true, nil
		}
	}
	recovered := []string{}
	for _, r := range t.rows {
		if !atRisk[r.member.UserID] {
			recovered = append(recovered, r.member.UserID)
		}
	}
	if len(recovered) == 0 {
		return false, nil
	}
	var stale bool
	if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE source_event_type = ANY($1)
		AND context_type = 'staff_risk' AND context_id = ANY($2) AND resolved_at IS NULL)`, rules.RiskEvents, recovered).Scan(&stale); err != nil {
		return false, fmt.Errorf("teamtargets: the recovered members' notices: %w", err)
	}
	return stale, nil
}

func plansWouldAdvance(ctx context.Context, db schooldirectory.Querier, leadUserID, fy string) (bool, error) {
	rows, err := db.Query(ctx, `SELECT status, COALESCE(created_activity_ids, '[]'::jsonb) FROM target_catchup_plan
		WHERE pl_user_id = $1 AND fy = $2 AND status IN ('approved', 'scheduled', 'in_progress')`, leadUserID, fy)
	if err != nil {
		return false, fmt.Errorf("teamtargets: the catch-up plans: %w", err)
	}
	type plan struct {
		status string
		ids    []string
	}
	plans := []plan{}
	for rows.Next() {
		var p plan
		var raw []byte
		if err := rows.Scan(&p.status, &raw); err != nil {
			rows.Close()
			return false, err
		}
		_ = json.Unmarshal(raw, &p.ids)
		plans = append(plans, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return false, err
	}
	for _, p := range plans {
		if len(p.ids) == 0 {
			continue
		}
		next, err := planStatus(ctx, db, p.ids)
		if err != nil {
			return false, err
		}
		if next != "" && next != p.status {
			return true, nil
		}
	}
	return false, nil
}

// planStatus is the status sync_completion would give a plan: completed
// when every live activity is done, in progress once one has started, ""
// when it would leave the plan as it is.
func planStatus(ctx context.Context, db schooldirectory.Querier, ids []string) (string, error) {
	rows, err := db.Query(ctx, `SELECT status FROM activity WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return "", fmt.Errorf("teamtargets: the recovery activities: %w", err)
	}
	defer rows.Close()
	live, found := []string{}, false
	for rows.Next() {
		var s string
		if err := rows.Scan(&s); err != nil {
			return "", err
		}
		found = true
		if !slices.Contains(rules.NotInPlan, s) {
			live = append(live, s)
		}
	}
	if err := rows.Err(); err != nil || !found {
		return "", err
	}
	done := len(live) > 0
	started := false
	for _, s := range live {
		if !slices.Contains(rules.CompletedStatuses, s) {
			done = false
		}
		if !slices.Contains(rules.NotStarted, s) {
			started = true
		}
	}
	switch {
	case done:
		return "completed", nil
	case started:
		return "in_progress", nil
	}
	return "", nil
}
