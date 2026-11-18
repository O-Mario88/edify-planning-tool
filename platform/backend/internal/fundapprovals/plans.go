package fundapprovals

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// officer is one requester the approver reviews (_scoped_cceos), with both
// id spaces an activity may name them by.
type officer struct {
	staffID, userID, name string
}

func (o officer) holds(id string) bool { return id != "" && (id == o.staffID || id == o.userID) }

// team is _scoped_cceos: a Lead's supervisees; for the Country Director,
// every live, active holder of a role whose requests reach them (in their
// country when they have one); for a country Admin, every live officer.
func team(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope) ([]officer, error) {
	ids := scope.SupervisedStaffIDs
	var err error
	switch {
	case scope.Role == "Admin" && scope.CountryScope:
		ids, err = collect(ctx, db, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
			WHERE u.active_role = 'CCEO' AND sp.deleted_at IS NULL`)
	case scope.Role == "CountryDirector" && scope.CountryFromRegistry:
		// A country whose roles come from the registry (docs/migration/80,
		// §13): the people holding those roles there.
		ids, err = collect(ctx, db, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
			WHERE u.is_active AND sp.deleted_at IS NULL AND `+registry.HoldsRoleIn("u.id", "$2", "$1::varchar[]"),
			rules.CDApprovalRoles, scope.CountryID)
	case scope.Role == "CountryDirector":
		// Uganda's rule, kept to the accounts that belong to the country.
		ids, err = collect(ctx, db, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
			WHERE u.active_role = ANY($1) AND u.is_active AND sp.deleted_at IS NULL
			  AND ($2 = '' OR (sp.country = $2 AND `+registry.BelongsTo("u.id", "$3")+`))`, rules.CDApprovalRoles, scope.Country, scope.CountryID)
	}
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `
		SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '')
		FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
		WHERE sp.deleted_at IS NULL AND sp.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the team: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (officer, error) {
		var o officer
		err := r.Scan(&o.staffID, &o.userID, &o.name)
		if o.name == "" {
			o.name = "CCEO"
		}
		return o, err
	})
}

func collect(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([]string, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the team: %w", err)
	}
	out, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the team: %w", err)
	}
	return out, nil
}

// teamIDs is every id the team's work may name them by.
func teamIDs(officers []officer) []string {
	out := []string{}
	for _, o := range officers {
		for _, id := range []string{o.staffID, o.userID} {
			if id != "" {
				out = append(out, id)
			}
		}
	}
	return out
}

func userIDs(officers []officer) []string {
	out := []string{}
	for _, o := range officers {
		if o.userID != "" {
			out = append(out, o.userID)
		}
	}
	return out
}

// weekBase is the condition week_base puts on a cost line: the team's
// live, dated work of the year that has not been called off.
const weekBase = `
	FROM activity_schedule_cost_line l
	JOIN activity a ON a.id = l.activity_id
	WHERE a.responsible_staff_id = ANY($1) AND a.fy = $2 AND a.deleted_at IS NULL
	  AND l.week_start_date IS NOT NULL
	  AND NOT (a.status IN ('cancelled', 'rejected', 'deferred') AND a.status IS NOT NULL)`

// line is one of the week's cost lines with what the plan reads of its
// activity.
type line struct {
	amount                                        int64
	lineType, activityID, staffID                 string
	partnerLine, vendorPaid, catalogued           bool
	activityType, delivery, programme, status     string
	school, district, region                      string
	atSchool, hasDistrict, hasRegion, costMissing bool
	attended                                      int64
	planned, end                                  *time.Time
}

func weekLines(ctx context.Context, db schooldirectory.Querier, ids []string, fy string, week time.Time) ([]line, error) {
	rows, err := db.Query(ctx, `
		SELECT l.amount, COALESCE(l.line_item_type, ''), a.id, COALESCE(a.responsible_staff_id, ''),
		       l.partner_id IS NOT NULL, l.vendor_paid, l.catalogue_id IS NOT NULL,
		       COALESCE(a.activity_type, ''), COALESCE(a.delivery_type, ''), COALESCE(a.programme_activity_type, ''),
		       COALESCE(a.status, ''), a.school_id IS NOT NULL, COALESCE(d.name, ''), COALESCE(r.name, ''),
		       s.district_id IS NOT NULL, s.region_id IS NOT NULL, a.cost_missing,
		       COALESCE(a.teachers_attended, 0) + COALESCE(a.leaders_attended, 0) + COALESCE(a.other_participants, 0),
		       a.planned_date, a.end_date
		FROM activity_schedule_cost_line l
		JOIN activity a ON a.id = l.activity_id
		LEFT JOIN school s ON s.id = a.school_id
		LEFT JOIN district d ON d.id = s.district_id
		LEFT JOIN region r ON r.id = s.region_id
		WHERE a.responsible_staff_id = ANY($1) AND a.fy = $2 AND a.deleted_at IS NULL
		  AND l.week_start_date IS NOT NULL
		  AND NOT (a.status IN ('cancelled', 'rejected', 'deferred') AND a.status IS NOT NULL)
		  AND l.week_start_date = $3`, ids, fy, week)
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the week's cost lines: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (line, error) {
		var l line
		err := r.Scan(&l.amount, &l.lineType, &l.activityID, &l.staffID, &l.partnerLine, &l.vendorPaid, &l.catalogued,
			&l.activityType, &l.delivery, &l.programme, &l.status, &l.atSchool, &l.district, &l.region,
			&l.hasDistrict, &l.hasRegion, &l.costMissing, &l.attended, &l.planned, &l.end)
		return l, err
	})
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the week's cost lines: %w", err)
	}
	return out, nil
}

func (l line) partner() bool { return l.delivery == "partner" || l.partnerLine }

// vendorTransport is fundable.is_vendor_transport: a single day's school
// transport, paid straight to the provider.
func (l line) vendorTransport() bool {
	severalDays := l.end != nil && l.planned != nil && l.end.After(*l.planned)
	return l.lineType == "transport" && l.atSchool && !severalDays
}

// request is an officer's weekly request for the week.
type request struct {
	id, status       string
	total, disbursed int64
	weekStart        time.Time
	responsible      string
}

// plan is _build_cceo_plan's record of one officer's week.
type plan struct {
	officer          officer
	district, region string
	total            int64
	req              request
	status           string
	valid            bool
	canApprove       bool
	canReturn        bool
}

// buildPlan is _build_cceo_plan: the staff lines (partner-delivered work
// and provider-paid transport and accommodation left out), the officer's
// commonest district and region, the checks and the status the approver
// reads.
func buildPlan(o officer, lines []line, req request, awaiting string) plan {
	p := plan{officer: o, req: req}
	districts, regions := map[string]int{}, map[string]int{}
	districtOrder, regionOrder := []string{}, []string{}
	seen := map[string]bool{}
	issues := false
	for _, l := range lines {
		if l.partner() || l.vendorTransport() || (l.lineType == "accommodation" && l.vendorPaid) {
			continue
		}
		p.total += l.amount
		if !l.catalogued {
			issues = true
		}
		if seen[l.activityID] {
			continue
		}
		seen[l.activityID] = true
		if l.costMissing {
			issues = true
		}
		if slices.Contains(rules.ClusterTrainingTypes, l.activityType) && l.attended == 0 &&
			slices.Contains([]string{"completed", "closed", "submitted_to_pl"}, l.status) {
			issues = true
		}
		if l.atSchool && l.hasDistrict {
			if districts[l.district] == 0 {
				districtOrder = append(districtOrder, l.district)
			}
			districts[l.district]++
		}
		if l.atSchool && l.hasRegion {
			if regions[l.region] == 0 {
				regionOrder = append(regionOrder, l.region)
			}
			regions[l.region]++
		}
	}
	p.district, p.region = commonest(districtOrder, districts), commonest(regionOrder, regions)
	p.valid = !issues
	p.status = statusLabel(req.status)
	if req.status == awaiting {
		p.status = "Awaiting Approval"
		if !p.valid {
			p.status = "Needs Review"
		}
	}
	p.canApprove = req.status == awaiting && p.valid
	p.canReturn = req.status == awaiting
	return p
}

// commonest is max(set(names), key=names.count), "—" for none. Python
// breaks a tie by its set's order, which varies from run to run; here a tie
// goes to the name first met.
func commonest(order []string, counts map[string]int) string {
	best := "—"
	n := 0
	for _, name := range order {
		if counts[name] > n {
			best, n = name, counts[name]
		}
	}
	return best
}

// requests reads each officer's request for the week.
func requests(ctx context.Context, db schooldirectory.Querier, users []string, week time.Time) (map[string]request, error) {
	rows, err := db.Query(ctx, `
		SELECT id, responsible_user, COALESCE(status, ''), total_amount, COALESCE(disbursed_amount, 0), week_start_date
		FROM weekly_fund_request WHERE responsible_user = ANY($1) AND week_start_date = $2`, users, week)
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the week's requests: %w", err)
	}
	out := map[string]request{}
	err = forEach(rows, func(r pgx.Rows) error {
		var q request
		if err := r.Scan(&q.id, &q.responsible, &q.status, &q.total, &q.disbursed, &q.weekStart); err != nil {
			return err
		}
		out[q.responsible] = q
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("fundapprovals: reading the week's requests: %w", err)
	}
	return out, nil
}

func forEach(rows pgx.Rows, each func(pgx.Rows) error) error {
	defer rows.Close()
	for rows.Next() {
		if err := each(rows); err != nil {
			return err
		}
	}
	return rows.Err()
}

// sortPlans is plans.sort(key=-total), stable.
func sortPlans(plans []plan) {
	sort.SliceStable(plans, func(i, j int) bool { return plans[i].total > plans[j].total })
}
