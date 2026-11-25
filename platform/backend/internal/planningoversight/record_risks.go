package planningoversight

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// RecordRiskKeys is build_item_by_reference with risk_service.annotate, as
// the delegated-action sweep asks it: the keys of the risks one record
// carries today (a day at UTC midnight). found is false when the record is
// gone, or is a hand-over the Partner has since scheduled or that has left
// the Partner (the condition cannot still hold).
func (s *Service) RecordRiskKeys(ctx context.Context, kind, id string, today time.Time) ([]string, bool, error) {
	switch kind {
	case "activity":
		a, err := s.readOneAct(ctx, id, nil, nil)
		if err != nil || a == nil {
			return nil, false, err
		}
		it, err := s.oneItem(ctx, a)
		if err != nil {
			return nil, false, err
		}
		keys := []string{}
		for _, r := range risksFor(it, today) {
			keys = append(keys, r.key)
		}
		return keys, true, nil
	case "assignment":
		c := rules.TeamPlan.Coverage
		var created *time.Time
		var partner string
		err := s.db.QueryRow(ctx, `SELECT pa.created_at, COALESCE(pt.name, '') FROM partner_assignment pa
LEFT JOIN partner pt ON pt.id = pa.partner_id
WHERE pa.id = $1 AND pa.status = ANY($2) AND NOT (pa.status = ANY($3) OR (pa.status = 'returned_to_staff' AND pa.resolved_at IS NOT NULL))`,
			id, c.AssignmentStatuses, c.LeftPartnerStatuses).Scan(&created, &partner)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, false, nil
		}
		if err != nil {
			return nil, false, fmt.Errorf("planningoversight: the hand-over: %w", err)
		}
		keys := []string{}
		if r, late := partnerNotScheduled(partner, "", utcDay(created), today); late {
			keys = append(keys, r.key)
		}
		return keys, true, nil
	}
	return nil, false, nil
}
