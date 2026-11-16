package cpdlearning

import (
	"context"
	"fmt"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// request is one PD request with what the dashboard reads of it.
type request struct {
	id, staffID, staffName, position, supervisor, country, course, courseType string
	status, funding, currency                                                 string
	requested, accounted                                                      int64
	start, end                                                                time.Time
	updated, created                                                          time.Time
	markedComplete, acctSubmitted, acctReviewed                               *time.Time
	certExpected, bamboo                                                      bool
}

const requestColumns = `id, staff_id, staff_name, COALESCE(position, ''), COALESCE(supervisor_name, ''), country,
  course_name, course_type, status, funding_type, currency, requested_amount_cents, COALESCE(accounted_amount, 0),
  start_date, end_date, updated_at, created_at, marked_complete_at, accountability_submitted_at,
  accountability_reviewed_at, certification_expected, bamboohr_uploaded`

func scanRequest(row pgx.CollectableRow) (request, error) {
	var r request
	err := row.Scan(&r.id, &r.staffID, &r.staffName, &r.position, &r.supervisor, &r.country,
		&r.course, &r.courseType, &r.status, &r.funding, &r.currency, &r.requested, &r.accounted,
		&r.start, &r.end, &r.updated, &r.created, &r.markedComplete, &r.acctSubmitted,
		&r.acctReviewed, &r.certExpected, &r.bamboo)
	return r, err
}

type reader struct {
	db schooldirectory.Querier
	sc scope
	fy string
}

// filtered is the page's filters on a table with a staff_id column: the
// year, the reader's scope, the country and the role
// (get_dashboard's alloc_qs and req_qs).
func (r reader) filtered(country, role string) (string, []any) {
	args := []any{r.fy}
	where, args := r.sc.where("staff_id", args)
	where = "fy = $1 AND " + where
	if country != "" {
		args = append(args, country)
		where += fmt.Sprintf(" AND country = $%d", len(args))
	}
	if role != "" {
		args = append(args, role)
		where += fmt.Sprintf(` AND staff_id IN (
  SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND u.active_role = $%d)`, len(args))
	}
	return where, args
}

// requests is req_qs, latest change first.
func (r reader) requests(ctx context.Context, country, role string) ([]request, error) {
	where, args := r.filtered(country, role)
	rows, err := r.db.Query(ctx, `SELECT `+requestColumns+` FROM pd_request
WHERE `+where+` AND status <> '`+statusDraft+`' ORDER BY updated_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the requests: %w", err)
	}
	out, err := pgx.CollectRows(rows, scanRequest)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the requests: %w", err)
	}
	return out, nil
}

// allocation is one person's year's allocation.
type allocation struct {
	staffID, currency string
	cents             int64
}

// allocations is alloc_qs, in the order its first() reads it.
func (r reader) allocations(ctx context.Context, country, role string) ([]allocation, error) {
	where, args := r.filtered(country, role)
	rows, err := r.db.Query(ctx, `SELECT staff_id, currency, annual_allocation FROM pd_allocation
WHERE `+where+` ORDER BY id`, args...)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the allocations: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (allocation, error) {
		var a allocation
		err := row.Scan(&a.staffID, &a.currency, &a.cents)
		return a, err
	})
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the allocations: %w", err)
	}
	return out, nil
}

// spent is StaffPDService.committed_and_accounted_cents for each person: the
// commitments not yet accounted for and every accounted spend, over all of
// their requests of the year.
func (r reader) spent(ctx context.Context, staffIDs []string) (map[string]int64, error) {
	out := map[string]int64{}
	if len(staffIDs) == 0 {
		return out, nil
	}
	rows, err := r.db.Query(ctx, `
SELECT staff_id,
  SUM(CASE WHEN status = ANY($3) AND COALESCE(accounted_amount, 0) = 0 THEN requested_amount_cents ELSE 0 END)
  + SUM(COALESCE(accounted_amount, 0))
FROM pd_request WHERE fy = $1 AND staff_id = ANY($2) GROUP BY staff_id`, r.fy, staffIDs, rules.CommittedStatuses)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading what is spent: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var cents int64
		if err := rows.Scan(&id, &cents); err != nil {
			return nil, fmt.Errorf("cpdlearning: reading what is spent: %w", err)
		}
		out[id] = cents
	}
	return out, rows.Err()
}

// waitingOnOthers is whether a request waits at the supervisor stage that
// is not the reader's own: the supervisor queue, which Go does not draw.
func waitingOnOthers(ctx context.Context, db schooldirectory.Querier, profileID string) (bool, error) {
	var waiting bool
	err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM pd_request WHERE status = $1 AND staff_id <> $2)`,
		statusSupervisor, profileID).Scan(&waiting)
	if err != nil {
		return false, fmt.Errorf("cpdlearning: reading the supervisor queue: %w", err)
	}
	return waiting, nil
}

// countryOptions is the countries of the people in the reader's scope.
func (r reader) countryOptions(ctx context.Context) ([]string, error) {
	where, args := r.sc.where("id", nil)
	countries, err := strings1(ctx, r.db, `SELECT DISTINCT country FROM staff_profile
WHERE deleted_at IS NULL AND country <> '' AND `+where, args...)
	if err != nil {
		return nil, err
	}
	sort.Strings(countries)
	return countries, nil
}

// certifiedClosed is how many of the closed courses have an uploaded
// certificate.
func (r reader) certifiedClosed(ctx context.Context, closed []string) (int, error) {
	if len(closed) == 0 {
		return 0, nil
	}
	var n int
	err := r.db.QueryRow(ctx, `SELECT COUNT(DISTINCT request_id) FROM pd_certificate
WHERE request_id = ANY($1) AND status = $2`, closed, certificateUploaded).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("cpdlearning: reading the certificates: %w", err)
	}
	return n, nil
}

// person is one PD-eligible staff member with their fund position.
type person struct {
	staffID, name, role, country string
	cents                        int64
	currency                     string
	req                          *request
	certificateID                string
}

// people is staff_fund_rows before it is sorted and drawn: every scoped,
// PD-eligible staff member by name, their latest live request of the year,
// its certificate and their allocation (their own, else their role's).
func (r reader) people(ctx context.Context, country, role string) ([]person, error) {
	args := []any{eligibleRoles()}
	where, args := r.sc.where("sp.id", args)
	if country != "" {
		args = append(args, country)
		where += fmt.Sprintf(" AND sp.country = $%d", len(args))
	}
	if role != "" {
		args = append(args, role)
		where += fmt.Sprintf(" AND u.active_role = $%d", len(args))
	}
	rows, err := r.db.Query(ctx, `
SELECT sp.id, u.name, u.active_role, COALESCE(sp.country, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.active_role = ANY($1) AND `+where+` ORDER BY u.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the eligible staff: %w", err)
	}
	people, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (person, error) {
		var p person
		err := row.Scan(&p.staffID, &p.name, &p.role, &p.country)
		return p, err
	})
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the eligible staff: %w", err)
	}
	ids := make([]string, len(people))
	for i, p := range people {
		ids[i] = p.staffID
	}
	latest, err := r.latest(ctx, ids)
	if err != nil {
		return nil, err
	}
	reqIDs := []string{}
	for _, req := range latest {
		reqIDs = append(reqIDs, req.id)
	}
	certificates, err := r.certificates(ctx, reqIDs)
	if err != nil {
		return nil, err
	}
	own, defaults, err := r.envelopes(ctx, ids)
	if err != nil {
		return nil, err
	}
	for i := range people {
		p := &people[i]
		p.cents, p.currency = 0, defaultCurrency
		if a, ok := own[p.staffID]; ok {
			p.cents, p.currency = a.cents, a.currency
		} else if a, ok := defaults[[2]string{p.role, p.country}]; ok {
			p.cents, p.currency = a.cents, a.currency
		}
		if req, ok := latest[p.staffID]; ok {
			p.req = &req
			p.certificateID = certificates[req.id]
		}
	}
	return people, nil
}

// latest is each person's latest request of the year that leaves them
// applied (neither a draft nor rejected, cancelled or withdrawn).
func (r reader) latest(ctx context.Context, ids []string) (map[string]request, error) {
	out := map[string]request{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := r.db.Query(ctx, `SELECT `+requestColumns+` FROM pd_request
WHERE fy = $1 AND staff_id = ANY($2) AND NOT (status = ANY($3)) ORDER BY created_at`, r.fy, ids, rules.NotAppliedStatuses)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the latest requests: %w", err)
	}
	reqs, err := pgx.CollectRows(rows, scanRequest)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the latest requests: %w", err)
	}
	for _, req := range reqs {
		out[req.staffID] = req
	}
	return out, nil
}

// certificates is each request's latest certificate not returned.
func (r reader) certificates(ctx context.Context, reqIDs []string) (map[string]string, error) {
	out := map[string]string{}
	if len(reqIDs) == 0 {
		return out, nil
	}
	rows, err := r.db.Query(ctx, `SELECT request_id, id FROM pd_certificate
WHERE request_id = ANY($1) AND status <> 'returned' ORDER BY created_at`, reqIDs)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the certificates: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var req, id string
		if err := rows.Scan(&req, &id); err != nil {
			return nil, fmt.Errorf("cpdlearning: reading the certificates: %w", err)
		}
		out[req] = id
	}
	return out, rows.Err()
}

// envelopes is each person's own allocation of the year and the roles'
// defaults by role and country.
func (r reader) envelopes(ctx context.Context, ids []string) (map[string]allocation, map[[2]string]allocation, error) {
	own := map[string]allocation{}
	if len(ids) > 0 {
		rows, err := r.db.Query(ctx, `SELECT staff_id, currency, annual_allocation FROM pd_allocation
WHERE fy = $1 AND staff_id = ANY($2)`, r.fy, ids)
		if err != nil {
			return nil, nil, fmt.Errorf("cpdlearning: reading the allocations: %w", err)
		}
		list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (allocation, error) {
			var a allocation
			err := row.Scan(&a.staffID, &a.currency, &a.cents)
			return a, err
		})
		if err != nil {
			return nil, nil, fmt.Errorf("cpdlearning: reading the allocations: %w", err)
		}
		for _, a := range list {
			own[a.staffID] = a
		}
	}
	defaults, err := r.roleDefaults(ctx, "")
	if err != nil {
		return nil, nil, err
	}
	byKey := map[[2]string]allocation{}
	for _, d := range defaults {
		byKey[[2]string{d.role, d.country}] = d.allocation
	}
	return own, byKey, nil
}

// roleDefault is one role's default allocation in one country.
type roleDefault struct {
	role, country string
	allocation
}

// roleDefaults is the year's PDRoleAllocation rows, in one country when
// country is given.
func (r reader) roleDefaults(ctx context.Context, country string) ([]roleDefault, error) {
	sql := `SELECT role, country, currency, annual_allocation_cents FROM pd_role_allocation WHERE fy = $1`
	args := []any{r.fy}
	if country != "" {
		sql += ` AND country = $2`
		args = append(args, country)
	}
	rows, err := r.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the role allocations: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (roleDefault, error) {
		var d roleDefault
		err := row.Scan(&d.role, &d.country, &d.currency, &d.cents)
		return d, err
	})
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the role allocations: %w", err)
	}
	return out, nil
}

// roleCounts is how many of the reader's scoped staff in the country hold
// each role.
func (r reader) roleCounts(ctx context.Context, country string) (map[string]int, error) {
	args := []any{country}
	where, args := r.sc.where("sp.id", args)
	rows, err := r.db.Query(ctx, `
SELECT u.active_role, COUNT(*) FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND sp.country = $1 AND `+where+` GROUP BY u.active_role`, args...)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: counting the roles: %w", err)
	}
	defer rows.Close()
	out := map[string]int{}
	for rows.Next() {
		var role *string
		var n int
		if err := rows.Scan(&role, &n); err != nil {
			return nil, fmt.Errorf("cpdlearning: counting the roles: %w", err)
		}
		if role != nil {
			out[*role] = n
		}
	}
	return out, rows.Err()
}
