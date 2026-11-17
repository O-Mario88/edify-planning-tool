package iapages

import (
	"context"
	"fmt"
	"math"
	"slices"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/oversightportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// geographyPageSize is the districts a group's table shows before it pages.
const geographyPageSize = 50

// rollup is _ia_merge_rollups' figures.
type rollup struct {
	planned, achieved, waiting, returned int
}

func (r rollup) add(o rollup) rollup {
	return rollup{r.planned + o.planned, r.achieved + o.achieved, r.waiting + o.waiting, r.returned + o.returned}
}

// pyPercent is round(part / whole * 100) as Python rounds it, 0 for none.
func pyPercent(part, whole int) int {
	if whole == 0 {
		return 0
	}
	return int(math.RoundToEven(float64(part) / float64(whole) * 100))
}

// districtRow is one district of the monitoring table.
type districtRow struct {
	id, name, region                         string
	figures                                  rollup
	schools, schoolsPlanned, schoolsAchieved int
}

// districtGroup is the districts of one sub-region.
type districtGroup struct {
	name, region string
	districts    []districtRow
}

// mapView is the dashboard's Map view: the country map card, regional
// performance and district monitoring (_ia_map_view over
// _ia_geography_context). A group running past a page hands on.
func (s *Service) mapView(ctx context.Context, scope schooldirectory.Scope, where string, args []any, now time.Time) ([]*screensv1.PageBlock, bool, error) {
	blocks, err := oversightportfolio.MapCard(ctx, s.db)
	if err != nil {
		return nil, true, err
	}
	d := rules.Dashboard
	n := len(args)
	plans := fmt.Sprintf(`FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.deleted_at IS NULL AND (%s) AND a.fy = $%d AND NOT COALESCE(a.status = ANY($%d), FALSE)`, where, n+1, n+2)
	pargs := append(slices.Clone(args), schooldirectory.OperationalFY(now), d.PerformanceExcludedStatuses, d.AchievedStatuses,
		rules.LeadVerifiedRoles, rules.LeadRole)
	figures := fmt.Sprintf(`count(*), count(*) FILTER (WHERE a.status = ANY($%d)),
  count(*) FILTER (WHERE a.status = 'awaiting_ia_verification' AND NOT COALESCE(%s, FALSE)),
  count(*) FILTER (WHERE a.status = 'returned_by_ia')`, n+3, leadVerifiedSQL(n+4))
	byDistrict, byRegion := map[string]rollup{}, map[string]rollup{}
	read := func(sql string, into func(key string, r rollup)) error {
		rows, err := s.db.Query(ctx, sql, pargs...)
		if err != nil {
			return fmt.Errorf("iapages: reading the activity roll-up: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var key *string
			var r rollup
			if err := rows.Scan(&key, &r.planned, &r.achieved, &r.waiting, &r.returned); err != nil {
				return fmt.Errorf("iapages: reading an activity roll-up: %w", err)
			}
			if key != nil {
				into(*key, r)
			}
		}
		return rows.Err()
	}
	// The school's district and region, then the event's district and its
	// region, each added (an activity with both counts under both).
	for _, q := range []struct {
		key  string
		into map[string]rollup
	}{
		{"s.district_id", byDistrict}, {"s.region_id", byRegion}, {"a.event_district_id", byDistrict},
		{"(SELECT ed.region_id FROM district ed WHERE ed.id = a.event_district_id)", byRegion},
	} {
		into := q.into
		if err := read(fmt.Sprintf("SELECT %s, %s %s GROUP BY 1", q.key, figures, plans), func(key string, r rollup) {
			into[key] = into[key].add(r)
		}); err != nil {
			return nil, true, err
		}
	}
	reach, err := s.schoolReach(ctx, scope, plans, pargs)
	if err != nil {
		return nil, true, err
	}
	groups, count, err := s.districtGroups(ctx, scope, byDistrict, reach)
	if err != nil {
		return nil, true, err
	}
	regions, err := s.regionLinks(ctx, scope, byRegion)
	if err != nil {
		return nil, true, err
	}
	regional := panelOf("Regional performance", linksItem(regions...))
	regional.GetPanel().Subtitle = "Achieved share of FY activity plans"
	monitoring := panelOf("District monitoring", textItem(strconv.Itoa(count)))
	monitoring.GetPanel().Subtitle = "Every district, including centrally planned activities assigned to it, grouped by sub-region"
	blocks = append(blocks, regional, monitoring)
	for _, g := range groups {
		if len(g.districts) > geographyPageSize {
			return nil, false, nil
		}
		blocks = append(blocks, g.blocks()...)
	}
	return blocks, true, nil
}

// reachSets is _ia_school_reach_sets by district: the active schools, and
// the schools with planned and achieved work.
type reachSets struct {
	schools           map[string]int
	planned, achieved map[string]map[string]bool
}

func (s *Service) schoolReach(ctx context.Context, scope schooldirectory.Scope, plans string, pargs []any) (reachSets, error) {
	r := reachSets{schools: map[string]int{}, planned: map[string]map[string]bool{}, achieved: map[string]map[string]bool{}}
	schools, sargs := activeSchools(scope)
	rows, err := s.db.Query(ctx, "SELECT s.district_id, count(*) FROM school s WHERE "+schools+" AND s.district_id IS NOT NULL GROUP BY 1", sargs...)
	if err != nil {
		return r, fmt.Errorf("iapages: counting the districts' schools: %w", err)
	}
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			rows.Close()
			return r, fmt.Errorf("iapages: counting a district's schools: %w", err)
		}
		r.schools[id] = n
	}
	rows.Close()
	n := len(pargs) - 2 // the achieved statuses' number, as the figures read them
	rows, err = s.db.Query(ctx, fmt.Sprintf(`SELECT DISTINCT s.district_id, a.school_id, COALESCE(a.status = ANY($%d), FALSE) %s
  AND a.school_id IS NOT NULL AND s.district_id IS NOT NULL`, n, plans), pargs[:n]...)
	if err != nil {
		return r, fmt.Errorf("iapages: reading the schools reached: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var district, school string
		var achieved bool
		if err := rows.Scan(&district, &school, &achieved); err != nil {
			return r, fmt.Errorf("iapages: reading a school reached: %w", err)
		}
		if r.planned[district] == nil {
			r.planned[district] = map[string]bool{}
		}
		r.planned[district][school] = true
		if achieved {
			if r.achieved[district] == nil {
				r.achieved[district] = map[string]bool{}
			}
			r.achieved[district][school] = true
		}
	}
	return r, rows.Err()
}

// districtScope is _ia_districts over district `d`.
func districtScope(scope schooldirectory.Scope) (string, []any) {
	switch {
	case countryBound(scope):
		return "d.region_id IN (SELECT id FROM region WHERE country = $1)", []any{scope.Country}
	case !scope.CountryScope:
		schools, args := activeSchoolsAll(scope)
		return "d.id IN (SELECT s.district_id FROM school s WHERE " + schools + ")", args
	}
	return "TRUE", nil
}

// activeSchoolsAll is _ia_school_scope: the scope's live schools, open or
// not.
func activeSchoolsAll(scope schooldirectory.Scope) (string, []any) {
	args := []any{}
	return schooldirectory.AnalyticsReach(scope, &args), args
}

func (s *Service) districtGroups(ctx context.Context, scope schooldirectory.Scope, byDistrict map[string]rollup, reach reachSets) ([]districtGroup, int, error) {
	where, args := districtScope(scope)
	rows, err := s.db.Query(ctx, `SELECT d.id, d.name, r.name, sr.name FROM district d JOIN region r ON r.id = d.region_id
LEFT JOIN sub_region sr ON sr.id = d.sub_region_id WHERE `+where+` ORDER BY r.name, sr.name, d.name`, args...)
	if err != nil {
		return nil, 0, fmt.Errorf("iapages: reading the districts: %w", err)
	}
	defer rows.Close()
	groups := []districtGroup{}
	index := map[[2]string]int{}
	count := 0
	for rows.Next() {
		var row districtRow
		var sub *string
		if err := rows.Scan(&row.id, &row.name, &row.region, &sub); err != nil {
			return nil, 0, fmt.Errorf("iapages: reading a district: %w", err)
		}
		count++
		row.figures = byDistrict[row.id]
		row.schools = reach.schools[row.id]
		row.schoolsPlanned, row.schoolsAchieved = len(reach.planned[row.id]), len(reach.achieved[row.id])
		key := [2]string{row.region, ""}
		name := "Other districts"
		if sub != nil {
			key[1], name = *sub, *sub
		}
		i, ok := index[key]
		if !ok {
			i = len(groups)
			index[key] = i
			groups = append(groups, districtGroup{name: name, region: row.region})
		}
		groups[i].districts = append(groups[i].districts, row)
	}
	return groups, count, rows.Err()
}

func (s *Service) regionLinks(ctx context.Context, scope schooldirectory.Scope, byRegion map[string]rollup) ([]*screensv1.PageLink, error) {
	where, args := "TRUE", []any{}
	switch {
	case countryBound(scope):
		where, args = "r.country = $1", []any{scope.Country}
	case !scope.CountryScope:
		schools, sargs := activeSchoolsAll(scope)
		where, args = "r.id IN (SELECT s.region_id FROM school s WHERE "+schools+")", sargs
	}
	rows, err := s.db.Query(ctx, "SELECT r.id, r.name FROM region r WHERE "+where+" ORDER BY r.name", args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the regions: %w", err)
	}
	defer rows.Close()
	links := []*screensv1.PageLink{}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("iapages: reading a region: %w", err)
		}
		f := byRegion[id]
		links = append(links, &screensv1.PageLink{Text: fmt.Sprintf("%s%d of %d achieved · %d awaiting IA%d%%",
			name, f.achieved, f.planned, f.waiting, pyPercent(f.achieved, f.planned))})
	}
	return links, rows.Err()
}

// blocks is one sub-region's group: its head (the schools achieved across
// its districts) and its districts' table.
func (g districtGroup) blocks() []*screensv1.PageBlock {
	schools, achieved := 0, 0
	for _, d := range g.districts {
		schools += d.schools
		achieved += d.schoolsAchieved
	}
	head := panelOf("", textItem(g.name), textItem(fmt.Sprintf("%s · %d %s", g.region, len(g.districts), plural(len(g.districts), "district"))),
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{{
			Label: fmt.Sprintf("%d of %d schools achieved", achieved, schools), Value: fmt.Sprintf("%d%%", pyPercent(achieved, schools)),
		}}}}})
	t := &screensv1.PageTable{Columns: columns("District", "Schools", "Activities", "# Schools", "# Planned", "# Achieved", "% Achieved",
		"Planned", "Achieved", "Awaiting IA", "Returned", "Performance")}
	for _, d := range g.districts {
		f := d.figures
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(d.name + d.region), cell(strconv.Itoa(d.schools)), cell(strconv.Itoa(d.schoolsPlanned)), cell(strconv.Itoa(d.schoolsAchieved)),
			{Text: fmt.Sprintf("%d%%", pyPercent(d.schoolsAchieved, d.schools)), Strong: true},
			cell(strconv.Itoa(f.planned)), cell(strconv.Itoa(f.achieved)), cell(strconv.Itoa(f.waiting)), cell(strconv.Itoa(f.returned)),
			{Text: fmt.Sprintf("%d%%", pyPercent(f.achieved, f.planned)), Strong: true},
		}})
	}
	return []*screensv1.PageBlock{head, tableBlock(t)}
}
