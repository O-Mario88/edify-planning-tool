package oversightportfolio

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// school is one row of country_portfolio: the eight facts it is built from,
// its owner resolved, and what is planned on it.
type school struct {
	id, code, name   string
	districtID       string
	district         string
	clusterID        string
	clusterName      string
	officerID        string
	officerName      string
	leadID, leadName string
	activities       int
	visits           int
	trainings        int
	firstDate        *time.Time
	budget           int64
}

func (s school) planned() bool { return s.activities > 0 }

// statement numbers its parameters as Django would bind them.
type statement struct{ args []any }

func (st *statement) arg(v any) string {
	st.args = append(st.args, v)
	return "$" + strconv.Itoa(len(st.args))
}

// operatingClause is lifecycle_service.active_schools on the school table.
func (st *statement) operatingClause() string {
	return `"school"."deleted_at" IS NULL AND "school"."operational_status" = ANY(` + st.arg(rules.OperatingStatuses) + `)`
}

// reach is scoping.scoped_school_queryset(scope) in the shape Django writes
// it (a country boundary through a LEFT OUTER JOIN of region, as
// school_in_country_q does), so the rows reach the sort in the same order and
// schools of one name come out as the existing page lists them. ok is false
// for a reader who reaches no school (qs.none(): Django issues no statement).
func (st *statement) reach(s schooldirectory.Scope) (join, clause string, ok bool) {
	switch {
	case s.CountryScope:
		if s.Country == "" {
			return "", "", true
		}
		c := st.arg(s.Country)
		return `LEFT OUTER JOIN "region" ON ("school"."region_id" = "region"."id") `,
			`("region"."country" = ` + c + ` OR ("school"."id" IS NOT NULL AND "school"."region_id" IS NULL AND ("school"."account_owner_id" IN (SELECT U0."id" AS "id" FROM "staff_profile" U0 WHERE (U0."deleted_at" IS NULL AND U0."country" = ` + c + `)) OR "school"."account_owner_id" IS NULL OR "school"."account_owner_id" = '' OR "school"."account_owner_id" IN (SELECT U0."id" AS "id" FROM "staff_profile" U0 WHERE (U0."deleted_at" IS NULL AND (U0."country" IS NULL OR U0."country" = ''))))))`,
			true
	case s.RegionScope:
		if len(s.RegionIDs) == 0 {
			return "", "", false
		}
		return "", `"school"."region_id" = ANY(` + st.arg(s.RegionIDs) + `)`, true
	case s.SummaryOnly:
		if len(s.RegionIDs) > 0 {
			return "", `"school"."region_id" = ANY(` + st.arg(s.RegionIDs) + `)`, true
		}
		return "", "", true
	case len(s.SchoolIDs) > 0:
		return "", `"school"."id" = ANY(` + st.arg(s.SchoolIDs) + `)`, true
	}
	return "", "", false
}

// readSchools is country_portfolio's school statement: the operating schools
// in reach, in the district asked for, by name.
func readSchools(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, district string) ([]school, error) {
	st := &statement{}
	join, clause, ok := st.reach(s)
	if !ok {
		return nil, nil
	}
	where := `"school"."deleted_at" IS NULL AND ` + st.operatingClause()
	if clause != "" {
		where += " AND " + clause
	}
	where += " AND " + st.operatingClause()
	if district != "" && district != "all" && district != "All" {
		where += ` AND "school"."district_id" = ` + st.arg(district)
	}
	sql := `SELECT "school"."id", COALESCE("school"."school_id", ''), "school"."name", COALESCE("school"."district_id", ''), COALESCE("district"."name", ''), COALESCE("school"."cluster_id", ''), COALESCE("school"."account_owner_id", '') FROM "school" ` +
		join + `LEFT OUTER JOIN "district" ON ("school"."district_id" = "district"."id") WHERE (` + where + `) ORDER BY 3 ASC`
	rows, err := q.Query(ctx, sql, st.args...)
	if err != nil {
		return nil, fmt.Errorf("oversightportfolio: reading the schools: %w", err)
	}
	defer rows.Close()
	out := []school{}
	for rows.Next() {
		var r school
		var owner string
		if err := rows.Scan(&r.id, &r.code, &r.name, &r.districtID, &r.district, &r.clusterID, &owner); err != nil {
			return nil, fmt.Errorf("oversightportfolio: reading the schools: %w", err)
		}
		if r.districtID == "" {
			r.district = ""
		}
		r.officerID = owner // resolved by resolveOwners
		out = append(out, r)
	}
	return out, rows.Err()
}

// owner is one entry of _staff_directory.
type owner struct{ officerID, officerName, leadID, leadName string }

func holdsRole(activeRole string, roles []string, role string) bool {
	return activeRole == role || slices.Contains(roles, role)
}

// staffDirectory is _staff_directory: owner id (a StaffProfile id or its
// User id) to the officer and the Programme Lead they report to.
func staffDirectory(ctx context.Context, q schooldirectory.Querier, ownerIDs []string) (map[string]owner, error) {
	if len(ownerIDs) == 0 {
		return map[string]owner{}, nil
	}
	type profile struct {
		id, userID, name, activeRole string
		roles                        []string
	}
	rows, err := q.Query(ctx, `
SELECT p.id, COALESCE(p.user_id, ''), COALESCE(u.name, ''), COALESCE(u.active_role, ''), COALESCE(u.roles, '{}')
FROM staff_profile p LEFT OUTER JOIN "user" u ON p.user_id = u.id
WHERE (p.id = ANY($1) OR p.user_id = ANY($1)) AND p.deleted_at IS NULL`, ownerIDs)
	if err != nil {
		return nil, fmt.Errorf("oversightportfolio: reading the officers: %w", err)
	}
	profiles := []profile{}
	for rows.Next() {
		var p profile
		if err := rows.Scan(&p.id, &p.userID, &p.name, &p.activeRole, &p.roles); err != nil {
			rows.Close()
			return nil, fmt.Errorf("oversightportfolio: reading the officers: %w", err)
		}
		profiles = append(profiles, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	ids := make([]string, len(profiles))
	for i, p := range profiles {
		ids[i] = p.id
	}
	leads := map[string][2]string{}
	if len(ids) > 0 {
		links, err := q.Query(ctx, `
SELECT a.supervisee_id, T3.id, COALESCE("user".name, ''), COALESCE("user".email, ''), COALESCE("user".active_role, ''), COALESCE("user".roles, '{}')
FROM staff_supervisor_assignment a
INNER JOIN staff_profile T3 ON (a.supervisor_id = T3.id)
INNER JOIN "user" ON (T3.user_id = "user".id)
WHERE (a.supervisee_id = ANY($1) AND T3.deleted_at IS NULL)
ORDER BY "user".name ASC`, ids)
		if err != nil {
			return nil, fmt.Errorf("oversightportfolio: reading the reporting lines: %w", err)
		}
		for links.Next() {
			var supervisee, supervisor, name, email, activeRole string
			var roles []string
			if err := links.Scan(&supervisee, &supervisor, &name, &email, &activeRole, &roles); err != nil {
				links.Close()
				return nil, fmt.Errorf("oversightportfolio: reading the reporting lines: %w", err)
			}
			if _, done := leads[supervisee]; done || !holdsRole(activeRole, roles, rules.ProgramLeadRole) {
				continue
			}
			label := name
			if label == "" {
				label = email
			}
			if label == "" {
				label = rules.UnassignedLabel
			}
			leads[supervisee] = [2]string{supervisor, label}
		}
		links.Close()
		if err := links.Err(); err != nil {
			return nil, err
		}
	}
	directory := map[string]owner{}
	for _, p := range profiles {
		name := ""
		if p.userID != "" {
			name = p.name
		}
		if name == "" {
			name = p.id
		}
		lead, ok := leads[p.id]
		if !ok && p.userID != "" && holdsRole(p.activeRole, p.roles, rules.ProgramLeadRole) {
			lead, ok = [2]string{p.id, name}, true
		}
		entry := owner{officerID: p.id, officerName: name, leadID: rules.NoLeadKey, leadName: rules.NoLeadLabel}
		if ok {
			entry.leadID, entry.leadName = lead[0], lead[1]
		}
		directory[p.id] = entry
		if p.userID != "" {
			directory[p.userID] = entry
		}
	}
	return directory, nil
}

// readPlanning is _planning_by_school: each school's live activities in the
// years the page reads, counted and costed.
func readPlanning(ctx context.Context, q schooldirectory.Querier, rows []school, years []string) error {
	if len(rows) == 0 {
		return nil
	}
	ids := make([]string, len(rows))
	index := make(map[string][]int, len(rows))
	for i, r := range rows {
		ids[i] = r.id
		index[r.id] = append(index[r.id], i)
	}
	plan, err := q.Query(ctx, `
SELECT school_id, COUNT(id), COUNT(id) FILTER (WHERE activity_type = ANY($3)),
       COUNT(id) FILTER (WHERE activity_type = ANY($4)), MIN(planned_date)
FROM activity
WHERE deleted_at IS NULL AND fy = ANY($2) AND school_id = ANY($1) AND NOT (status = ANY($5))
GROUP BY school_id`, ids, years, rules.VisitTypes, rules.TrainingTypes, rules.DeadStatuses)
	if err != nil {
		return fmt.Errorf("oversightportfolio: reading the plans: %w", err)
	}
	for plan.Next() {
		var id string
		var activities, visits, trainings int
		var first *time.Time
		if err := plan.Scan(&id, &activities, &visits, &trainings, &first); err != nil {
			plan.Close()
			return fmt.Errorf("oversightportfolio: reading the plans: %w", err)
		}
		for _, i := range index[id] {
			rows[i].activities, rows[i].visits, rows[i].trainings, rows[i].firstDate = activities, visits, trainings, first
		}
	}
	plan.Close()
	if err := plan.Err(); err != nil {
		return err
	}
	costs, err := q.Query(ctx, `
SELECT a.school_id, COALESCE(SUM(c.amount), 0)::bigint
FROM activity_schedule_cost_line c INNER JOIN activity a ON (c.activity_id = a.id)
WHERE a.deleted_at IS NULL AND a.fy = ANY($2) AND a.school_id = ANY($1) AND NOT (a.status = ANY($3))
GROUP BY 1`, ids, years, rules.DeadStatuses)
	if err != nil {
		return fmt.Errorf("oversightportfolio: reading the costs: %w", err)
	}
	defer costs.Close()
	for costs.Next() {
		var id string
		var total int64
		if err := costs.Scan(&id, &total); err != nil {
			return fmt.Errorf("oversightportfolio: reading the costs: %w", err)
		}
		for _, i := range index[id] {
			if rows[i].activities > 0 {
				rows[i].budget = total
			}
		}
	}
	return costs.Err()
}

// readClusters is _cluster_names: live clusters' names by id.
func readClusters(ctx context.Context, q schooldirectory.Querier, rows []school) (map[string]string, error) {
	ids := []string{}
	for _, r := range rows {
		if r.clusterID != "" && !slices.Contains(ids, r.clusterID) {
			ids = append(ids, r.clusterID)
		}
	}
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	res, err := q.Query(ctx, `SELECT id, COALESCE(name, '') FROM cluster WHERE deleted_at IS NULL AND id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("oversightportfolio: reading the clusters: %w", err)
	}
	defer res.Close()
	for res.Next() {
		var id, name string
		if err := res.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("oversightportfolio: reading the clusters: %w", err)
		}
		out[id] = name
	}
	return out, res.Err()
}

// portfolioRows is country_portfolio up to its rows: the schools in reach,
// each under its owner and lead, with what is planned on it.
func portfolioRows(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, district string, years []string) ([]school, error) {
	rows, err := readSchools(ctx, q, s, district)
	if err != nil || len(rows) == 0 {
		return rows, err
	}
	owners := []string{}
	for _, r := range rows {
		if r.officerID != "" && !slices.Contains(owners, r.officerID) {
			owners = append(owners, r.officerID)
		}
	}
	directory, err := staffDirectory(ctx, q, owners)
	if err != nil {
		return nil, err
	}
	if err := readPlanning(ctx, q, rows, years); err != nil {
		return nil, err
	}
	clusters, err := readClusters(ctx, q, rows)
	if err != nil {
		return nil, err
	}
	for i := range rows {
		r := &rows[i]
		r.clusterName = clusters[r.clusterID]
		if o, ok := directory[r.officerID]; ok && r.officerID != "" {
			r.officerID, r.officerName, r.leadID, r.leadName = o.officerID, o.officerName, o.leadID, o.leadName
		} else {
			r.officerID, r.officerName = rules.UnassignedKey, rules.UnassignedLabel
			r.leadID, r.leadName = rules.NoLeadKey, rules.NoLeadLabel
		}
	}
	return rows, nil
}
