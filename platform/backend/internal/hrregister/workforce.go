package hrregister

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// leavingDays is how far ahead "Leaving in 90 days" looks.
const leavingDays = 90

// unit is one country's department, as the register groups people.
type unit struct{ country, department string }

// unitCounts are one unit's figures.
type unitCounts struct{ headcount, pending, left, leaving, open, awaiting int }

// workforcePlanning is workforce_planning_view: the People records in reach
// and in the search, not exited, grouped by country and department (none is
// "Unassigned"), with their active headcount and those pending activation;
// the exits of the searched people (exited or not) leaving within 90 days
// and gone since the operational year began; and the vacancies of the
// reach's countries open or awaiting approval. A unit is listed when it has
// people, open roles, roles awaiting approval or someone leaving, in country
// and department order.
//
// A department stored as none and one stored as "" are one unit here; the
// existing view groups them apart and keeps whichever comes last
// (OWNER_DEFECTS), which the development seed never meets.
func workforcePlanning(ctx context.Context, in input) (register, error) {
	units := map[unit]*unitCounts{}
	at := func(u unit) *unitCounts {
		if units[u] == nil {
			units[u] = &unitCounts{}
		}
		return units[u]
	}
	listed := map[unit]bool{}

	reachSQL, args := in.reach.profiles(nil)
	searchSQL, args := searched(in.search, args)
	people := fmt.Sprintf(`
SELECT sp.id, sp.country, COALESCE(sp.department, '') AS department, sp.onboarding_state, u.is_active
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND %s AND %s`, reachSQL, searchSQL)
	rows, err := in.db.Query(ctx, people, args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the workforce: %w", err)
	}
	for rows.Next() {
		var id, country, department, state string
		var active bool
		if err := rows.Scan(&id, &country, &department, &state, &active); err != nil {
			rows.Close()
			return register{}, fmt.Errorf("hrregister: reading the workforce: %w", err)
		}
		if state == "exited" {
			continue
		}
		u := unit{country, department}
		listed[u] = true
		if active {
			at(u).headcount++
		}
		if state == "pending" {
			at(u).pending++
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return register{}, fmt.Errorf("hrregister: reading the workforce: %w", err)
	}

	fy := schooldirectory.OperationalFY(in.now)
	year, _ := strconv.Atoi(fy)
	fyStart := time.Date(year-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	horizon := in.today.AddDate(0, 0, leavingDays)
	exits, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT sp.country, COALESCE(sp.department, ''), p.last_working_day, p.status
FROM hr_offboarding p JOIN staff_profile sp ON sp.id = p.staff_id
WHERE p.last_working_day IS NOT NULL AND p.staff_id IN (SELECT id FROM (%s) people)`, people), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the exits: %w", err)
	}
	for exits.Next() {
		var country, department, status string
		var last time.Time
		if err := exits.Scan(&country, &department, &last, &status); err != nil {
			exits.Close()
			return register{}, fmt.Errorf("hrregister: reading the exits: %w", err)
		}
		u := unit{country, department}
		if !last.Before(in.today) && !last.After(horizon) && status != "Closed" {
			at(u).leaving++
			listed[u] = true
		}
		if !last.Before(fyStart) && !last.After(in.today) {
			at(u).left++
		}
	}
	exits.Close()
	if err := exits.Err(); err != nil {
		return register{}, fmt.Errorf("hrregister: reading the exits: %w", err)
	}

	scopeSQL, vargs := in.reach.byCountry("v.country", nil)
	vacancies, err := in.db.Query(ctx, `
SELECT v.country, COALESCE(v.department, ''), lower(COALESCE(v.status, '')) FROM hr_vacancy v WHERE `+scopeSQL, vargs...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the vacancies: %w", err)
	}
	for vacancies.Next() {
		var country, department, status string
		if err := vacancies.Scan(&country, &department, &status); err != nil {
			vacancies.Close()
			return register{}, fmt.Errorf("hrregister: reading the vacancies: %w", err)
		}
		u := unit{country, department}
		switch status {
		case "open":
			at(u).open++
			listed[u] = true
		case "pending_approval":
			at(u).awaiting++
			listed[u] = true
		}
	}
	vacancies.Close()
	if err := vacancies.Err(); err != nil {
		return register{}, fmt.Errorf("hrregister: reading the vacancies: %w", err)
	}

	keys := make([]unit, 0, len(listed))
	for u := range listed {
		keys = append(keys, u)
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].country != keys[j].country {
			return keys[i].country < keys[j].country
		}
		return keys[i].department < keys[j].department
	})
	reg := register{
		path: "/workforce-planning", title: "Workforce Planning", eyebrow: "People and staffing",
		description: "Staffing by country and department: headcount, who has left and who is leaving, and the roles open or " +
			"awaiting approval to replace or grow.",
		columns:    []string{"Department", "Country", "Headcount", "Pending activation", "Left this FY", "Leaving in 90 days", "Open roles", "Awaiting approval"},
		actions:    []action{{label: "Request a vacancy", drawer: "/recruitment/new"}},
		emptyTitle: "No workforce profiles in this scope",
		emptyBody:  defaultEmptyBody,
	}
	total := unitCounts{}
	for _, c := range units {
		total.headcount += c.headcount
		total.left += c.left
		total.leaving += c.leaving
		total.open += c.open
		total.awaiting += c.awaiting
	}
	for _, u := range keys {
		c := at(u)
		department := u.department
		if department == "" {
			department = "Unassigned"
		}
		reg.rows = append(reg.rows, []string{department, dash(u.country), count(c.headcount), count(c.pending), count(c.left),
			count(c.leaving), count(c.open), count(c.awaiting)})
	}
	leavingTone := "success"
	if total.leaving > 0 {
		leavingTone = "warning"
	}
	turnover := "—"
	if population := total.headcount + total.left; population > 0 {
		turnover = pyG1(float64(total.left)*100/float64(population)) + "%"
	}
	reg.metrics = []metric{
		{"Headcount", count(total.headcount), "active people in your countries", "info"},
		{"Open roles", count(total.open), fmt.Sprintf("%d awaiting approval", total.awaiting), "info"},
		{"Leaving in 90 days", count(total.leaving), "last working day ahead", leavingTone},
		{"Turnover this FY", turnover, fmt.Sprintf("%d left since %s", total.left, fyStart.Format("Jan 2006")), "info"},
	}
	return reg, nil
}

// pyG1 is f"{round(x, 1):g}": x to one decimal (half to even on its exact
// value, as Python rounds), without a trailing ".0".
func pyG1(x float64) string {
	return strings.TrimSuffix(strconv.FormatFloat(x, 'f', 1, 64), ".0")
}
