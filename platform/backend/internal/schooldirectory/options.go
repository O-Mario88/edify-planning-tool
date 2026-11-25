package schooldirectory

import (
	"context"
	"fmt"
	"slices"
	"strconv"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func options(ctx context.Context, q Querier, sql string, args ...any) ([]*screensv1.DirectoryOption, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.DirectoryOption, error) {
		o := &screensv1.DirectoryOption{}
		err := row.Scan(&o.Value, &o.Label)
		return o, err
	})
}

// districtOptions and subCountyOptions are the filter's places: those the
// reader's schools sit in, or the whole reference list when they have none.
func districtOptions(ctx context.Context, q Querier, base *sqlb, hasSchools bool) ([]*screensv1.DirectoryOption, error) {
	if !hasSchools {
		return options(ctx, q, `SELECT id, name FROM district ORDER BY name`)
	}
	return options(ctx, q, `SELECT id, name FROM district WHERE id IN (SELECT s.district_id FROM school s WHERE `+
		base.where()+`) ORDER BY name`, base.args...)
}

func subCountyOptions(ctx context.Context, q Querier, base *sqlb, hasSchools bool, district string) ([]*screensv1.DirectoryOption, error) {
	switch {
	case district != "":
		return options(ctx, q, `SELECT id, name FROM sub_county WHERE district_id = $1 ORDER BY name`, district)
	case hasSchools:
		return options(ctx, q, `SELECT id, name FROM sub_county WHERE id IN (SELECT s.sub_county_id FROM school s WHERE `+
			base.where()+` AND s.sub_county_id IS NOT NULL) ORDER BY name`, base.args...)
	}
	return []*screensv1.DirectoryOption{}, nil
}

// bulkClusters are the bulk bar's clusters: every active cluster for a
// country reader, else those this person is responsible for, in either id
// space, or that their own schools are in (cluster_owner_ids, direct only).
func bulkClusters(ctx context.Context, q Querier, s Scope) ([]*screensv1.ActionChoice, error) {
	sql := `SELECT id, name FROM cluster WHERE deleted_at IS NULL AND status = 'active'`
	args := []any{}
	if !(s.CountryScope || s.SummaryOnly) {
		owners := uniq([]string{s.UserID, s.StaffID})
		sql += ` AND (responsible_staff_id IN (
  SELECT unnest(ARRAY[sp.id, sp.user_id]) FROM staff_profile sp WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))
  UNION SELECT unnest($1::varchar[]))
 OR id = ANY($2))`
		args = append(args, owners, s.OwnClusterIDs)
	}
	rows, err := q.Query(ctx, sql+` ORDER BY name`, args...)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading clusters: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.ActionChoice, error) {
		c := &screensv1.ActionChoice{}
		err := row.Scan(&c.Value, &c.Label)
		return c, err
	})
}

type allocation struct{ maximum, assigned int }

func (a allocation) remaining() int { return max(a.maximum-a.assigned, 0) }

// bulkProjects are the Add to project dialog's projects
// (assignable_projects, annotate_coordinator_names, annotate_allocations).
func bulkProjects(ctx context.Context, q Querier, p auth.Principal, s Scope) ([]*screensv1.BulkProjectChoice, error) {
	sql := `SELECT pr.id, pr.name, COALESCE(c.name, '') FROM project pr
LEFT JOIN (SELECT sp.id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL) c
  ON c.id = pr.manager_staff_id
WHERE pr.deleted_at IS NULL AND pr.status = ANY($1)`
	args := []any{rules.OpenProjectStatuses}
	switch {
	case s.CountryScope:
		if s.Country != "" {
			sql += ` AND (EXISTS (SELECT 1 FROM project_school_assignment pa JOIN school sc ON sc.id = pa.school_id
    JOIN region r ON r.id = sc.region_id WHERE pa.project_id = pr.id AND r.country = $2)
 OR pr.manager_staff_id IN (SELECT id FROM staff_profile WHERE country = $2 AND deleted_at IS NULL)
 OR (NOT EXISTS (SELECT 1 FROM project_school_assignment pa WHERE pa.project_id = pr.id)
     AND (pr.manager_staff_id IS NULL OR pr.manager_staff_id = '')))`
			args = append(args, s.Country)
		}
	case len(s.SchoolIDs) == 0 && s.StaffID == "":
		return []*screensv1.BulkProjectChoice{}, nil
	}
	rows, err := q.Query(ctx, sql+` ORDER BY pr.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading projects: %w", err)
	}
	type project struct{ id, name, coordinator string }
	projects, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (project, error) {
		var pr project
		err := row.Scan(&pr.id, &pr.name, &pr.coordinator)
		return pr, err
	})
	if err != nil {
		return nil, err
	}

	staff := p.StaffProfileID
	if in(rules.CapacityExemptRoles, p.ActiveRole) {
		staff = ""
	}
	mine := map[string]allocation{}
	managed := map[string]bool{}
	teamHeld := map[string]bool{}
	if staff != "" && len(projects) > 0 {
		rows, err := q.Query(ctx, `
SELECT c.project_id, c.max_schools,
  (SELECT count(*) FROM project_school_assignment pa WHERE pa.project_id = c.project_id AND pa.assigned_staff_id = c.staff_id)
FROM project_staff_capacity c JOIN project pr ON pr.id = c.project_id
WHERE c.staff_id = $1 AND pr.deleted_at IS NULL`, staff)
		if err != nil {
			return nil, fmt.Errorf("schooldirectory: reading allocations: %w", err)
		}
		for rows.Next() {
			var id string
			var a allocation
			if err := rows.Scan(&id, &a.maximum, &a.assigned); err != nil {
				rows.Close()
				return nil, err
			}
			mine[id] = a
		}
		rows.Close()
		projectIDs := []string{}
		for _, pr := range projects {
			projectIDs = append(projectIDs, pr.id)
		}
		managedIDs, err := strings1(ctx, q, `SELECT DISTINCT project_id FROM project_staff_capacity WHERE project_id = ANY($1)`, projectIDs)
		if err != nil {
			return nil, err
		}
		for _, id := range managedIDs {
			managed[id] = true
		}
		held, err := strings1(ctx, q, `
SELECT DISTINCT project_id FROM project_staff_capacity
WHERE project_id = ANY($1) AND staff_id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $2)`,
			managedIDs, staff)
		if err != nil {
			return nil, err
		}
		for _, id := range held {
			teamHeld[id] = true
		}
	}

	out := []*screensv1.BulkProjectChoice{}
	for _, pr := range projects {
		choice := &screensv1.BulkProjectChoice{Value: pr.id, Label: pr.name}
		if pr.coordinator != "" {
			choice.Label += " · " + pr.coordinator
		}
		a, has := mine[pr.id]
		var remaining *int32
		switch {
		case has && a.remaining() == 0:
			choice.Block = fmt.Sprintf("You have reached your allocation of %d schools for %s. No additional schools can be "+
				"added unless the Project Coordinator increases your allocation.", a.maximum, pr.name)
		case !has && teamHeld[pr.id]:
		case !has && managed[pr.id]:
			choice.Block = fmt.Sprintf("You have no school allocation for %s. Ask its Project Coordinator to set one.", pr.name)
			zero := int32(0)
			remaining = &zero
		}
		if has {
			r := int32(a.remaining())
			remaining = &r
			choice.Label += " · " + strconv.Itoa(a.remaining()) + " of " + strconv.Itoa(a.maximum) + " left"
		} else if choice.Block != "" {
			choice.Label += " · no allocation"
		}
		choice.Remaining = remaining
		out = append(out, choice)
	}
	return out, nil
}

// ── Owners ─────────────────────────────────────────────────────────────────

type owner struct{ profileID, name, plName string }

// ownerDirectory is owner_groups.owner_directory: each owner id, in either
// id space, with its name and Program Lead.
func ownerDirectory(ctx context.Context, q Querier, ownerIDs []string) (map[string]owner, error) {
	out := map[string]owner{}
	if len(ownerIDs) == 0 {
		return out, nil
	}
	rows, err := q.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, ''), COALESCE(u.active_role, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, ownerIDs)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading owners: %w", err)
	}
	type profile struct{ id, userID, name, role string }
	profiles, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (profile, error) {
		var pr profile
		err := row.Scan(&pr.id, &pr.userID, &pr.name, &pr.role)
		return pr, err
	})
	if err != nil {
		return nil, err
	}
	profileIDs := []string{}
	for _, pr := range profiles {
		profileIDs = append(profileIDs, pr.id)
	}
	leads := map[string]string{}
	rows, err = q.Query(ctx, `
SELECT a.supervisee_id, COALESCE(u.name, ''), COALESCE(u.active_role, '')
FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisor_id AND sp.deleted_at IS NULL
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisee_id = ANY($1)
ORDER BY u.name`, profileIDs)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading leads: %w", err)
	}
	for rows.Next() {
		var supervisee, name, role string
		if err := rows.Scan(&supervisee, &name, &role); err != nil {
			rows.Close()
			return nil, err
		}
		if _, seen := leads[supervisee]; role == roleProgramLead && !seen {
			leads[supervisee] = name
		}
	}
	rows.Close()
	for _, pr := range profiles {
		name := pr.name
		if name == "" {
			name = pr.id
		}
		pl := leads[pr.id]
		if pl == "" && pr.role == roleProgramLead {
			pl = name
		}
		entry := owner{profileID: pr.id, name: name, plName: pl}
		out[pr.id] = entry
		if pr.userID != "" {
			out[pr.userID] = entry
		}
	}
	return out, nil
}

// ownerRanking is owner_order's ranking: lead, then officer; owners with no
// profile last.
func ownerRanking(ownerIDs []string, directory map[string]owner) []string {
	const last = "￿"
	key := func(id string) [2]string {
		e, ok := directory[id]
		if !ok {
			return [2]string{last, last}
		}
		pl := e.plName
		if pl == "" {
			pl = last
		}
		return [2]string{pl, e.name}
	}
	ranked := append([]string{}, ownerIDs...)
	slices.SortStableFunc(ranked, func(a, b string) int {
		ka, kb := key(a), key(b)
		if ka[0] != kb[0] {
			if ka[0] < kb[0] {
				return -1
			}
			return 1
		}
		if ka[1] < kb[1] {
			return -1
		}
		if ka[1] > kb[1] {
			return 1
		}
		return 0
	})
	return ranked
}

// OwnerLeads is owner_directory's pl_name for each owner id (in either id
// space): the Programme Lead each person is filed under, "" for none.
func OwnerLeads(ctx context.Context, q Querier, ownerIDs []string) (map[string]string, error) {
	dir, err := ownerDirectory(ctx, q, ownerIDs)
	if err != nil {
		return nil, err
	}
	out := make(map[string]string, len(dir))
	for id, o := range dir {
		out[id] = o.plName
	}
	return out, nil
}
