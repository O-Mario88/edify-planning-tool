package workplan

import (
	"context"
	"time"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// NextOpenFY is fy_policy.next_open_fy at noon of today in zone, or "" when
// no later year is open, for another page that opens on the planning year
// (the Planning Monitor), in the request's country.
func NextOpenFY(ctx context.Context, db schooldirectory.Querier, place *registry.Work, today time.Time, zone *time.Location) (string, error) {
	return nextOpenFY(ctx, db, place, today, zone)
}
