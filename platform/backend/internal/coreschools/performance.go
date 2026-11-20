package coreschools

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// pyRound is round(x, digits) of a float: from its exact value, ties to even.
func pyRound(x float64, digits int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', digits, 64), 64)
	return v
}

// pyFloat is str() of a float.
func pyFloat(x float64) string { return allocations.Repr(x) }

// insight is one row of the staff, partner or region cards.
type insight struct {
	name, initials string
	score, vsAvg   *float64
	schools        int
}

// performanceFigures is get_staff_vs_partner_performance.
type performanceFigures struct {
	delta, orgAverage        *float64
	staff, partners, regions []insight
}

// perf is the staff and partner outcomes, read once a page.
func (pg *page) perf(ctx context.Context) (*performanceFigures, error) {
	if pg.performanceFigures != nil {
		return pg.performanceFigures, nil
	}
	db := pg.db
	pks, codes := ids(pg.all)
	f := &performanceFigures{}
	rows, err := db.Query(ctx, `
SELECT p.baseline_average, p.follow_up_average,
       EXISTS (SELECT 1 FROM core_activity_slot sl WHERE sl.core_plan_id = p.id AND sl.owner = 'partner')
FROM core_plan p WHERE p.school_id = ANY($1) AND p.fy = $2 AND p.baseline_average IS NOT NULL AND p.follow_up_average IS NOT NULL`,
		codes, pg.fy)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the paired assessments: %w", err)
	}
	var staffDeltas, partnerDeltas []float64
	for rows.Next() {
		var baseline, followUp float64
		var partner bool
		if err := rows.Scan(&baseline, &followUp, &partner); err != nil {
			rows.Close()
			return nil, fmt.Errorf("coreschools: reading a paired assessment: %w", err)
		}
		if partner {
			partnerDeltas = append(partnerDeltas, followUp-baseline)
		} else {
			staffDeltas = append(staffDeltas, followUp-baseline)
		}
	}
	rows.Close()
	mean := func(xs []float64) float64 {
		if len(xs) == 0 {
			return 0
		}
		return schooldirectory.PySum(xs) / float64(len(xs))
	}
	if len(staffDeltas)+len(partnerDeltas) > 0 {
		d := pyRound(mean(staffDeltas)-mean(partnerDeltas), 1)
		f.delta = &d
	}
	avg, err := averageScore(ctx, db, pks)
	if err != nil {
		return nil, err
	}
	if avg != 0 {
		o := pyRound(avg, 1)
		f.orgAverage = &o
	}
	vs := func(score *float64) *float64 {
		if score == nil || f.orgAverage == nil {
			return nil
		}
		v := pyRound(*score-*f.orgAverage, 1)
		return &v
	}
	latest := map[string]*float64{}
	lrows, err := db.Query(ctx, `SELECT DISTINCT ON (school_id) school_id, average_score FROM ssa_record
WHERE school_id = ANY($1) AND deleted_at IS NULL ORDER BY school_id, date_of_ssa DESC`, pks)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the latest assessments: %w", err)
	}
	for lrows.Next() {
		var id string
		var score *float64
		if err := lrows.Scan(&id, &score); err != nil {
			lrows.Close()
			return nil, fmt.Errorf("coreschools: reading a latest assessment: %w", err)
		}
		latest[id] = score
	}
	lrows.Close()
	grouped := func(schools []string) *float64 {
		scores := []float64{}
		for _, id := range schools {
			if s := latest[id]; s != nil {
				scores = append(scores, *s)
			}
		}
		if len(scores) == 0 {
			return nil
		}
		v := pyRound(pyRound(schooldirectory.PySum(scores)/float64(len(scores)), 2), 1)
		if v == 0 {
			return nil
		}
		return &v
	}
	owners := map[string][]string{}
	for _, sc := range pg.all {
		if sc.ownerID != "" {
			owners[sc.ownerID] = append(owners[sc.ownerID], sc.id)
		}
	}
	srows, err := db.Query(ctx, `SELECT sp.id, coalesce(sp.user_id, ''), coalesce(u.name, '') FROM staff_profile sp
INNER JOIN "user" u ON u.id = sp.user_id`)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the staff: %w", err)
	}
	for srows.Next() {
		var id, user, name string
		if err := srows.Scan(&id, &user, &name); err != nil {
			srows.Close()
			return nil, fmt.Errorf("coreschools: reading a staff member: %w", err)
		}
		schools := append(append([]string{}, owners[id]...), owners[user]...)
		if len(schools) == 0 {
			continue
		}
		score := grouped(schools)
		f.staff = append(f.staff, insight{name: name, initials: initials(name), score: score, vsAvg: vs(score), schools: len(schools)})
	}
	srows.Close()
	f.staff = top(f.staff, 5)

	cohort := map[string]bool{}
	for _, id := range pks {
		cohort[id] = true
	}
	held := map[string][]string{}
	arows, err := db.Query(ctx, `SELECT pa.partner_id, pa.school_id FROM partner_assignment pa JOIN school s ON s.id = pa.school_id
WHERE s.school_type = 'core' AND NOT (pa.status = ANY($1))`, rules.PartnerReleased)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the partner hand-overs: %w", err)
	}
	for arows.Next() {
		var partner, school string
		if err := arows.Scan(&partner, &school); err != nil {
			arows.Close()
			return nil, fmt.Errorf("coreschools: reading a partner hand-over: %w", err)
		}
		if cohort[school] && !contains(held[partner], school) {
			held[partner] = append(held[partner], school)
		}
	}
	arows.Close()
	prows, err := db.Query(ctx, `SELECT id, name FROM partner ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the partners: %w", err)
	}
	for prows.Next() {
		var id, name string
		if err := prows.Scan(&id, &name); err != nil {
			prows.Close()
			return nil, fmt.Errorf("coreschools: reading a partner: %w", err)
		}
		if schools := held[id]; len(schools) > 0 {
			score := grouped(schools)
			f.partners = append(f.partners, insight{name: name, initials: initials(name), score: score, vsAvg: vs(score), schools: len(schools)})
		}
	}
	prows.Close()
	f.partners = top(f.partners, 5)

	regionSchools := map[string]int{}
	for _, sc := range pg.all {
		if sc.regionID != "" {
			regionSchools[sc.regionID]++
		}
	}
	averages := map[string]*float64{}
	rrows, err := db.Query(ctx, `SELECT s.region_id, avg(r.average_score) FROM ssa_record r JOIN school s ON s.id = r.school_id
WHERE r.school_id = ANY($1) AND r.deleted_at IS NULL AND r.verification_status = 'confirmed' GROUP BY s.region_id`, pks)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the regions' averages: %w", err)
	}
	for rrows.Next() {
		var region *string
		var avg *float64
		if err := rrows.Scan(&region, &avg); err != nil {
			rrows.Close()
			return nil, fmt.Errorf("coreschools: reading a region's average: %w", err)
		}
		if region != nil {
			averages[*region] = avg
		}
	}
	rrows.Close()
	grows, err := db.Query(ctx, `SELECT id, name FROM region ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the regions: %w", err)
	}
	for grows.Next() {
		var id, name string
		if err := grows.Scan(&id, &name); err != nil {
			grows.Close()
			return nil, fmt.Errorf("coreschools: reading a region: %w", err)
		}
		n := regionSchools[id]
		if n == 0 {
			continue
		}
		var score *float64
		if a := averages[id]; a != nil && *a != 0 {
			v := pyRound(*a, 1)
			score = &v
		}
		f.regions = append(f.regions, insight{name: name, score: score, vsAvg: vs(score), schools: n})
	}
	grows.Close()
	f.regions = top(f.regions, len(f.regions))
	pg.performanceFigures = f
	return f, nil
}

func contains(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// top sorts the rows scored first, highest first (keeping their order
// among equals), and keeps n.
func top(rows []insight, n int) []insight {
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i].score, rows[j].score
		if (a == nil) != (b == nil) {
			return a != nil
		}
		if a == nil {
			return false
		}
		return *a > *b
	})
	if len(rows) > n {
		rows = rows[:n]
	}
	return rows
}

// initials is _initials: the first and last words' first letters.
func initials(name string) string {
	parts := strings.Fields(name)
	if len(parts) == 0 {
		return "–"
	}
	first := []rune(parts[0])[:1]
	out := string(first)
	if len(parts) > 1 {
		out += string([]rune(parts[len(parts)-1])[:1])
	}
	return strings.ToUpper(out)
}

// performance is the Staff vs Partner Performance tab.
func (pg *page) performance(ctx context.Context) ([]*screensv1.PageBlock, error) {
	f, err := pg.perf(ctx)
	if err != nil {
		return nil, err
	}
	comparable, err := pg.interventionComparable(ctx)
	if err != nil {
		return nil, err
	}
	if comparable {
		return nil, fmt.Errorf("a staff and partner comparison by intervention: %w", errPassOn)
	}
	trend, err := pg.verifiedTrend(ctx)
	if err != nil {
		return nil, err
	}
	if trend {
		return nil, fmt.Errorf("an assessment trend: %w", errPassOn)
	}
	text := func(s string) *screensv1.PagePanelItem {
		return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
	}
	oversight := func() []*screensv1.PagePanelItem {
		if !pg.door.OpenOversight {
			return []*screensv1.PagePanelItem{}
		}
		return []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: "Core School Oversight →", Href: "/core-schools-oversight/"}}}}}}
	}
	org := ""
	if f.orgAverage != nil {
		org = pyFloat(*f.orgAverage) + "/10"
	}
	ranked := func(items []*screensv1.PagePanelItem, rows []insight, insufficient string) []*screensv1.PagePanelItem {
		for i, r := range rows {
			items = append(items, text(strconv.Itoa(i+1)), text(r.initials), text(r.name))
			if r.score == nil {
				items = append(items, text(insufficient))
				continue
			}
			word := "schools"
			if r.schools == 1 {
				word = "school"
			}
			items = append(items, text(fmt.Sprintf("%s/10 · %d %s", allocations.FloatFormatFloat(*r.score, 1), r.schools, word)))
			if r.vsAvg != nil {
				switch v := *r.vsAvg; {
				case v > 0:
					items = append(items, text("▲ +"+pyFloat(v)))
				case v < 0:
					items = append(items, text("▼ "+pyFloat(v)))
				default:
					items = append(items, text("— 0.0"))
				}
			}
		}
		return items
	}
	panel := func(title, subtitle string, items []*screensv1.PagePanelItem) *screensv1.PageBlock {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
	}
	staff := oversight()
	if len(f.staff) > 0 {
		staff = ranked(staff, f.staff, "Insufficient comparable data")
		if org != "" {
			staff = append(staff, text("Organization average: "+org+" · ▲▼ vs average, in score points"))
		}
	} else {
		staff = append(staff, text("No staff portfolios in scope Rows appear when staff own core schools with verified assessments."))
	}
	partners := []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
		Links: []*screensv1.PageLink{{Text: "View Full Report →", Href: "/partners"}}}}}}
	if len(f.partners) > 0 {
		partners = ranked(partners, f.partners, "Not enough comparable SSA data")
		if org != "" {
			partners = append(partners, text("Organization average: "+org))
		}
	} else {
		partners = append(partners, text("No Partner portfolios in scope Rows appear when Partners are assigned core schools with verified assessments."))
	}
	blocks := []*screensv1.PageBlock{
		panel("Core School Outcomes by Staff", "Average verified core score of each staff portfolio — school-outcome context, not a performance rating.", staff),
		panel("Core School Outcomes by Partner", "Average verified core score of schools assigned to each Partner.", partners),
	}
	region := oversight()
	if len(f.regions) == 0 {
		region = append(region, text("No regional comparison available No regions in the selected scope hold core schools."))
		blocks = append(blocks, panel("Performance by Region", "Average verified core score across regional teams.", region))
	} else {
		blocks = append(blocks, panel("Performance by Region", "Average verified core score across regional teams.", region))
		lines := []*screensv1.PagePanelItem{}
		var topRegion *insight
		for i, r := range f.regions {
			lines = append(lines, text(r.name))
			if r.score == nil {
				lines = append(lines, text("No verified assessments yet"))
				continue
			}
			lines = append(lines, text(allocations.FloatFormatFloat(*r.score, 1)+"/10"))
			if topRegion == nil {
				topRegion = &f.regions[i]
			}
		}
		if org != "" {
			lines = append(lines, text("Org average: "+org+" (marker line)"))
		}
		blocks = append(blocks, panel("", "", feeddom.Paired(lines)))
		if topRegion != nil {
			helper := fmt.Sprintf("%s · %d core schools", topRegion.name, topRegion.schools)
			if topRegion.vsAvg != nil {
				helper += " · " + pyFloat(*topRegion.vsAvg) + " vs org average"
			}
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
				Title: "Performance overview", Metrics: []*screensv1.PageMetric{
					metric("Top performing region", allocations.FloatFormatFloat(*topRegion.score, 1)+"/10", helper)}}}})
		}
	}
	blocks = append(blocks,
		panel("Staff vs Partner by Intervention", "Average verified core score per intervention (0–10); gap in score points.",
			append(oversight(), text("Not enough comparable data. A row appears only when an intervention has both staff-led and Partner-owned slots with verified scores — comparisons are never invented from one side."))),
		panel("Verified Assessment Outcome Trend", "Average verified core assessment score across real assessment periods.",
			append(oversight(), text("Not enough comparable assessment history yet The trend appears once at least two verified assessment periods exist for this scope."))),
	)
	return blocks, nil
}

// interventionComparable is whether staff_partner_splits holds a comparison:
// an intervention with both a staff-led and a partner-owned slot this year,
// each side with a live score.
func (pg *page) interventionComparable(ctx context.Context) (bool, error) {
	pks, codes := ids(pg.all)
	var any bool
	err := pg.db.QueryRow(ctx, `
WITH sides AS (
  SELECT DISTINCT sl.school_id, sl.intervention, CASE WHEN sl.owner = 'partner' THEN 'partner' ELSE 'staff' END AS side
  FROM core_activity_slot sl JOIN core_plan p ON p.id = sl.core_plan_id WHERE p.fy = $2 AND sl.school_id = ANY($1)),
scored AS (
  SELECT DISTINCT s.school_id, sc.intervention FROM ssa_score sc JOIN ssa_record r ON r.id = sc.ssa_record_id
  JOIN school s ON s.id = r.school_id WHERE r.deleted_at IS NULL AND s.id = ANY($3))
SELECT EXISTS (
  SELECT 1 FROM sides a JOIN scored sa ON sa.school_id = a.school_id AND sa.intervention = a.intervention
  WHERE a.side = 'staff' AND EXISTS (
    SELECT 1 FROM sides b JOIN scored sb ON sb.school_id = b.school_id AND sb.intervention = b.intervention
    WHERE b.side = 'partner' AND b.intervention = a.intervention))`, codes, pg.fy, pks).Scan(&any)
	if err != nil {
		return false, fmt.Errorf("coreschools: reading the staff and partner comparison: %w", err)
	}
	return any, nil
}

// verifiedTrend is whether get_monthly_trend has two months or more.
func (pg *page) verifiedTrend(ctx context.Context) (bool, error) {
	pks, _ := ids(pg.all)
	var months int
	err := pg.db.QueryRow(ctx, `SELECT count(DISTINCT date_trunc('month', date_of_ssa AT TIME ZONE 'Africa/Nairobi')) FROM ssa_record
WHERE school_id = ANY($1) AND deleted_at IS NULL AND verification_status = 'confirmed' AND average_score IS NOT NULL
  AND date_of_ssa IS NOT NULL`, pks).Scan(&months)
	if err != nil {
		return false, fmt.Errorf("coreschools: reading the assessment months: %w", err)
	}
	return months >= 2, nil
}
