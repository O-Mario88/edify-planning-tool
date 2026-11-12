package schooldirectory

import "context"

// ScopeGeography is _derive_from_schools' cluster_ids and district_ids: the
// clusters and districts of every live school in the scope, a lead's team's
// included. Cluster Oversight reads through them
// (cluster_queryset(scope) without direct_only), where the Clusters page
// reads the direct portfolio's (OwnClusterIDs, OwnDistrictIDs).
func ScopeGeography(ctx context.Context, q Querier, s Scope) (clusters, districts []string, err error) {
	return ownGeography(ctx, q, s.SchoolIDs)
}
