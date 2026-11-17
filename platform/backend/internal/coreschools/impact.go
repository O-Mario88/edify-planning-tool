package coreschools

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// impactRow is one intervention of get_intervention_impact.
type impactRow struct {
	label, improvement, owner, comparison string
	supported                             int
	trend                                 []float64
}

// scoreTotal is one (school, intervention)'s live scores' total and count.
type scoreTotal struct {
	total float64
	count int
}

// scoreTotals is CoreInterventionImpactService._score_totals by (school
// code, intervention).
func scoreTotals(ctx context.Context, db schooldirectory.Querier, pks []string) (map[[2]string]scoreTotal, error) {
	rows, err := db.Query(ctx, `
SELECT s.school_id, sc.intervention, sum(sc.score), count(sc.id) FROM ssa_score sc
JOIN ssa_record r ON r.id = sc.ssa_record_id JOIN school s ON s.id = r.school_id
WHERE r.deleted_at IS NULL AND s.id = ANY($1) GROUP BY s.school_id, sc.intervention`, pks)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the score totals: %w", err)
	}
	defer rows.Close()
	out := map[[2]string]scoreTotal{}
	for rows.Next() {
		var code, intervention string
		var t scoreTotal
		var total *float64
		if err := rows.Scan(&code, &intervention, &total, &t.count); err != nil {
			return nil, fmt.Errorf("coreschools: reading a score total: %w", err)
		}
		if total != nil {
			t.total = *total
		}
		out[[2]string{code, intervention}] = t
	}
	return out, rows.Err()
}

// interventionImpact is get_intervention_impact over the filtered schools.
func (pg *page) interventionImpact(ctx context.Context) ([]impactRow, error) {
	db, fy := pg.db, pg.fy
	pks, codes := ids(pg.all)
	supported, err := counts(ctx, db, `SELECT coalesce(focus_intervention, ''), count(DISTINCT school_id) FROM activity
WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL AND status = ANY($3) GROUP BY focus_intervention`, pks, fy, rules.ImpactActive)
	if err != nil {
		return nil, err
	}
	// The intervention's most active owner: the first owner reached with
	// the most activities, in the order the grouped rows come.
	topOwner, topCount := map[string]string{}, map[string]int{}
	rows, err := db.Query(ctx, `SELECT coalesce(focus_intervention, ''), coalesce(responsible_staff_id, ''), count(id) FROM activity
WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL GROUP BY focus_intervention, responsible_staff_id`, pks, fy)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the interventions' owners: %w", err)
	}
	for rows.Next() {
		var code, owner string
		var n int
		if err := rows.Scan(&code, &owner, &n); err != nil {
			rows.Close()
			return nil, fmt.Errorf("coreschools: reading an intervention's owner: %w", err)
		}
		if held, ok := topCount[code]; !ok || n > held {
			topCount[code], topOwner[code] = n, owner
		}
	}
	rows.Close()
	ownerIDs := []string{}
	for _, id := range topOwner {
		if id != "" {
			ownerIDs = append(ownerIDs, id)
		}
	}
	ownerNames, err := names(ctx, db, `SELECT sp.user_id, coalesce(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.user_id = ANY($1)`, ownerIDs)
	if err != nil {
		return nil, err
	}
	completed, staffSide, partnerSide := map[string]map[string]bool{}, map[string]map[string]bool{}, map[string]map[string]bool{}
	add := func(m map[string]map[string]bool, code, school string) {
		if m[code] == nil {
			m[code] = map[string]bool{}
		}
		m[code][school] = true
	}
	srows, err := db.Query(ctx, `SELECT coalesce(sl.intervention, ''), coalesce(sl.school_id, ''), coalesce(sl.owner, ''), coalesce(sl.status, '')
FROM core_activity_slot sl JOIN core_plan p ON p.id = sl.core_plan_id WHERE sl.school_id = ANY($1) AND p.fy = $2`, codes, fy)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the package slots: %w", err)
	}
	for srows.Next() {
		var code, school, owner, status string
		if err := srows.Scan(&code, &school, &owner, &status); err != nil {
			srows.Close()
			return nil, fmt.Errorf("coreschools: reading a package slot: %w", err)
		}
		if contains(rules.ImpactCompleted, status) {
			add(completed, code, school)
		}
		if owner == "partner" {
			add(partnerSide, code, school)
		} else {
			add(staffSide, code, school)
		}
	}
	srows.Close()
	deltas := map[string]float64{}
	drows, err := db.Query(ctx, `SELECT school_id, follow_up_average - baseline_average FROM core_plan
WHERE school_id = ANY($1) AND fy = $2 AND baseline_average IS NOT NULL AND follow_up_average IS NOT NULL`, codes, fy)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the paired assessments: %w", err)
	}
	for drows.Next() {
		var school string
		var d float64
		if err := drows.Scan(&school, &d); err != nil {
			drows.Close()
			return nil, fmt.Errorf("coreschools: reading a paired assessment: %w", err)
		}
		deltas[school] = d
	}
	drows.Close()
	totals, err := scoreTotals(ctx, db, pks)
	if err != nil {
		return nil, err
	}
	trends := map[string][]float64{}
	trows, err := db.Query(ctx, `
SELECT sc.intervention, avg(sc.score) FROM ssa_score sc JOIN ssa_record r ON r.id = sc.ssa_record_id JOIN school s ON s.id = r.school_id
WHERE s.school_id = ANY($1) AND r.deleted_at IS NULL
GROUP BY sc.intervention, date_trunc('month', r.date_of_ssa AT TIME ZONE 'Africa/Nairobi')
ORDER BY sc.intervention, date_trunc('month', r.date_of_ssa AT TIME ZONE 'Africa/Nairobi')`, codes)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the score trends: %w", err)
	}
	for trows.Next() {
		var code string
		var avg *float64
		if err := trows.Scan(&code, &avg); err != nil {
			trows.Close()
			return nil, fmt.Errorf("coreschools: reading a score trend: %w", err)
		}
		if avg != nil {
			trends[code] = append(trends[code], pyRound(*avg, 2))
		}
	}
	trows.Close()
	groupAverage := func(code string, group map[string]bool) *float64 {
		var sum float64
		n := 0
		parts := []float64{}
		for school := range group {
			if t, ok := totals[[2]string{school, code}]; ok {
				parts = append(parts, t.total)
				n += t.count
			}
		}
		if n == 0 {
			return nil
		}
		sum = schooldirectory.PySum(parts)
		v := pyRound(sum/float64(n), 1)
		return &v
	}
	out := []impactRow{}
	for _, c := range rules.Interventions {
		code := c[0]
		r := impactRow{label: c[1], supported: supported[code], improvement: "No data yet", comparison: "Insufficient data"}
		ds := []float64{}
		for school := range completed[code] {
			if d, ok := deltas[school]; ok {
				ds = append(ds, d)
			}
		}
		if len(ds) > 0 {
			r.improvement = "+" + pyFloat(pyRound(schooldirectory.PySum(ds)/float64(len(ds)), 1)) + " pp"
		}
		if len(staffSide[code]) > 0 && len(partnerSide[code]) > 0 {
			staffPct, partnerPct := groupAverage(code, staffSide[code]), groupAverage(code, partnerSide[code])
			if staffPct != nil && partnerPct != nil {
				diff := *staffPct - *partnerPct
				if diff >= 0 {
					r.comparison = "Staff +" + pyFloat(diff) + "pp"
				} else {
					r.comparison = "Partner +" + pyFloat(-diff) + "pp"
				}
			}
		}
		if t := trends[code]; len(t) >= 2 {
			r.trend = t
		}
		r.owner = "Unassigned"
		if name, ok := ownerNames[topOwner[code]]; ok {
			r.owner = name
		}
		out = append(out, r)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].supported > out[j].supported })
	return out, nil
}

// impact is the Intervention Impact Tracker tab.
func (pg *page) impact(ctx context.Context) ([]*screensv1.PageBlock, error) {
	rows, err := pg.interventionImpact(ctx)
	if err != nil {
		return nil, err
	}
	head := []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: "Verified SSA movement by intervention across your core schools."}}}
	if pg.door.OpenOversight {
		head = append(head, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: "Core School Oversight", Href: "/core-schools-oversight/"}}}}})
	}
	cols := []*screensv1.PageColumn{}
	for _, c := range []string{"Intervention", "Schools Supported", "Avg. Improvement", "Top Supporting Owner", "Staff vs Partner"} {
		cols = append(cols, &screensv1.PageColumn{Label: c})
	}
	cols = append(cols, &screensv1.PageColumn{Label: "Trend", Numeric: true})
	t := &screensv1.PageTable{Columns: cols}
	for _, r := range rows {
		if strings.HasPrefix(r.comparison, "Staff") {
			// The staff-ahead pill's colour is not one the feed was seen
			// reading; hand on rather than guess it.
			return nil, fmt.Errorf("a staff-ahead comparison: %w", errPassOn)
		}
		trend := "Not enough data"
		if len(r.trend) > 0 {
			trend = ""
		}
		owner := string([]rune(r.owner)[:min(2, len([]rune(r.owner)))]) + " " + r.owner
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: r.label}, {Text: strconv.Itoa(r.supported)}, {Text: r.improvement}, {Text: owner},
			{Text: r.comparison, Tone: "primary", Badge: true}, {Text: trend},
		}})
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: head}}},
		{Kind: &screensv1.PageBlock_Table{Table: t}},
	}, nil
}
