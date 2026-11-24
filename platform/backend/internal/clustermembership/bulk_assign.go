package clustermembership

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The School Directory's bulk Assign cluster (school_views.
// bulk_assign_cluster_view, read by the feed's run_bulk).

// bulkAssignMessages are the view's messages as run_bulk reads them.
func bulkAssignMessages(assigned int, cluster string, skipped []string) *screensv1.BulkActionResult {
	warnings := []string{}
	if len(skipped) > 0 {
		warnings = append(warnings, "Skipped already-clustered schools: "+strings.Join(skipped, ", ")+".")
	}
	if assigned == 0 {
		return &screensv1.BulkActionResult{Error: "No unclustered schools were selected.", Warnings: warnings}
	}
	return &screensv1.BulkActionResult{Saved: true, Warnings: warnings,
		Message: fmt.Sprintf("Successfully assigned %d schools to cluster '%s'.", assigned, cluster)}
}

// BulkAssign is bulk_assign_cluster_view's POST: each ticked school of the
// reader's own that is not clustered joins the cluster through assign_school.
// A refusal ends the press with its words, as the view's exception does, and
// the schools before it stay in the cluster.
func (s *Service) BulkAssign(ctx context.Context, p auth.Principal, schoolIDs []string, clusterID string, origin activities.Origin) (*screensv1.BulkActionResult, error) {
	clusterID = strings.TrimSpace(clusterID)
	if len(schoolIDs) == 0 || clusterID == "" {
		return &screensv1.BulkActionResult{Error: "Failed to perform assignment: missing fields."}, nil
	}
	if p.InActingAppointment {
		return nil, ErrHandOn
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, err
	}
	if scope.CountryScope || scope.SummaryOnly {
		return nil, ErrHandOn
	}
	var c Cluster
	err = s.db.QueryRow(ctx, `SELECT id, name FROM cluster WHERE id = $1 AND deleted_at IS NULL`, clusterID).Scan(&c.ID, &c.Name)
	if errors.Is(err, pgx.ErrNoRows) {
		return &screensv1.BulkActionResult{Error: "Not found."}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("clustermembership: reading the cluster: %w", err)
	}
	var args []any
	arg := numbered(&args)
	rows, err := s.db.Query(ctx, `SELECT s.id, s.name, COALESCE(s.school_id, ''), COALESCE(s.cluster_id, ''), COALESCE(s.cluster_status, ''),
  COALESCE(s.account_owner_id, '')
FROM school s WHERE `+schooldirectory.DirectPortfolio(scope, arg)+` AND s.deleted_at IS NULL AND s.id = ANY(`+arg(schoolIDs)+`)
ORDER BY s.created_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("clustermembership: reading the ticked schools: %w", err)
	}
	schools, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (ticked, error) {
		var t ticked
		return t, r.Scan(&t.ID, &t.Name, &t.Code, &t.ClusterID, &t.Status, &t.AccountOwner)
	})
	if err != nil {
		return nil, err
	}
	skipped, fresh := []string{}, []ticked{}
	for _, t := range schools {
		if t.Status == "clustered" {
			skipped = append(skipped, t.Name)
			continue
		}
		fresh = append(fresh, t)
	}
	for _, t := range fresh {
		refusal, err := s.assignSchool(ctx, p, scope, &c, t, "", origin)
		if err != nil {
			return nil, err
		}
		if refusal != "" {
			return &screensv1.BulkActionResult{Error: refusal}, nil
		}
	}
	return bulkAssignMessages(len(fresh), c.Name, skipped), nil
}
