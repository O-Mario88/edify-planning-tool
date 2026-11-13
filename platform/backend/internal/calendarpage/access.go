package calendarpage

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// tickable is group_actions.tickable_ids for a member of staff: live work
// they hold themselves (responsible for it, or monitoring it) and may run.
func tickable(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope, rows []*activity) (map[string]bool, error) {
	out := map[string]bool{}
	if !rules.Roles[p.ActiveRole].MyPlan {
		return out, nil
	}
	mine := ownerIDs(p)
	for _, a := range rows {
		if in(rules.Untickable, a.status) {
			continue
		}
		if !slices.Contains(mine, a.staffID) && !slices.Contains(mine, a.monitorID) {
			continue
		}
		may, err := schoolprofile.MayRun(ctx, db, p, scope, schoolprofile.RunnableActivity{
			StaffID: a.staffID, MonitorID: a.monitorID, SchoolID: a.schoolID, SchoolOwner: a.schoolOwner,
			HasSchool: a.hasSchool, ClusterID: a.clusterID, ClusterDistrict: a.clusterDistrict,
			ClusterLead: a.clusterLead, ClusterLive: a.clusterLive, InCountry: a.inCountry,
		})
		if err != nil {
			return nil, err
		}
		if may {
			out[a.id] = true
		}
	}
	return out, nil
}

// unopened is the work on somebody else's calendar whose record the reader
// is refused (RolePermissionService.can_view_record): it is drawn as a
// plain entry, not a link. A school in the reader's scope opens.
func unopened(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope, rows []*activity, now time.Time) (map[string]bool, error) {
	out := map[string]bool{}
	if scope.CountryScope || p.ActiveRole == rules.AdminRole {
		return out, nil
	}
	v := viewer{db: db, p: p, scope: scope, now: now}
	for _, a := range rows {
		if a.schoolID != "" && slices.Contains(scope.SchoolIDs, a.schoolID) {
			continue
		}
		ok, err := v.canView(ctx, a)
		if err != nil {
			return nil, err
		}
		if !ok {
			out[a.id] = true
		}
	}
	return out, nil
}

type viewer struct {
	db    schooldirectory.Querier
	p     auth.Principal
	scope schooldirectory.Scope
	now   time.Time
	team  []string
	read  bool
}

// canView is can_view_record for an activity, for a member of staff with
// no country scope.
func (v *viewer) canView(ctx context.Context, a *activity) (bool, error) {
	owners := ownerIDs(v.p)
	if slices.Contains(owners, a.staffID) || slices.Contains(owners, a.monitorID) {
		return true, nil
	}
	if a.staffID != "" && a.staffID != v.p.UserID {
		var covering bool
		err := v.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM temporary_coverage_assignment t
  JOIN staff_profile c ON c.id = t.covering_staff_id JOIN staff_profile o ON o.id = t.original_staff_id
  WHERE c.user_id = $1 AND o.user_id = $2 AND t.start_datetime <= $3 AND t.end_datetime >= $3 AND t.status = 'active')`,
			v.p.UserID, a.staffID, v.now).Scan(&covering)
		if err != nil {
			return false, fmt.Errorf("calendarpage: reading cover: %w", err)
		}
		if covering {
			return true, nil
		}
	}
	return v.supervisedClusterActivity(ctx, a)
}

// supervisedClusterActivity is RolePermissionService._supervised_cluster_activity:
// work with no school belonging to somebody the reader supervises, in a
// cluster they may read.
func (v *viewer) supervisedClusterActivity(ctx context.Context, a *activity) (bool, error) {
	if a.schoolID != "" || len(v.scope.SupervisedStaffIDs) == 0 {
		return false, nil
	}
	team, err := v.teamIDs(ctx)
	if err != nil {
		return false, err
	}
	if !(a.staffID != "" && slices.Contains(team, a.staffID)) && !(a.monitorID != "" && slices.Contains(team, a.monitorID)) {
		return false, nil
	}
	if a.clusterID == "" {
		return true, nil
	}
	if !a.hasCluster || !a.clusterLive {
		return false, nil
	}
	return clusterpage.ClusterReadable(ctx, v.db, v.scope, a.clusterID, a.clusterLead, a.clusterDistrict, a.clusterRegion)
}

// teamIDs is oversight_service._both_id_spaces of the reader's supervisees.
func (v *viewer) teamIDs(ctx context.Context) ([]string, error) {
	if v.read {
		return v.team, nil
	}
	ids := slices.Clone(v.scope.SupervisedStaffIDs)
	rows, err := v.db.Query(ctx, `
SELECT id, user_id FROM staff_profile WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1))`, v.scope.SupervisedStaffIDs)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the team's ids: %w", err)
	}
	defer rows.Close()
	asked := slices.Clone(ids)
	for rows.Next() {
		var id, userID string
		if err := rows.Scan(&id, &userID); err != nil {
			return nil, fmt.Errorf("calendarpage: reading the team's ids: %w", err)
		}
		// A profile asked for by its id adds its account; one asked for by
		// its account adds its profile.
		if slices.Contains(asked, id) && userID != "" && !slices.Contains(ids, userID) {
			ids = append(ids, userID)
		}
		if slices.Contains(asked, userID) && !slices.Contains(ids, id) {
			ids = append(ids, id)
		}
	}
	v.team, v.read = ids, true
	return ids, rows.Err()
}
