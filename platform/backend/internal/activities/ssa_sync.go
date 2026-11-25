package activities

// The ssa_recommendation_sync job (apps.realtime.jobs._do_ssa_recommendation_sync):
// sync_recommendations (each operating school whose latest confirmed
// assessment has no recommendations gets them, as the confirmation handler
// gives them; then each live plan with a focus that answers no
// recommendation is linked to the open ones it answers), and
// judge_unjudged_plans (each live plan of the year with no SSA verdict is
// judged as it stands today, marked backfilled, and linked). Inside the
// caller's transaction.
//
// The activity saves the existing job makes run the Core package mirror; on
// consistent data that mirror changes nothing (the save that last wrote the
// work's status, date and school ran it), so Go does not run it here. A plan
// Go cannot judge yet (a cluster session, or work filed under a project no
// SSA intervention measures, which the existing verdict reads differently)
// is passed over, logged, for the existing job.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

var (
	// syncLiveStatuses are sync_recommendations' live plan statuses.
	syncLiveStatuses = []string{"planned", "scheduled", "rescheduled", "assigned_to_partner", "partner_scheduled",
		"in_progress", "completion_started"}
	// livePlanStatuses are LIVE_PLAN_STATUSES.
	livePlanStatuses         = append(append([]string{}, syncLiveStatuses...), "awaiting_owner_approval")
	openRecommendationStates = []string{"generated", "accepted", "deferred"}
	operatingSchoolStatuses  = []string{"active", "reopened"}
)

// SyncSSARecommendations is the job; it says what the existing job counts:
// recommendations made, plans linked, plans judged and plans they linked.
//
// The plans it saves are returned: each save's package credit follows the
// commit (CreditSchoolActivity), as Activity.save queues it.
func SyncSSARecommendations(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, logger *slog.Logger) (int, []string, error) {
	fy := schooldirectory.OperationalFY(now.In(kampala))
	side := &packageSide{kampala: kampala}
	created, err := generateMissing(ctx, tx, now, kampala)
	if err != nil {
		return 0, nil, err
	}
	linked, err := linkLivePlans(ctx, tx, fy, now, side)
	if err != nil {
		return 0, nil, err
	}
	judged, judgedLinks, err := judgeUnjudged(ctx, tx, fy, now, kampala, logger, side)
	if err != nil {
		return 0, nil, err
	}
	return created + linked + judged + judgedLinks, side.saved, nil
}

// packageSide is Activity.save's package side for the plans a run saves:
// the slot mirror inside the save, the credit after the commit.
type packageSide struct {
	kampala *time.Location
	saved   []string
}

func (ps *packageSide) afterSave(ctx context.Context, tx pgx.Tx, activityID string, now time.Time) error {
	if err := MirrorSlots(ctx, tx, activityID, ps.kampala, now); err != nil {
		return err
	}
	if !slices.Contains(ps.saved, activityID) {
		ps.saved = append(ps.saved, activityID)
	}
	return nil
}

// generateMissing is sync_recommendations' first half, by school code.
func generateMissing(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location) (int, error) {
	rows, err := tx.Query(ctx, `
SELECT latest.id FROM school s
CROSS JOIN LATERAL (SELECT r.id FROM ssa_record r WHERE r.school_id = s.id AND r.verification_status = 'confirmed'
  AND r.deleted_at IS NULL ORDER BY r.date_of_ssa DESC, r.created_at DESC LIMIT 1) latest
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1)
  AND NOT EXISTS (SELECT 1 FROM ssa_recommendation x WHERE x.ssa_record_id = latest.id)
ORDER BY s.school_id`, operatingSchoolStatuses)
	if err != nil {
		return 0, fmt.Errorf("activities: reading the schools with no recommendations: %w", err)
	}
	var records []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return 0, err
		}
		records = append(records, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	created := 0
	for _, id := range records {
		n, err := generateFor(ctx, tx, id, now, kampala)
		if err != nil {
			return created, err
		}
		created += n
	}
	return created, nil
}

// livePlan is one plan as linking and judging read it.
type livePlan struct {
	id, status, kind, focus                    string
	schoolID, clusterID, recommendation, owner *string
	projectID, itemID, deviation, reason       *string
	planned                                    *time.Time
	collects                                   bool
	source                                     map[string]any
	sourceSSA                                  *string
	sourceScore                                *float64
}

// linkLivePlans is sync_recommendations' second half.
func linkLivePlans(ctx context.Context, tx pgx.Tx, fy string, now time.Time, side *packageSide) (int, error) {
	plans, err := readPlans(ctx, tx, `a.deleted_at IS NULL AND a.fy = $1 AND a.status = ANY($2)
  AND COALESCE(a.focus_intervention, '') <> ''
  AND NOT EXISTS (SELECT 1 FROM ssa_recommendation x WHERE x.planned_activity_id = a.id)`,
		// The model's order, newest first: of two plans answering one need,
		// the newer takes it.
		"a.created_at DESC", fy, syncLiveStatuses)
	if err != nil {
		return 0, err
	}
	linked := 0
	for i := range plans {
		n, err := linkRecommendations(ctx, tx, &plans[i], now, false, side)
		if err != nil {
			return linked, err
		}
		linked += n
	}
	return linked, nil
}

func readPlans(ctx context.Context, tx pgx.Tx, where, order string, args ...any) ([]livePlan, error) {
	rows, err := tx.Query(ctx, `SELECT a.id, a.status, a.activity_type, COALESCE(a.focus_intervention, ''), NULLIF(a.school_id, ''),
  NULLIF(a.cluster_id, ''), NULLIF(a.ssa_recommendation_id, ''), a.responsible_staff_id, NULLIF(a.project_id, ''),
  a.catalogue_item_id, a.ssa_deviation_reason, a.recommendation_reason, a.planned_date, a.ssa_collection_expected,
  COALESCE(a.recommendation_source, '{}'::jsonb), NULLIF(a.source_ssa_id, ''), a.source_score
FROM activity a WHERE `+where+` ORDER BY `+order, args...)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the live plans: %w", err)
	}
	defer rows.Close()
	var out []livePlan
	for rows.Next() {
		var p livePlan
		if err := rows.Scan(&p.id, &p.status, &p.kind, &p.focus, &p.schoolID, &p.clusterID, &p.recommendation, &p.owner,
			&p.projectID, &p.itemID, &p.deviation, &p.reason, &p.planned, &p.collects, &p.source, &p.sourceSSA,
			&p.sourceScore); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// linkRecommendations is link_recommendations: the open recommendations of
// the plan's school (or a cluster session's invited schools) for its focus
// marked planned by it, the school plan pointed at the first, audited.
//
// markLedger is whether the save marks the owner's ledger: the sync reads its
// live plans with their owner and date deferred (.only), so the existing
// ledger handler finds neither and marks nothing; a judged plan is read whole.
func linkRecommendations(ctx context.Context, tx pgx.Tx, p *livePlan, now time.Time, markLedger bool, side *packageSide) (int, error) {
	if p.focus == "" {
		return 0, nil
	}
	var schools []string
	switch {
	case p.schoolID != nil:
		schools = []string{*p.schoolID}
	case p.clusterID != nil:
		ids, err := clusterSchoolIDs(ctx, tx, p.id, *p.clusterID)
		if err != nil {
			return 0, err
		}
		schools = ids
	default:
		return 0, nil
	}
	rows, err := tx.Query(ctx, `SELECT id FROM ssa_recommendation WHERE school_id = ANY($1) AND intervention = $2
  AND state = ANY($3) ORDER BY school_id, created_at DESC`, schools, p.focus, openRecommendationStates)
	if err != nil {
		return 0, fmt.Errorf("activities: reading the recommendations a plan answers: %w", err)
	}
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return 0, err
		}
		ids = append(ids, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(ids) == 0 {
		return 0, err
	}
	if _, err := tx.Exec(ctx, `UPDATE ssa_recommendation SET state = 'planned', planned_activity_id = $1, decided_at = $2,
  updated_at = $2 WHERE id = ANY($3)`, p.id, now, ids); err != nil {
		return 0, fmt.Errorf("activities: planning the recommendations: %w", err)
	}
	if p.schoolID != nil && p.recommendation == nil {
		if _, err := tx.Exec(ctx, `UPDATE activity SET ssa_recommendation_id = $2, updated_at = $3 WHERE id = $1`,
			p.id, ids[0], now); err != nil {
			return 0, fmt.Errorf("activities: pointing the plan at its recommendation: %w", err)
		}
		if err := side.afterSave(ctx, tx, p.id, now); err != nil {
			return 0, err
		}
		first := ids[0]
		p.recommendation = &first
		if markLedger {
			if err := markOwnerLedger(ctx, tx, p, now); err != nil {
				return 0, err
			}
		}
	}
	listed := make([]any, 0, min(len(ids), 200))
	for _, id := range ids[:min(len(ids), 200)] {
		listed = append(listed, id)
	}
	empty := ""
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "ssa.recommendation_planned", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(p.id),
		ActorID: audit.Text("system"), ActorRole: &empty, Success: true,
		Payload: map[string]any{"recommendationIds": listed, "intervention": p.focus, "status": p.status},
	}, now); err != nil {
		return 0, fmt.Errorf("activities: auditing the plan's recommendations: %w", err)
	}
	return len(ids), nil
}

// clusterSchoolIDs is _cluster_school_ids: the session's invited schools,
// else the cluster's operating schools.
func clusterSchoolIDs(ctx context.Context, tx pgx.Tx, activityID, clusterID string) ([]string, error) {
	read := func(sql string, arg string) ([]string, error) {
		rows, err := tx.Query(ctx, sql, arg)
		if err != nil {
			return nil, fmt.Errorf("activities: reading the session's schools: %w", err)
		}
		defer rows.Close()
		var out []string
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				return nil, err
			}
			out = append(out, id)
		}
		return out, rows.Err()
	}
	invited, err := read(`SELECT school_id FROM cluster_activity_attendance WHERE activity_id = $1 AND invited`, activityID)
	if err != nil || len(invited) > 0 {
		return invited, err
	}
	return read(`SELECT id FROM school WHERE cluster_id = $1 AND deleted_at IS NULL AND operational_status = ANY('{active,reopened}')`,
		clusterID)
}

// markOwnerLedger is the ledger mark an activity save leaves (apps.targets.
// ledger_sync), for a type some target area counts: its owner and year are
// rebuilt on the next read.
func markOwnerLedger(ctx context.Context, tx pgx.Tx, p *livePlan, now time.Time) error {
	if p.owner == nil || *p.owner == "" || p.planned == nil || !targets.CreditedActivityType(p.kind) {
		return nil
	}
	if _, err := tx.Exec(ctx, `INSERT INTO target_ledger_dirty (owner_id, fy, marked_at) VALUES ($1, $2, $3)
ON CONFLICT (owner_id, fy) DO UPDATE SET marked_at = EXCLUDED.marked_at`, *p.owner,
		schooldirectory.OperationalFY(*p.planned), now); err != nil {
		return fmt.Errorf("activities: marking the owner's ledger: %w", err)
	}
	return nil
}

// judgeUnjudged is judge_unjudged_plans for the year.
func judgeUnjudged(ctx context.Context, tx pgx.Tx, fy string, now time.Time, kampala *time.Location,
	logger *slog.Logger, side *packageSide) (int, int, error) {
	plans, err := readPlans(ctx, tx, `a.deleted_at IS NULL AND a.fy = $1 AND a.status = ANY($2) AND a.ssa_alignment = ''`,
		"a.planned_date, a.id", fy, livePlanStatuses)
	if err != nil {
		return 0, 0, err
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, tx, schoolprofile.GateRules())
	if err != nil {
		return 0, 0, err
	}
	judged, linked := 0, 0
	for i := range plans {
		p := &plans[i]
		if p.schoolID == nil || (p.projectID != nil && slices.Contains(outside, *p.projectID)) {
			if logger != nil {
				logger.WarnContext(ctx, "activities: an unjudged plan is left for the existing job", "activity", p.id)
			}
			continue
		}
		if err := judgePlan(ctx, tx, p, now, kampala, side); err != nil {
			return judged, linked, err
		}
		n, err := linkRecommendations(ctx, tx, p, now, true, side)
		if err != nil {
			return judged, linked, err
		}
		judged++
		linked += n
	}
	return judged, linked, nil
}

// judgePlan is assess then stamp(link=False) for a school plan.
func judgePlan(ctx context.Context, tx pgx.Tx, p *livePlan, now time.Time, kampala *time.Location, side *packageSide) error {
	var clusterID string
	if err := tx.QueryRow(ctx, `SELECT COALESCE(cluster_id, '') FROM school WHERE id = $1`, *p.schoolID).Scan(&clusterID); err != nil &&
		!errors.Is(err, pgx.ErrNoRows) {
		return fmt.Errorf("activities: reading the plan's school: %w", err)
	}
	need, err := schoolNeedOf(ctx, pgNeed{tx}, *p.schoolID, clusterID, now)
	if err != nil {
		return err
	}
	var modes []string
	if p.itemID != nil && *p.itemID != "" {
		rows, err := tx.Query(ctx, `SELECT DISTINCT mapping_mode FROM activity_intervention_mapping
WHERE catalogue_item_id = $1 AND active`, *p.itemID)
		if err != nil {
			return fmt.Errorf("activities: reading the item's mappings: %w", err)
		}
		for rows.Next() {
			var m string
			if err := rows.Scan(&m); err != nil {
				rows.Close()
				return err
			}
			modes = append(modes, m)
		}
		rows.Close()
	}
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	ev := assess(p.kind, p.focus, "planner", modes, need, p.collects, today)
	ev.Data["backfilled"] = true
	reason := reasonFor(ev)
	ssa := map[string]any{}
	for k, v := range ev.Data {
		ssa[k] = v
	}
	ssa["reason"] = reason
	if p.deviation != nil && *p.deviation != "" {
		ssa["deviationReason"] = *p.deviation
	}
	source := map[string]any{}
	for k, v := range p.source {
		source[k] = v
	}
	source["ssa"] = ssa
	var (
		setSSA, setScore bool
		ssaID, band      any
		score            any
	)
	if school, ok := ev.Data["school"].(map[string]any); ok && school != nil && p.sourceSSA == nil {
		setSSA, ssaID = true, school["ssaId"]
		if focus, ok := school["focusScore"].(pyFloat); ok && p.sourceScore == nil {
			setScore, score, band = true, float64(focus), school["focusBand"]
		}
	}
	setReason := p.reason == nil || *p.reason == ""
	if _, err := tx.Exec(ctx, `SELECT gateway_ssa_judge.judge_unjudged_plan($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
		p.id, source, ev.Alignment, setSSA, ssaID, setScore, score, band, setReason, reason, now); err != nil {
		return fmt.Errorf("activities: recording the plan's SSA verdict: %w", err)
	}
	// A verdict alone is beside the package (BESIDE_THE_PACKAGE_FIELDS); the
	// SSA, score or reason it records with it is not.
	if setSSA || setScore || setReason {
		if err := side.afterSave(ctx, tx, p.id, now); err != nil {
			return err
		}
	}
	return markOwnerLedger(ctx, tx, p, now)
}
