package coreschools

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

var errPassOn = errors.New("coreschools: passed to the existing application")

// filters are the page's filters as the view reads them (each "All" when
// not asked).
type filters struct {
	fy, q, region, district, staff, partner, schoolType, ssaStatus, partnerAssigned string
}

func (f filters) narrowed() bool {
	for _, v := range []string{f.district, f.staff, f.partner, f.schoolType, f.ssaStatus, f.partnerAssigned} {
		if v != "All" {
			return true
		}
	}
	return false
}

// school is one core school as the page reads it.
type school struct {
	id, code, name, districtID, districtName, regionID, regionName, subCountyID, subCountyName   string
	clusterID, ownerID, ownerRaw, shipping, schoolType, phone, contact, ssaStatus, clusterStatus string
	enrollment                                                                                   *int
	createdAt                                                                                    time.Time
}

// sqlArgs numbers a query's parameters.
type sqlArgs struct{ list []any }

func (a *sqlArgs) arg(v any) string {
	a.list = append(a.list, v)
	return fmt.Sprintf("$%d", len(a.list))
}

// likeArg is an icontains pattern: the text with LIKE's own characters
// escaped, between wildcards.
func likeArg(q string) string {
	r := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`)
	return "%" + r.Replace(q) + "%"
}

// lensClause is the lens's schools (aliased s): the direct portfolio, or a
// supervisor's team's schools.
func lensClause(scope schooldirectory.Scope, oversight bool, a *sqlArgs) string {
	if !oversight {
		return schooldirectory.DirectPortfolio(scope, a.arg)
	}
	team := teamSchoolIDs(scope)
	if len(team) == 0 {
		return "false"
	}
	return "s.deleted_at IS NULL AND s.id = ANY(" + a.arg(team) + ")"
}

// teamSchoolIDs is scope.team_school_ids: the scope's schools that are not
// the person's own.
func teamSchoolIDs(scope schooldirectory.Scope) []string {
	out := []string{}
	for _, id := range scope.SchoolIDs {
		if !slices.Contains(scope.OwnSchoolIDs, id) {
			out = append(out, id)
		}
	}
	return out
}

// healPending is whether CoreSchoolsService.get_core_schools would write on
// this read: a core school of the lens with no package for the year but a
// confirmed SSA (self_heal_plans), or — for the operational year or a later
// one — with a live package of another year and none for this one
// (carry_packages_forward).
func healPending(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, oversight bool, fy, operational string) (bool, error) {
	a := &sqlArgs{}
	base := lensClause(scope, oversight, a) + " AND s.school_type = 'core'"
	year := a.arg(fy)
	carry := "false"
	if fy >= operational {
		carry = fmt.Sprintf(`EXISTS (SELECT 1 FROM core_plan p WHERE p.school_id = s.school_id AND NOT (p.status = ANY(%s)))`,
			a.arg(rules.PlanClosedStatuses))
	}
	var pending bool
	err := db.QueryRow(ctx, fmt.Sprintf(`
SELECT EXISTS (
  SELECT 1 FROM school s
  WHERE %s AND NOT EXISTS (SELECT 1 FROM core_plan p WHERE p.school_id = s.school_id AND p.fy = %s)
    AND (EXISTS (SELECT 1 FROM ssa_record r WHERE r.school_id = s.id AND r.deleted_at IS NULL AND r.verification_status = 'confirmed')
         OR %s))`, base, year, carry), a.list...).Scan(&pending)
	if err != nil {
		return false, fmt.Errorf("coreschools: reading whether the packages are whole: %w", err)
	}
	return pending, nil
}

// filterClause is get_core_schools' filters over the lens's core schools.
func filterClause(f filters, a *sqlArgs) string {
	parts := []string{}
	if f.q != "" {
		p := a.arg(likeArg(f.q))
		parts = append(parts, fmt.Sprintf(`(s.name ILIKE %[1]s OR s.school_id ILIKE %[1]s OR d.name ILIKE %[1]s OR sc.name ILIKE %[1]s
  OR s.account_owner_name_raw ILIKE %[1]s)`, p))
	}
	for _, c := range []struct{ value, column string }{
		{f.region, "s.region_id"}, {f.district, "s.district_id"}, {f.staff, "s.account_owner_id"},
		{f.schoolType, "s.school_type"}, {f.ssaStatus, "s.current_fy_ssa_status"},
	} {
		if c.value != "" && c.value != "All" {
			parts = append(parts, c.column+" = "+a.arg(c.value))
		}
	}
	if f.partner != "" && f.partner != "All" {
		parts = append(parts, fmt.Sprintf(`s.id IN (SELECT pa.school_id FROM partner_assignment pa JOIN school ps ON ps.id = pa.school_id
  WHERE pa.partner_id = %s AND ps.school_type = 'core')`, a.arg(f.partner)))
	}
	if f.partnerAssigned == "assigned" || f.partnerAssigned == "unassigned" {
		held := fmt.Sprintf(`(SELECT pa.school_id FROM partner_assignment pa JOIN school ps ON ps.id = pa.school_id
  WHERE ps.school_type = 'core' AND NOT (pa.status = ANY(%s)))`, a.arg(rules.PartnerReleased))
		if f.partnerAssigned == "assigned" {
			parts = append(parts, "s.id IN "+held)
		} else {
			parts = append(parts, "s.id NOT IN "+held)
		}
	}
	if len(parts) == 0 {
		return "true"
	}
	return strings.Join(parts, " AND ")
}

const schoolColumns = `s.id, coalesce(s.school_id, ''), s.name, coalesce(s.district_id, ''), coalesce(d.name, ''),
  coalesce(s.region_id, ''), coalesce(r.name, ''), coalesce(s.sub_county_id, ''), coalesce(sc.name, ''),
  coalesce(s.cluster_id, ''), coalesce(s.account_owner_id, ''), coalesce(s.account_owner_name_raw, ''),
  coalesce(s.shipping_address, ''), coalesce(s.school_type, ''),
  coalesce(nullif(s.primary_contact_phone, ''), coalesce(s.school_phone, '')), coalesce(s.primary_contact_name, ''),
  coalesce(s.current_fy_ssa_status, ''), coalesce(s.cluster_status, ''), s.enrollment, s.created_at`

const schoolJoins = `FROM school s LEFT JOIN district d ON d.id = s.district_id LEFT JOIN region r ON r.id = s.region_id
  LEFT JOIN sub_county sc ON sc.id = s.sub_county_id`

func scanSchool(rows pgx.Rows) (school, error) {
	var sc school
	err := rows.Scan(&sc.id, &sc.code, &sc.name, &sc.districtID, &sc.districtName, &sc.regionID, &sc.regionName,
		&sc.subCountyID, &sc.subCountyName, &sc.clusterID, &sc.ownerID, &sc.ownerRaw, &sc.shipping, &sc.schoolType,
		&sc.phone, &sc.contact, &sc.ssaStatus, &sc.clusterStatus, &sc.enrollment, &sc.createdAt)
	return sc, err
}

// coreSchools is get_core_schools: the lens's core schools, filtered, newest
// first (id settling the same instant).
func coreSchools(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, oversight bool, f filters) ([]school, error) {
	a := &sqlArgs{}
	where := lensClause(scope, oversight, a) + " AND s.school_type = 'core' AND " + filterClause(f, a)
	rows, err := db.Query(ctx, "SELECT "+schoolColumns+" "+schoolJoins+" WHERE "+where+" ORDER BY s.created_at DESC, s.id", a.list...)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the core schools: %w", err)
	}
	defer rows.Close()
	out := []school{}
	for rows.Next() {
		sc, err := scanSchool(rows)
		if err != nil {
			return nil, fmt.Errorf("coreschools: reading a core school: %w", err)
		}
		out = append(out, sc)
	}
	return out, rows.Err()
}

func ids(list []school) (pks, codes []string) {
	pks, codes = []string{}, []string{}
	for _, sc := range list {
		pks = append(pks, sc.id)
		codes = append(codes, sc.code)
	}
	return pks, codes
}
