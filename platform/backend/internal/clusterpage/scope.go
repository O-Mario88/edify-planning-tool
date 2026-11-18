package clusterpage

import (
	"context"
	"fmt"
	"strings"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// sqlb gathers a statement's numbered arguments.
type sqlb struct{ args []any }

func (b *sqlb) arg(v any) string {
	b.args = append(b.args, v)
	return fmt.Sprintf("$%d", len(b.args))
}

// ownerIDs is scoping.cluster_owner_ids(scope, direct_only=True): the
// reader's user and staff profile ids, each matched to the other id space
// through the live staff profiles, since a cluster's owner is filed under
// either.
func ownerIDs(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope) ([]string, error) {
	ids := []string{}
	for _, id := range []string{s.UserID, s.StaffID} {
		if id != "" && !in(ids, id) {
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return nil, nil
	}
	rows, err := q.Query(ctx, `
SELECT id, COALESCE(user_id, '') FROM staff_profile
WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1))`, ids)
	if err != nil {
		return nil, fmt.Errorf("clusterpage: reading the owner ids: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var profileID, userID string
		if err := rows.Scan(&profileID, &userID); err != nil {
			return nil, err
		}
		for _, id := range []string{profileID, userID} {
			if id != "" && !in(ids, id) {
				ids = append(ids, id)
			}
		}
	}
	return ids, rows.Err()
}

// inScope is scoping.cluster_queryset(scope, direct_only=True) over the
// clusters aliased c: a country reader's country (the cluster's region, or
// its district's), the whole deployment for a summary reader, and otherwise
// the clusters this person is responsible for, those of their own schools,
// and the ownerless ones in their own schools' districts.
func (b *sqlb) inScope(s schooldirectory.Scope, owners []string) string {
	switch {
	case s.CountryScope:
		if s.Country == "" {
			return "TRUE"
		}
		// Read through the registry (docs/migration/80, §16).
		return registry.ClusterIn("c", b.arg(s.CountryIDs()))
	case s.SummaryOnly:
		return "TRUE"
	}
	return fmt.Sprintf(`(c.responsible_staff_id = ANY(%s) OR c.id = ANY(%s)
  OR ((c.responsible_staff_id IS NULL OR c.responsible_staff_id = '') AND c.district_id = ANY(%s)))`,
		b.arg(nonNil(owners)), b.arg(nonNil(s.OwnClusterIDs)), b.arg(nonNil(s.OwnDistrictIDs)))
}

func nonNil(ids []string) []string {
	if ids == nil {
		return []string{}
	}
	return ids
}

// likeContains is Django's icontains pattern: the value escaped and wrapped.
func likeContains(value string) string {
	r := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`)
	return "%" + r.Replace(value) + "%"
}
