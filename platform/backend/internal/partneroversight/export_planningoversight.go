package partneroversight

import (
	"context"
	"net/url"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Period is oversight_views._period_filters as readPeriod reads it, for
// another oversight page (internal/planningoversight) that reads the same
// period bar.
type Period struct {
	FY, Kind, Week, Quarter string
	Month                   int
}

// ReadPeriod is readPeriod: ok is false for a value whose reading Go does
// not copy (the existing application answers those).
func ReadPeriod(q url.Values, now time.Time) (Period, bool) {
	p, ok := readPeriod(q, now)
	return Period{FY: p.fy, Kind: p.kind, Week: p.week, Quarter: p.quarter, Month: p.month}, ok
}

// BothIDSpaces is bothIDSpaces (oversight_service._both_id_spaces).
func BothIDSpaces(ctx context.Context, db schooldirectory.Querier, ids []string) ([]string, error) {
	return bothIDSpaces(ctx, db, ids)
}
