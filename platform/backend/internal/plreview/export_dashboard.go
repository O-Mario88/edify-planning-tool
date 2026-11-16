package plreview

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Waiting is pl_review.services.waiting_count: how many completions wait on
// this reviewer (the Programme Lead dashboard's Completed work to confirm).
func (s *Service) Waiting(ctx context.Context, p auth.Principal) (int, error) {
	rows, err := s.queue(ctx, p)
	return len(rows), err
}
