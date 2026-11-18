package partneroversight

import (
	"context"
	"fmt"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The withdrawal queue (partner_oversight_service.withdrawal_requests):
// requests a CCEO raised about work a Partner has already scheduled,
// waiting on the supervising Programme Lead's decision.

// request is one withdrawal request as the queue words it.
type request struct {
	school, partner, kind, reason, attribution string
	explanation, note, disposition             string
	countsAgainst, locked                      bool
	plannedCost                                int64
}

// readRequests is withdrawal_requests for the reader's lens: a team's,
// addressed to its leads (staff); a region's, by its school or its
// hand-over's cluster (regions); the country's (both nil). Oldest first,
// at most a hundred.
func readRequests(ctx context.Context, db schooldirectory.Querier, staff, regions []string) ([]request, error) {
	rows, err := db.Query(ctx, `
SELECT COALESCE(s.name, ''), COALESCE(p.name, ''), w.kind, w.reason_category, w.attribution,
  w.partner_facing_reason, w.internal_note, w.disposition, w.financial_state_at_withdrawal = 'locked',
  w.original_planned_cost
FROM partner_assignment_withdrawal w
LEFT JOIN school s ON s.id = w.school_id
LEFT JOIN partner p ON p.id = w.partner_id
LEFT JOIN partner_assignment wa ON wa.id = w.assignment_id LEFT JOIN cluster wc ON wc.id = wa.cluster_id
WHERE w.state = $1 AND ($2::text[] IS NULL OR w.supervising_pl_id = ANY($2))
  AND ($3::text[] IS NULL OR s.region_id = ANY($3) OR wc.region_id = ANY($3))
ORDER BY w.requested_at, w.id LIMIT 100`, rules.WithdrawalRequested, staff, regions)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the withdrawal requests: %w", err)
	}
	defer rows.Close()
	w := rules.Work.Withdrawal
	out := []request{}
	for rows.Next() {
		var r request
		var kind, reason, attribution, disposition string
		if err := rows.Scan(&r.school, &r.partner, &kind, &reason, &attribution, &r.explanation, &r.note,
			&disposition, &r.locked, &r.plannedCost); err != nil {
			return nil, fmt.Errorf("partneroversight: reading the withdrawal requests: %w", err)
		}
		r.kind = labelOr(w.Labels, kind)
		r.reason = labelOr(w.ReasonLabels, reason)
		r.attribution = labelOr(w.AttributionLabels, attribution)
		r.disposition = labelOr(w.DispositionLabels, disposition)
		r.countsAgainst = attribution == "partner"
		out = append(out, r)
	}
	return out, rows.Err()
}

// labelOr is a choice's label (get_FOO_display), the stored value where it
// names no choice.
func labelOr(labels map[string]string, value string) string {
	if l, ok := labels[value]; ok {
		return l
	}
	return value
}

// requestBlocks is the queue as the feed reads it: its heading, then a
// panel for each request (the reader without the decision is told whose it
// is).
func (v *workView) requestBlocks() []*screensv1.PageBlock {
	text := func(t string) *screensv1.PagePanelItem {
		return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title:  fmt.Sprintf("Withdrawal requests (%d)", len(v.requests)),
		Badges: []*screensv1.PageBadge{},
		Items:  []*screensv1.PagePanelItem{text("Raised by a CCEO about work a partner has already scheduled. Your decision.")},
	}}}}
	for _, r := range v.requests {
		items := []*screensv1.PagePanelItem{text(r.school + " · " + r.partner)}
		line := r.kind + " · " + r.reason
		if !r.countsAgainst {
			line += " · " + r.attribution
		}
		items = append(items, text(line), text(r.explanation))
		if r.note != "" {
			items = append(items, text("Note: "+r.note))
		}
		next := "Proposed next: " + r.disposition
		if r.plannedCost != 0 {
			next += " · UGX " + intcomma(r.plannedCost) + " planned"
		}
		if r.locked {
			next += " · Committed money"
		}
		items = append(items, text(next))
		if !v.w.role.ReviewsWithdrawals {
			items = append(items, text("Awaiting the supervising Programme Lead's decision."))
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Badges: []*screensv1.PageBadge{}, Items: items,
		}}})
	}
	return out
}
