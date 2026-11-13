package partneroversight

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// member is one team-member tab: its key (a StaffProfile id) and name.
type member struct{ key, name string }

// bothIDSpaces is oversight_service._both_id_spaces: each id with the User
// id of the live StaffProfile it names and the live StaffProfile of the User
// it names (an activity names its officer in either).
func bothIDSpaces(ctx context.Context, db schooldirectory.Querier, ids []string) ([]string, error) {
	out := []string{}
	for _, id := range ids {
		if id != "" && !contains(out, id) {
			out = append(out, id)
		}
	}
	if len(out) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
SELECT COALESCE(user_id, '') FROM staff_profile WHERE deleted_at IS NULL AND id = ANY($1)
UNION ALL
SELECT id FROM staff_profile WHERE deleted_at IS NULL AND user_id = ANY($1)`, out)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading both id spaces: %w", err)
	}
	defer rows.Close()
	expanded := append([]string{}, out...)
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("partneroversight: reading both id spaces: %w", err)
		}
		if id != "" && !contains(expanded, id) {
			expanded = append(expanded, id)
		}
	}
	return expanded, rows.Err()
}

// anyPartnerWork is whether anything the page could list, count or ask
// about sits within reach of ids for the years it reads: a handover the
// Partner still holds (build_items), Partner work made without one
// (_unassigned_partner_activities), a group training a Partner facilitates
// (facilitated_trainings), a withdrawal waiting on a decision
// (withdrawal_requests), or a school the reader's Planning Monitor follows
// (the Partner target behind the first tile). The years are fy alone, or fy
// and every later year when forward (planning_horizon reads the
// operational year forward). Each condition is at least as wide as the
// page's own (no period or status narrows it, and an unscheduled handover
// counts whatever its date), so when it finds nothing the page has nothing
// either.
func anyPartnerWork(ctx context.Context, db schooldirectory.Querier, ids, schoolIDs []string, fy string, forward bool) (bool, error) {
	var found bool
	err := db.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1 FROM partner_assignment pa
  LEFT JOIN school s ON s.id = pa.school_id
  LEFT JOIN cluster c ON c.id = pa.cluster_id
  LEFT JOIN activity sa ON sa.id = pa.scheduled_activity_id
  WHERE (pa.monitoring_staff_id = ANY($1) OR pa.assigning_staff_id = ANY($1)
     OR s.account_owner_id = ANY($1) OR c.responsible_staff_id = ANY($1))
    AND NOT (pa.status = ANY($5) OR (pa.status = $6 AND pa.resolved_at IS NOT NULL))
    AND (pa.scheduled_activity_id IS NULL OR sa.id IS NULL
      OR sa.fy = $3 OR ($4 AND sa.fy > $3))
) OR EXISTS (
  SELECT 1 FROM activity a
  LEFT JOIN school s ON s.id = a.school_id
  LEFT JOIN cluster c ON c.id = a.cluster_id
  WHERE a.deleted_at IS NULL AND (a.fy = $3 OR ($4 AND a.fy > $3)) AND (
    (a.delivery_type = $2 AND COALESCE(a.assigned_partner_id, '') <> ''
      AND (a.monitored_by_staff_id = ANY($1) OR a.responsible_staff_id = ANY($1)
        OR s.account_owner_id = ANY($1) OR c.responsible_staff_id = ANY($1)))
    OR (COALESCE(a.facilitating_partner_id, '') <> ''
      AND (a.responsible_staff_id = ANY($1) OR c.responsible_staff_id = ANY($1))))
) OR EXISTS (
  SELECT 1 FROM partner_assignment_withdrawal w
  WHERE w.state = $7 AND w.supervising_pl_id = ANY($1)
) OR EXISTS (
  SELECT 1 FROM school s
  WHERE s.deleted_at IS NULL AND (s.account_owner_id = ANY($1) OR s.id = ANY($8))
)`, ids, rules.PartnerDelivery, fy, forward, rules.LeftPartnerStatuses, rules.ReturnedToStaff,
		rules.WithdrawalRequested, schoolIDs).Scan(&found)
	if err != nil {
		return false, fmt.Errorf("partneroversight: reading the reader's partner work: %w", err)
	}
	return found, nil
}

// anyEngagement is whether the partnership register would hold a row or a
// count for a Programme Lead (engagements_visible_to: their own) or a
// Regional Lead observation asking for work with a partner
// (open_observation_follow_ups), read wider than the register does.
func anyEngagement(ctx context.Context, db schooldirectory.Querier, userID string) (bool, error) {
	var found bool
	err := db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM partner_engagement e WHERE e.author_id = $1)
    OR EXISTS (SELECT 1 FROM cce_regional_engagement r WHERE r.recommendation = ANY($2))`,
		userID, rules.PartnerActionRecommendations).Scan(&found)
	if err != nil {
		return false, fmt.Errorf("partneroversight: reading the partnership register: %w", err)
	}
	return found, nil
}

// isRosterLead is whether the reader leads a team in the planning roster
// (country_oversight.rules.roster): a live profile on a live, active account
// whose planning role is Programme Lead. monitor_roster files the reader's
// own team only then, and the Planning Monitor behind the first tile has
// people to total.
func isRosterLead(ctx context.Context, db schooldirectory.Querier, ownIDs []string) (bool, error) {
	var lead bool
	err := db.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1 FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND u.is_active AND u.deleted_at IS NULL
    AND (sp.id = ANY($1) OR sp.user_id = ANY($1))
    AND ($2 = ANY(COALESCE(u.roles, '{}')) OR u.active_role = $2))`, ownIDs, rules.PlanningLeadRole).Scan(&lead)
	if err != nil {
		return false, fmt.Errorf("partneroversight: reading the planning roster: %w", err)
	}
	return lead, nil
}

// roster is oversight_service.program_lead_members(team_lead_user_id): the
// Programme Lead the reader's account is (the first live profile holding the
// role, by key), then everyone with a reporting line to them, by name.
func roster(ctx context.Context, db schooldirectory.Querier, userID string) ([]member, error) {
	if userID == "" {
		return nil, nil
	}
	var leadID, name string
	err := db.QueryRow(ctx, `
SELECT sp.id, COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = $1 OR sp.user_id = $1)
  AND (u.active_role = $2 OR $2 = ANY(COALESCE(u.roles, '{}')))
ORDER BY sp.id LIMIT 1`, userID, rules.RosterLeadRole).Scan(&leadID, &name)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, fmt.Errorf("partneroversight: reading the team's Lead: %w", err)
	}
	out := []member{{key: leadID, name: name}}
	rows, err := db.Query(ctx, `
SELECT sp.id, COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisee_id
JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisor_id = $1 AND a.supervisee_id <> a.supervisor_id
ORDER BY u.name, a.supervisee_id`, leadID)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the team: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var m member
		if err := rows.Scan(&m.key, &m.name); err != nil {
			return nil, fmt.Errorf("partneroversight: reading the team: %w", err)
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func contains(list []string, v string) bool {
	for _, item := range list {
		if item == v {
			return true
		}
	}
	return false
}
