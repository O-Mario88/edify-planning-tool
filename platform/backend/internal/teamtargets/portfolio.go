package teamtargets

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// query is what _team_targets_page_context reads off the request.
type query struct {
	fy                                string
	month                             int // 0: the page's default
	category, district, member, order string
}

func readQuery(q map[string]string) query {
	get := func(name string) string { return strings.TrimSpace(q[name]) }
	out := query{fy: get("fy"), category: get("category"), district: get("district"), member: get("team_member"), order: get("order")}
	if out.category == "" {
		out.category = "overall"
	}
	raw := get("month")
	if n, err := strconv.Atoi(raw); err == nil && raw != "" && strings.Trim(raw, "0123456789") == "" && n >= 1 && n <= 12 {
		out.month = n
	}
	return out
}

// period is get_page's year and month: today's when none is asked (the
// first month of another year).
type period struct {
	fy            string
	month         int
	current       bool
	today         time.Time
	start, end    time.Time // the month, end exclusive
	operationalFY string
}

func periodOf(q query, today time.Time, operationalFY string) period {
	p := period{fy: q.fy, today: today, operationalFY: operationalFY}
	if p.fy == "" {
		p.fy = operationalFY
	}
	p.current = p.fy == operationalFY
	p.month = q.month
	if p.month == 0 {
		p.month = 1
		if p.current {
			if m := targets.MonthOfFY(today, p.fy); m != 0 {
				p.month = m
			}
		}
	}
	p.start, p.end = targets.MonthRange(p.fy, p.month)
	return p
}

// school is one portfolio school.
type school struct{ id, code, name, district string }

// portfolio is the supervision portfolio: each person's operating schools
// (StaffSchoolAssignment) and their districts.
type portfolio struct {
	of        map[string][]school // staff id → schools
	districts []string            // the districts, sorted
	codes     []string            // School.school_id of the portfolio
	names     map[string]string   // school code → name
}

func readPortfolio(ctx context.Context, db schooldirectory.Querier, staffIDs []string) (portfolio, error) {
	out := portfolio{of: map[string][]school{}, names: map[string]string{}}
	if len(staffIDs) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT a.staff_id, s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(d.name, '')
		FROM staff_school_assignment a JOIN school s ON s.id = a.school_id
		LEFT JOIN district d ON d.id = s.district_id
		WHERE a.staff_id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2) ORDER BY a.id`, staffIDs, operating)
	if err != nil {
		return out, fmt.Errorf("teamtargets: the portfolio: %w", err)
	}
	defer rows.Close()
	seen, codes, districts := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for rows.Next() {
		var staff string
		var s school
		if err := rows.Scan(&staff, &s.id, &s.code, &s.name, &s.district); err != nil {
			return out, err
		}
		out.of[staff] = append(out.of[staff], s)
		out.names[s.code] = s.name
		if s.district != "" {
			districts[s.district] = true
		}
		if !seen[s.id] {
			seen[s.id] = true
			if !codes[s.code] {
				codes[s.code] = true
				out.codes = append(out.codes, s.code)
			}
		}
	}
	for d := range districts {
		out.districts = append(out.districts, d)
	}
	sort.Strings(out.districts)
	return out, rows.Err()
}

// districtsOf are the sorted districts of a person's schools.
func (p portfolio) districtsOf(staffID string) []string {
	set := map[string]bool{}
	for _, s := range p.of[staffID] {
		if s.district != "" {
			set[s.district] = true
		}
	}
	out := []string{}
	for d := range set {
		out = append(out, d)
	}
	sort.Strings(out)
	return out
}
