package myplan

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PairActivity is what pair_costing.pair_cost_notes reads of one activity,
// for the Work Plan's rows (internal/workplan).
type PairActivity struct {
	ID, Type     string
	PairedVisit  *string
	CostMissing  bool
	DeliveryMode *string
	HasLines     bool
}

// PairNotes is pair_costing.pair_cost_notes over acts: the note beside the
// UGX 0 half of each in-school pair, and an unpriced online training's.
func PairNotes(ctx context.Context, db schooldirectory.Querier, acts []PairActivity) (map[string]string, error) {
	in := make([]*activity, 0, len(acts))
	lines := costLines{}
	for _, a := range acts {
		in = append(in, &activity{
			id: a.ID, activityType: a.Type, pairedVisit: a.PairedVisit,
			costMissing: a.CostMissing, deliveryMode: a.DeliveryMode,
		})
		if a.HasLines {
			lines[a.ID] = []string{a.ID}
		}
	}
	return pairNotes(ctx, db, in, lines)
}
