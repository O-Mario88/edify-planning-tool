package clusterpage

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// What the Cluster Profile (internal/schoolprofile) borrows from this page:
// who may read a cluster and act on it, and its school roster.

// Work a cluster has that is not work at all, and work not yet held
// (apps.clusters.services._NOT_WORK_STATUSES and _UNHELD_STATUSES).
var (
	notWorkStatuses = []string{"cancelled", "not_planned", "deferred"}
	unheldStatuses  = []string{"planned", "scheduled", "rescheduled", "assigned_to_partner", "partner_scheduled", "awaiting_owner_approval"}
)

// ProfileAccess is what p may do on the cluster's profile. A cluster that
// does not exist, or is outside p's scope, is simply not Readable.
func (s *Service) ProfileAccess(ctx context.Context, p auth.Principal, clusterID string) (schoolprofile.ClusterAccess, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return schoolprofile.ClusterAccess{}, err
	}
	var c clusterRef
	err = s.db.QueryRow(ctx, `
SELECT id, COALESCE(name, ''), COALESCE(responsible_staff_id, ''), COALESCE(district_id, ''), COALESCE(region_id, '')
FROM cluster WHERE id = $1 AND deleted_at IS NULL`, clusterID).Scan(&c.id, &c.name, &c.owner, &c.districtID, &c.regionID)
	if errors.Is(err, pgx.ErrNoRows) {
		return schoolprofile.ClusterAccess{}, nil
	}
	if err != nil {
		return schoolprofile.ClusterAccess{}, fmt.Errorf("clusterpage: reading the cluster: %w", err)
	}
	ok, err := readable(ctx, s.db, scope, c)
	if err != nil || !ok {
		return schoolprofile.ClusterAccess{}, err
	}
	doors := rules.Doors[p.ActiveRole]
	access := schoolprofile.ClusterAccess{Readable: true, Plan: doors.Plan, AddSchools: doors.AddSchools}
	if !doors.Plan {
		return access, nil
	}
	if access.Edit, err = mayEdit(ctx, s.db, scope, c); err != nil {
		return access, err
	}
	if access.Edit {
		if access.DeleteBlock, err = deleteBlock(ctx, s.db, c); err != nil {
			return access, err
		}
	}
	return access, nil
}

// Roster is the cluster's school list as its card opens it, for p.
func (s *Service) Roster(ctx context.Context, p auth.Principal, clusterID, fy string) (*screensv1.GetPageResponse, error) {
	return s.schools(ctx, p, clusterID, url.Values{"fy": {fy}})
}

// mayEdit is services.may_edit_cluster_profile: an owned cluster by its
// owner or a country reader, an unowned one from the editor's own portfolio.
func mayEdit(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, c clusterRef) (bool, error) {
	if s.CountryScope {
		return true, nil
	}
	if owner := strings.TrimSpace(c.owner); owner != "" {
		owners, err := ownerIDs(ctx, q, s)
		if err != nil {
			return false, err
		}
		return in(owners, owner), nil
	}
	if s.SummaryOnly {
		return false, nil
	}
	return in(s.OwnClusterIDs, c.id) || (c.districtID != "" && in(s.OwnDistrictIDs, c.districtID)), nil
}

// deleteBlock is services.cluster_delete_block: why the cluster cannot be
// deleted, in the planner's words, or "".
func deleteBlock(ctx context.Context, q schooldirectory.Querier, c clusterRef) (string, error) {
	var work, pending int
	err := q.QueryRow(ctx, `
SELECT COUNT(*), COUNT(*) FILTER (WHERE status = ANY($3))
FROM activity WHERE cluster_id = $1 AND deleted_at IS NULL AND NOT (status = ANY($2))`,
		c.id, notWorkStatuses, unheldStatuses).Scan(&work, &pending)
	if err != nil {
		return "", fmt.Errorf("clusterpage: reading the cluster's work: %w", err)
	}
	if held := work - pending; held > 0 {
		plural := "s"
		if held == 1 {
			plural = ""
		}
		return fmt.Sprintf("%s has held %d meeting%s or training. A cluster with a record of work is kept — move its schools to another cluster instead.", c.name, held, plural), nil
	}
	if pending > 0 {
		return fmt.Sprintf("%s has %d scheduled meeting or training. Cancel or move it before deleting the cluster.", c.name, pending), nil
	}
	return "", nil
}
