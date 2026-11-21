package coreschools

import (
	"context"
	"fmt"
	"slices"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// option is a select's choice.
type option struct{ value, label string }

// selectFilter is a select as the feed reads it: the chosen option's value,
// the first when none is chosen.
func selectFilter(name, label, caption, chosen string, options []option) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label, Caption: caption}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: o.label})
		if o.value == chosen && f.Value == "" {
			f.Value = o.value
		}
	}
	if f.Value == "" && len(options) > 0 {
		f.Value = options[0].value
	}
	return f
}

// filterBlock is partials/core_schools/filters.html.
func (pg *page) filterBlock(ctx context.Context) (*screensv1.PageBlock, error) {
	years := []option{}
	for _, y := range schooldirectory.FYOptions(pg.now) {
		years = append(years, option{y, y})
	}
	_, codes := ids(pg.all)
	pks, _ := ids(pg.all)
	districts := []option{{"All", "All Districts"}}
	rows, err := pg.db.Query(ctx, `SELECT id, name FROM district WHERE id IN (SELECT district_id FROM school WHERE id = ANY($1)) ORDER BY name`, pks)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the districts: %w", err)
	}
	for rows.Next() {
		var o option
		if err := rows.Scan(&o.value, &o.label); err != nil {
			rows.Close()
			return nil, fmt.Errorf("coreschools: reading a district: %w", err)
		}
		districts = append(districts, o)
	}
	rows.Close()
	staff := []option{{"All", "All Staff"}}
	rows, err = pg.db.Query(ctx, `
SELECT sp.user_id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.user_id IN (SELECT account_owner_id FROM school WHERE id = ANY($1) AND account_owner_id IS NOT NULL)
ORDER BY u.name`, pks)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the owners: %w", err)
	}
	for rows.Next() {
		var o option
		if err := rows.Scan(&o.value, &o.label); err != nil {
			rows.Close()
			return nil, fmt.Errorf("coreschools: reading an owner: %w", err)
		}
		staff = append(staff, o)
	}
	rows.Close()
	partners := []option{{"All", "All Partners"}}
	rows, err = pg.db.Query(ctx, `
SELECT p.id, p.name FROM partner p WHERE p.id IN (
  SELECT pa.partner_id FROM partner_assignment pa JOIN school s ON s.id = pa.school_id
  WHERE s.school_type = 'core' AND NOT (pa.status = ANY($1)))
ORDER BY p.name`, rules.PartnerReleased)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the partners: %w", err)
	}
	for rows.Next() {
		var o option
		if err := rows.Scan(&o.value, &o.label); err != nil {
			rows.Close()
			return nil, fmt.Errorf("coreschools: reading a partner: %w", err)
		}
		partners = append(partners, o)
	}
	rows.Close()
	_ = codes
	f := pg.f
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			selectFilter("fy", "Fiscal year", "FY", pg.fy, years),
			selectFilter("district", "District", "", f.district, districts),
			selectFilter("staff", "Staff", "", f.staff, staff),
			selectFilter("partner", "Partner", "", f.partner, partners),
			selectFilter("school_type_filter", "School type", "", f.schoolType, []option{{"All", "All types"}, {"core", "Core"},
				{"core_trained", "Core Trained"}, {"core_graduate", "Core Graduate"}, {"champion", "Champion"}}),
			selectFilter("ssa_status", "SSA status", "", f.ssaStatus, []option{{"All", "All"}, {"done", "Complete"}, {"not_done", "Pending"}}),
			selectFilter("partner_assigned", "Partner assignment status", "Partner status", f.partnerAssigned,
				[]option{{"All", "All"}, {"assigned", "Partner Assigned"}, {"unassigned", "Not Assigned"}}),
		},
		Hidden: pg.hidden(),
	}}}, nil
}

// metric is a context-metrics tile as the feed reads it.
func metric(label, value, helper string) *screensv1.PageMetric {
	m := &screensv1.PageMetric{Label: label, Value: value, Helper: schoolprofile.BriefHelper(helper)}
	if m.Helper != helper {
		m.Note = helper
	}
	return m
}

func percent(part, whole int) int {
	if whole == 0 {
		return 0
	}
	return int(float64(part) / float64(whole) * 100)
}

// kpis is the "Current portfolio context" strip.
func (pg *page) kpis(ctx context.Context) (*screensv1.PageBlock, error) {
	pks, codes := ids(pg.all)
	total := len(pg.all)
	ready := 0
	regions := map[string]bool{}
	for _, sc := range pg.all {
		if sc.ssaStatus == "done" {
			ready++
		}
		regions[sc.regionID] = true
	}
	avg, err := averageScore(ctx, pg.db, pks)
	if err != nil {
		return nil, err
	}
	var visits, trainings int
	core := schoolprofile.GateRules().Core
	rows, err := pg.db.Query(ctx, `SELECT coalesce(sl.activity_type, ''), coalesce(sl.status, '') FROM core_activity_slot sl
JOIN core_plan p ON p.id = sl.core_plan_id WHERE p.school_id = ANY($1) AND p.fy = $2`, codes, pg.fy)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the scheduled slots: %w", err)
	}
	for rows.Next() {
		var kind, status string
		if err := rows.Scan(&kind, &status); err != nil {
			rows.Close()
			return nil, fmt.Errorf("coreschools: reading a scheduled slot: %w", err)
		}
		if !core.SlotTaken(status) {
			continue
		}
		switch kind {
		case "visit":
			visits++
		case "training":
			trainings++
		}
	}
	rows.Close()
	var allRegions int
	if err := pg.db.QueryRow(ctx, `SELECT count(*) FROM region`).Scan(&allRegions); err != nil {
		return nil, fmt.Errorf("coreschools: counting the regions: %w", err)
	}
	perf, err := pg.perf(ctx)
	if err != nil {
		return nil, err
	}
	delta, deltaHelper := "—", "No paired SSA cycles yet"
	if perf.delta != nil {
		d := *perf.delta
		sign, ahead := "", "Partner"
		if d >= 0 {
			sign, ahead = "+", "Staff"
		}
		delta, deltaHelper = sign+pyFloat(d), "score points · "+ahead+" ahead"
	}
	target := total * 4
	covered := len(regions)
	if total == 0 {
		covered = 0
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Current portfolio context",
		Metrics: []*screensv1.PageMetric{
			metric("Total Core Schools", strconv.Itoa(total), ""),
			metric("Core Schools Ready for Planning", strconv.Itoa(ready), fmt.Sprintf("%d%% of core", percent(ready, total))),
			metric("Avg. Core Assessment Score", pyFloat(pyRound(avg, 1))+"/10", ""),
			metric("Visits Scheduled", fmt.Sprintf("%d / %d", visits, target), fmt.Sprintf("%d%% complete", percent(visits, target))),
			metric("Trainings Scheduled", fmt.Sprintf("%d / %d", trainings, target), fmt.Sprintf("%d%% complete", percent(trainings, target))),
			metric("Staff vs Partner Performance Delta", delta, deltaHelper),
			metric("Regions Covered", fmt.Sprintf("%d / %d", covered, allRegions), fmt.Sprintf("%d%% coverage", percent(covered, allRegions))),
		}}}}, nil
}

// averageScore is CoreAssessmentService.get_average_score: the average of
// each school's latest live SSA record's average, to two places; 0.0 for
// none.
func averageScore(ctx context.Context, db schooldirectory.Querier, pks []string) (float64, error) {
	var avg *float64
	if err := db.QueryRow(ctx, `
SELECT avg(average_score) FROM (
  SELECT DISTINCT ON (school_id) average_score FROM ssa_record
  WHERE school_id = ANY($1) AND deleted_at IS NULL ORDER BY school_id, date_of_ssa DESC) latest`, pks).Scan(&avg); err != nil {
		return 0, fmt.Errorf("coreschools: reading the average score: %w", err)
	}
	if avg == nil {
		return 0, nil
	}
	return pyRound(*avg, 2), nil
}

var _ = slices.Contains[[]string]

// hidden is the filter form's hidden inputs: the page, its size and, on the
// read-only lens, the lens.
func (pg *page) hidden() map[string]string {
	out := map[string]string{"page": strconv.Itoa(pg.number), "per_page": strconv.Itoa(pg.perPage)}
	switch {
	case pg.oversight:
		out["lens"] = "oversight"
	case pg.hasTeamCore:
		out["lens"] = "mine"
	}
	return out
}
