package activities

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// groupNoneTicked is group_actions.selection's refusal for an empty tick.
const groupNoneTicked = "Tick at least one activity first."

// GroupSelection is group_actions.selection for the group reschedule and
// cancel drawers: the ticked activities the action changes and the ones it
// leaves with their reason, and for a cancel how many carry money already
// disbursed. It hands on exactly where GroupReschedule and GroupCancel hand
// on, so the drawer is Go's only when the save is. Reading writes nothing.
func (s *Service) GroupSelection(ctx context.Context, p auth.Principal, raw []string, cancel bool) (ready, left []GroupPick, moneyMoved int, err error) {
	given := 0
	for _, id := range raw {
		if strings.TrimSpace(id) != "" {
			given++
		}
	}
	if given == 0 {
		return nil, nil, 0, refuse(groupNoneTicked)
	}
	ids, err := groupIDs(raw)
	if err != nil {
		return nil, nil, 0, err
	}
	if p.InActingAppointment || p.StaffProfileID == "" || in(rules.Doors.Requesters, p.ActiveRole) ||
		(!cancel && rules.CalendarBlocksRefuse) {
		return nil, nil, 0, handOn("not the owner acting on their own visits")
	}
	// selection drops an id that matches no activity without a word: it did
	// not come from a tick box on a page the reader was shown. None left is
	// the drawer's "None of the selected activities can be ...".
	if ids, err = s.existingActivities(ctx, ids); err != nil || len(ids) == 0 {
		return nil, nil, 0, err
	}
	statuses := movableStatuses
	if cancel {
		statuses = cancellableStatuses
	}
	picks, err := s.groupPicks(ctx, p, ids, statuses, !cancel)
	if err != nil {
		return nil, nil, 0, err
	}
	var readyIDs []string
	for _, pick := range picks {
		if cancel && in(offPlanStatuses, pick.a.status) {
			pick.Refusal = groupAlreadyOff
			left = append(left, pick.GroupPick)
			continue
		}
		ready = append(ready, pick.GroupPick)
		readyIDs = append(readyIDs, pick.ActivityID)
	}
	if cancel && len(readyIDs) > 0 {
		if err := s.db.QueryRow(ctx, `SELECT count(DISTINCT activity_id) FROM advance_request
WHERE activity_id = ANY($1) AND status = ANY($2)`, readyIDs, rules.Cancel.MoneyMovedAdvanceStatuses).Scan(&moneyMoved); err != nil {
			return nil, nil, 0, fmt.Errorf("activities: reading the disbursed advances: %w", err)
		}
	}
	return ready, left, moneyMoved, nil
}

// existingActivities are the ids that name a live activity, in their order.
func (s *Service) existingActivities(ctx context.Context, ids []string) ([]string, error) {
	rows, err := s.db.Query(ctx, `SELECT id FROM activity WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the ticked activities: %w", err)
	}
	found, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	kept := []string{}
	for _, id := range ids {
		if in(found, id) {
			kept = append(kept, id)
		}
	}
	return kept, nil
}
