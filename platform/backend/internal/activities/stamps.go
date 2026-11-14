package activities

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
)

// coverageStamp is _read_acting_for(actor), shared with the other writers
// of the audit chain (audit.CoverageStamp).
func coverageStamp(ctx context.Context, q Querier, actorUserID string, now time.Time) (map[string]any, error) {
	return audit.CoverageStamp(ctx, q, actorUserID, now)
}

// withStamps is the payload as log() leaves it: the cover merged in.
func withStamps(payload map[string]any, cover map[string]any) map[string]any {
	return audit.WithStamps(payload, cover)
}
