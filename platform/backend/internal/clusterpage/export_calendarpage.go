package clusterpage

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ClusterReadable is scoping.cluster_in_scope(scope, cluster) for a live
// cluster, for the Calendar's links on a team member's calendar
// (internal/calendarpage).
func ClusterReadable(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, id, owner, districtID, regionID string) (bool, error) {
	return readable(ctx, q, s, clusterRef{id: id, owner: owner, districtID: districtID, regionID: regionID})
}
