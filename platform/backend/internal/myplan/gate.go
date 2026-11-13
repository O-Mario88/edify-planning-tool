package myplan

import (
	"context"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ownerIDs is scoping.owner_ids: both ids a person's work is filed under.
func ownerIDs(p auth.Principal) []string {
	out := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			out = append(out, id)
		}
	}
	return out
}

// plans is panel_views.plans_visits (rules.planning_role): a Programme Lead
// or a CCEO by any role held, whose page carries their own Planned and
// remaining, their training summary and a visit target.
func plans(p auth.Principal) bool {
	if p.ActiveRole == rules.ProgramLeadRole || p.ActiveRole == rules.CCEORole {
		return true
	}
	return in(p.Roles, rules.ProgramLeadRole) || in(p.Roles, rules.CCEORole)
}

// holdsAnything is whether the page Go draws for p would be missing
// something only the existing page draws: a training, or a cluster meeting
// delivering one, that they own or monitor, whatever its year or state (My
// Training Summary's group, in-school and partner rows,
// training_ceilings._training_q); a school they hold, a cluster they lead, a partner
// hand-over they made or follow that the Partner has not dated (My Training
// Summary's _handover_rows), a training ceiling set for them (Cluster
// Planning Status and My Training Summary); or a partner organisation the
// login is, or is a member of (the partner's own My Plan,
// scoping.resolve_partner_ids). Each is asked of every row, deleted or
// closed ones too: a page answered here is one with none of them. Their
// other work is counted, and the page is Go's only when the tables list
// none of it (ReadPlan).
//
// trains is the first of them alone (a training of their own): since piece
// 3e My Training Summary is drawn from internal/trainingsummary, so it no
// longer makes held.
func holdsAnything(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (held, trains bool, err error) {
	owners := ownerIDs(p)
	err = db.QueryRow(ctx, `SELECT
    EXISTS (SELECT 1 FROM activity a WHERE (a.monitored_by_staff_id = ANY($1) OR a.responsible_staff_id = ANY($1))
            AND (a.activity_type = ANY($3) OR (a.activity_type = ANY($4) AND a.meeting_kind = 'training'))),
    EXISTS (SELECT 1 FROM school s WHERE s.account_owner_id = ANY($1))
 OR EXISTS (SELECT 1 FROM cluster c WHERE c.responsible_staff_id = ANY($1))
 OR EXISTS (SELECT 1 FROM partner_assignment pa WHERE (pa.assigning_staff_id = ANY($1) OR pa.monitoring_staff_id = ANY($1))
            AND pa.status = ANY($5))
 OR EXISTS (SELECT 1 FROM training_ceiling tc WHERE tc.staff_id = ANY($1))
 OR EXISTS (SELECT 1 FROM partner pt WHERE pt.user_id = $2)
 OR EXISTS (SELECT 1 FROM partner_member pm WHERE pm.user_id = $2)`, owners, p.UserID, rules.Plan.SummaryTrainingTypes, rules.Plan.SummaryMeetingTypes, rules.Tables.OpenHandoverStatuses).Scan(&trains, &held)
	if err != nil {
		return false, false, fmt.Errorf("myplan: reading what the reader holds: %w", err)
	}
	return held, trains, nil
}
