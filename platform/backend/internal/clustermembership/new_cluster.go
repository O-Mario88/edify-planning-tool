package clustermembership

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// notReadable is get_scoped_object_or_404's PermissionDenied.
const notReadable = "Access Denied: Your active role or assigned portfolio scope does not permit accessing this record."

// IntoNewCluster is create_cluster_view's assign_school_id: the school the
// reader may read, put into the cluster just made through assign_school. It
// answers the school's name once it joined, or the refusal's words.
func (s *Service) IntoNewCluster(ctx context.Context, p auth.Principal, clusterID, schoolID string, origin activities.Origin) (string, string, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return "", "", err
	}
	var args []any
	arg := numbered(&args)
	var t ticked
	var code, owner *string
	err = s.db.QueryRow(ctx, `SELECT s.id, s.name, s.school_id, s.account_owner_id FROM school s
WHERE `+schooldirectory.ReadScope(scope, arg)+` AND s.deleted_at IS NULL AND s.id = `+arg(schoolID)+` LIMIT 1`, args...).
		Scan(&t.ID, &t.Name, &code, &owner)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", notReadable, nil
	}
	if err != nil {
		return "", "", fmt.Errorf("clustermembership: reading the school to put in the new cluster: %w", err)
	}
	t.Code, t.AccountOwner = deref(code), deref(owner)
	access, err := s.access.ProfileAccess(ctx, p, clusterID)
	if err != nil {
		return "", "", err
	}
	if !access.Readable {
		return "", notReadable, nil
	}
	var name string
	if err := s.db.QueryRow(ctx, `SELECT name FROM cluster WHERE id = $1 AND deleted_at IS NULL`, clusterID).Scan(&name); err != nil {
		return "", "", fmt.Errorf("clustermembership: reading the new cluster: %w", err)
	}
	refusal, err := s.assignSchool(ctx, p, scope, &Cluster{ID: clusterID, Name: name}, t, origin)
	if err != nil || refusal != "" {
		return "", refusal, err
	}
	return t.Name, "", nil
}
