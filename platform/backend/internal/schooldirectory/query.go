package schooldirectory

import (
	"fmt"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// sqlb builds a WHERE clause with numbered parameters.
type sqlb struct {
	parts []string
	args  []any
}

func (b *sqlb) arg(v any) string {
	b.args = append(b.args, v)
	return fmt.Sprintf("$%d", len(b.args))
}

func (b *sqlb) and(clause string) { b.parts = append(b.parts, "("+clause+")") }

func (b *sqlb) where() string {
	if len(b.parts) == 0 {
		return "true"
	}
	return strings.Join(b.parts, " AND ")
}

func (b *sqlb) clone() *sqlb {
	return &sqlb{parts: append([]string{}, b.parts...), args: append([]any{}, b.args...)}
}

// operating is _operationally_active and active_schools: not deleted, and
// not closed.
const operating = `s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')`

// inCountry is school_in_country_q read through Edify Global's registry: the
// school belongs to the Active country the existing tables name country
// (country.SchoolIn). Its explicit country decides; without one, its
// region's, or with no region its holder's. Unlike school_in_country_q, a
// school with neither region nor a holder of the country is in no country,
// not in every one (docs/migration/80-multi-country-phase-0.md, §1.2).
func (b *sqlb) inCountry(name string) string {
	c := b.arg(name)
	return country.SchoolIn("s", fmt.Sprintf(`ARRAY(SELECT a.country_id::text FROM country_registry.country_alias a
  JOIN country_registry.country c ON c.id = a.country_id WHERE a.alias = %s AND c.state = '%s')`, c, country.StateActive))
}

// scopeBase is school_queryset(scope, direct_only=True).
func scopeBase(s Scope) *sqlb {
	b := &sqlb{}
	b.and(operating)
	switch {
	case s.Role == roleCountryDirector && !rules.AllowCDOperational:
		b.and("false")
	case s.CountryScope:
		if s.Country != "" {
			b.and(b.inCountry(s.Country))
		}
	case s.RegionScope:
		if len(s.RegionIDs) == 0 {
			b.and("false")
		} else {
			b.and("s.region_id = ANY(" + b.arg(s.RegionIDs) + ")")
		}
	case s.SummaryOnly:
		b.and("false")
	default:
		if len(s.OwnSchoolIDs) == 0 {
			b.and("false")
		} else {
			b.and("s.id = ANY(" + b.arg(s.OwnSchoolIDs) + ")")
		}
	}
	return b
}

// unheldBase is data_gaps.unheld(country): operating schools nobody holds.
func unheldBase(country string) *sqlb {
	b := &sqlb{}
	b.and(operating)
	b.and(`(s.account_owner_id IS NULL OR s.account_owner_id = '')
 AND NOT EXISTS (SELECT 1 FROM staff_school_assignment a WHERE a.school_id = s.id)`)
	if country != "" {
		b.and(b.inCountry(country))
	}
	return b
}

// likeContains is Django's icontains pattern: the value escaped and wrapped.
func likeContains(value string) string {
	r := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`)
	return "%" + r.Replace(value) + "%"
}

// search is the directory's search contract: name, School ID, district,
// sub-county, the uploaded place names, the owner's name as uploaded, and
// the cluster's name.
func (b *sqlb) search(q string) {
	p := b.arg(likeContains(q))
	b.and(fmt.Sprintf(`UPPER(s.name::text) LIKE UPPER(%[1]s)
 OR UPPER(s.school_id::text) LIKE UPPER(%[1]s)
 OR s.district_id IN (SELECT id FROM district WHERE UPPER(name::text) LIKE UPPER(%[1]s))
 OR s.sub_county_id IN (SELECT id FROM sub_county WHERE UPPER(name::text) LIKE UPPER(%[1]s))
 OR UPPER(s.uploaded_district_text::text) LIKE UPPER(%[1]s)
 OR UPPER(s.uploaded_sub_county_text::text) LIKE UPPER(%[1]s)
 OR UPPER(s.account_owner_name_raw::text) LIKE UPPER(%[1]s)
 OR s.cluster_id IN (SELECT id FROM cluster WHERE deleted_at IS NULL AND UPPER(name::text) LIKE UPPER(%[1]s))`, p))
}

const (
	inProject    = `EXISTS (SELECT 1 FROM project_school_assignment pa WHERE pa.school_id = s.id)`
	notInProject = `NOT EXISTS (SELECT 1 FROM project_school_assignment pa WHERE pa.school_id = s.id)`
)

// gapConditions are data_gaps.GAPS, in their order.
var gapConditions = []struct{ key, condition string }{
	{"no_owner", "(s.account_owner_id IS NULL OR s.account_owner_id = '')"},
	{"no_district", "s.district_id IS NULL"},
	{"no_sub_county", "s.sub_county_id IS NULL"},
	{"no_cluster", "(s.cluster_id IS NULL OR s.cluster_id = '')"},
	{"no_type", "(s.school_type IS NULL OR s.school_type = '')"},
	{"no_enrolment", "(s.enrollment IS NULL OR s.enrollment = 0)"},
	{"no_school_id", "(s.school_id IS NULL OR s.school_id = '')"},
}

func anyGap() string {
	parts := []string{}
	for _, g := range gapConditions {
		parts = append(parts, g.condition)
	}
	return "(" + strings.Join(parts, " OR ") + ")"
}

// noSSA is data_gaps.no_ssa_q(fy).
func (b *sqlb) noSSA(fy string) string {
	return fmt.Sprintf(`NOT EXISTS (SELECT 1 FROM ssa_record r WHERE r.school_id = s.id AND r.fy = %s
 AND r.deleted_at IS NULL AND r.verification_status = ANY(%s))`, b.arg(fy), b.arg(rules.CurrentSSAStatuses))
}

// gapCondition is data_gaps.gap_q; empty for a key that names none.
func (b *sqlb) gapCondition(gap, fy string) string {
	if gap == "any" {
		return anyGap()
	}
	if gap == "no_ssa" {
		return b.noSSA(fy)
	}
	for _, g := range gapConditions {
		if g.key == gap {
			return g.condition
		}
	}
	return ""
}

// tabCondition narrows to the chosen tab.
func tabCondition(tab string) string {
	switch tab {
	case "unclustered":
		return "s.cluster_status = 'unclustered'"
	case "clustered":
		return "s.cluster_status = 'clustered'"
	case "not_assigned":
		return notInProject
	case "assigned":
		return inProject
	}
	return ""
}
