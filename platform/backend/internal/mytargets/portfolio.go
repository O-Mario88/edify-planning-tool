package mytargets

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// strategicPriorities is strategic_priority_overview for the reader, as
// partials/targets/strategic_priority_overview.html draws it: nothing when
// the year has no governed priorities.
func strategicPriorities(ctx context.Context, db schooldirectory.Querier, pg *page) ([]*screensv1.PageBlock, error) {
	if pg.p.StaffProfileID == "" {
		// Read only for a People record (a partner's login has none).
		return nil, nil
	}
	return StrategicPriorityBlocks(ctx, db, pg.fy, []string{pg.p.StaffProfileID}, "your personal target ledger")
}

// StrategicPriorityBlocks is strategic_priority_overview(fy, staff_ids)
// through the template with its scope_label: the year's governed
// priorities, each with its milestones and those allocated to the people
// named; nothing when the year has none.
func StrategicPriorityBlocks(ctx context.Context, db schooldirectory.Querier, fy string, staffIDs []string,
	scopeLabel string) ([]*screensv1.PageBlock, error) {
	rows, err := db.Query(ctx, `
SELECT sp.title, sp.sequence,
       count(DISTINCT m.id),
       count(DISTINCT m.id) FILTER (WHERE m.active AND NOT m.requires_definition AND m.definition_status = 'approved'
                                    AND m.metric_definition_id IS NOT NULL),
       count(DISTINCT a.id) FILTER (WHERE a.status = 'approved' AND a.employee_id = ANY($2))
FROM hr_strategic_priority sp
LEFT JOIN hr_priority_milestone m ON m.priority_id = sp.id
LEFT JOIN hr_milestone_allocation a ON a.milestone_id = m.id
WHERE sp.fy = $1 AND sp.cycle_id IS NOT NULL
GROUP BY sp.id, sp.title, sp.sequence
ORDER BY sp.sequence, sp.title`, fy, staffIDs)
	if err != nil {
		return nil, fmt.Errorf("mytargets: the strategic priorities: %w", err)
	}
	defer rows.Close()
	var records []*screensv1.PageBlock
	for rows.Next() {
		var title string
		var sequence, milestones, ready, allocated int
		if err := rows.Scan(&title, &sequence, &milestones, &ready, &allocated); err != nil {
			return nil, fmt.Errorf("mytargets: the strategic priorities: %w", err)
		}
		// The feed reads the success pill as "good" and the others as plain.
		badge := &screensv1.PageBadge{Text: "Definition in progress", Tone: "plain"}
		switch {
		case allocated > 0:
			badge = &screensv1.PageBadge{Text: "Allocated", Tone: "good"}
		case ready > 0:
			badge.Text = "Ready for allocation"
		}
		records = append(records, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Record{Record: &screensv1.PageRecord{
			Title: title, Subtitle: fmt.Sprintf("Priority %d", sequence),
			Badges: []*screensv1.PageBadge{badge},
			Facts: []*screensv1.PageFact{{Label: "Milestones", Value: strconv.Itoa(milestones)},
				{Label: "In this scope", Value: strconv.Itoa(allocated)}},
		}}})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(records) == 0 {
		return nil, nil
	}
	head := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title:    "FY " + fy + " Strategic Priorities",
		Subtitle: "The governed priority portfolio is shown for context. Only active, approved milestone allocations affect " + scopeLabel + ".",
		Items:    []*screensv1.PagePanelItem{text(fmt.Sprintf("%d priorities", len(records)))},
	}}}
	out := append([]*screensv1.PageBlock{head}, records...)
	return append(out, textPanel("", "Milestones still in definition remain visible here, but they do not create targets, reduce achievement, or generate risk.")), nil
}

// portfolioRow is one row of a priority group, as the feed reads it: its
// action, where the action goes, and its title.
type portfolioRow struct{ title, action, url string }

// priorityPortfolio is priority_portfolio as
// partials/targets/priority_portfolio.html draws it; the planning feed is
// the reader's approved milestones.
func priorityPortfolio(ctx context.Context, db schooldirectory.Querier, pg *page, planning []portfolioRow) (*screensv1.PageBlock, error) {
	panel := &screensv1.PagePanel{
		Title:    "My Priority Portfolio",
		Subtitle: "Your planning, school assessment, agreed priorities and professional development in one place.",
	}
	if pg.p.StaffProfileID == "" {
		// Without a People record the portfolio has no groups.
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: panel}}, nil
	}
	ssa, err := ssaFocus(ctx, db, pg)
	if err != nil {
		return nil, err
	}
	manual, err := manualPriorities(ctx, db, pg)
	if err != nil {
		return nil, err
	}
	development, err := developmentPriorities(ctx, db, pg)
	if err != nil {
		return nil, err
	}
	for _, g := range []struct {
		label string
		rows  []portfolioRow
	}{{"Planning feed", planning}, {"SSA focus", ssa}, {"Manual priorities", manual}, {"Professional development", development}} {
		panel.Items = append(panel.Items, heading(g.label), toned(strconv.Itoa(len(g.rows)), "neutral"))
		if len(g.rows) == 0 {
			panel.Items = append(panel.Items, text("Nothing open for FY"+pg.fy+"."))
			continue
		}
		ls := []*screensv1.PageLink{}
		for _, r := range g.rows {
			ls = append(ls, &screensv1.PageLink{Text: r.action + " →", Href: r.url, Caption: r.title})
		}
		panel.Items = append(panel.Items, links(ls...))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: panel}}, nil
}

// heldSchools are the reader's assigned schools that are operating, by id,
// with their operational codes.
func heldSchools(ctx context.Context, db schooldirectory.Querier, pg *page) ([]string, map[string]string, error) {
	rows, err := db.Query(ctx, `SELECT s.id, s.school_id FROM school s
WHERE s.id IN (SELECT school_id FROM staff_school_assignment WHERE staff_id = $1)
  AND s.deleted_at IS NULL AND s.operational_status = ANY($2)`, pg.p.StaffProfileID, rules.OperatingStatuses)
	if err != nil {
		return nil, nil, fmt.Errorf("mytargets: the reader's schools: %w", err)
	}
	defer rows.Close()
	var ids []string
	codes := map[string]string{}
	for rows.Next() {
		var id string
		var code *string
		if err := rows.Scan(&id, &code); err != nil {
			return nil, nil, fmt.Errorf("mytargets: the reader's schools: %w", err)
		}
		ids = append(ids, id)
		if code != nil {
			codes[id] = *code
		}
	}
	return ids, codes, rows.Err()
}

// ssaFocus is the portfolio's SSA group: the schools still owed this year's
// confirmed SSA, then each intervention scored below Strong in a school's
// latest confirmed SSA, weakest first.
func ssaFocus(ctx context.Context, db schooldirectory.Querier, pg *page) ([]portfolioRow, error) {
	schools, _, err := heldSchools(ctx, db, pg)
	if err != nil || len(schools) == 0 {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT DISTINCT ON (school_id) school_id, id FROM ssa_record
WHERE school_id = ANY($1) AND fy = $2 AND verification_status = 'confirmed' AND deleted_at IS NULL
ORDER BY school_id, date_of_ssa DESC, created_at DESC`, schools, pg.fy)
	if err != nil {
		return nil, fmt.Errorf("mytargets: the schools' SSAs: %w", err)
	}
	latest, records := map[string]bool{}, []string{}
	for rows.Next() {
		var school, id string
		if err := rows.Scan(&school, &id); err != nil {
			rows.Close()
			return nil, fmt.Errorf("mytargets: the schools' SSAs: %w", err)
		}
		latest[school] = true
		records = append(records, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var out []portfolioRow
	missing := map[string]bool{}
	for _, s := range schools {
		if !latest[s] {
			missing[s] = true
		}
	}
	if len(missing) > 0 {
		home := rules.SSAHomes[pg.p.ActiveRole]
		out = append(out, portfolioRow{title: "Complete current-FY SSA coverage", action: "Open " + home.Label,
			url: strings.ReplaceAll(home.Href, rules.Reader, url.PathEscape(pg.p.UserID))})
	}
	if len(records) == 0 {
		return out, nil
	}
	// The records' scores as the prefetch reads them: unordered, record by
	// record in the order the records came.
	scores, err := db.Query(ctx, `SELECT ssa_record_id, intervention, score::float8 FROM ssa_score WHERE ssa_record_id = ANY($1)`, records)
	if err != nil {
		return nil, fmt.Errorf("mytargets: the SSA scores: %w", err)
	}
	byRecord := map[string][][2]any{}
	for scores.Next() {
		var record, intervention string
		var score float64
		if err := scores.Scan(&record, &intervention, &score); err != nil {
			scores.Close()
			return nil, fmt.Errorf("mytargets: the SSA scores: %w", err)
		}
		byRecord[record] = append(byRecord[record], [2]any{intervention, score})
	}
	scores.Close()
	if err := scores.Err(); err != nil {
		return nil, err
	}
	order, weak := []string{}, map[string][]float64{}
	for _, r := range records {
		for _, s := range byRecord[r] {
			intervention, score := s[0].(string), s[1].(float64)
			if score >= 8 {
				continue
			}
			if _, ok := weak[intervention]; !ok {
				order = append(order, intervention)
			}
			weak[intervention] = append(weak[intervention], score)
		}
	}
	lowest := func(k string) float64 {
		m := math.Inf(1)
		for _, v := range weak[k] {
			m = math.Min(m, v)
		}
		return m
	}
	sort.SliceStable(order, func(i, j int) bool { return lowest(order[i]) < lowest(order[j]) })
	for _, k := range order {
		label, ok := rules.InterventionLabels[k]
		if !ok {
			label = pyTitle(strings.ReplaceAll(k, "_", " "))
		}
		out = append(out, portfolioRow{title: label, action: "Plan response",
			url: "/planning?fy=" + pg.fy + "&priority_source=ssa&intervention=" + k})
	}
	return out, nil
}

// manualPriorities are the latest review's priorities agreed by hand.
func manualPriorities(ctx context.Context, db schooldirectory.Querier, pg *page) ([]portfolioRow, error) {
	rows, err := db.Query(ctx, `SELECT outcome_statement FROM hr_performance_priority
WHERE source_rule_id IS NULL AND review_id = (SELECT id FROM hr_performance_review WHERE staff_id = $1 AND fy = $2
                                              ORDER BY created_at DESC LIMIT 1)
ORDER BY sequence`, pg.p.StaffProfileID, pg.fy)
	if err != nil {
		return nil, fmt.Errorf("mytargets: the agreed priorities: %w", err)
	}
	defer rows.Close()
	var out []portfolioRow
	for rows.Next() {
		var title string
		if err := rows.Scan(&title); err != nil {
			return nil, fmt.Errorf("mytargets: the agreed priorities: %w", err)
		}
		out = append(out, portfolioRow{title: title, action: "View agreement", url: "/performance-conversation"})
	}
	return out, rows.Err()
}

// developmentPriorities are the reader's professional development requests
// of the year.
func developmentPriorities(ctx context.Context, db schooldirectory.Querier, pg *page) ([]portfolioRow, error) {
	rows, err := db.Query(ctx, `SELECT course_name FROM pd_request WHERE staff_id = $1 AND fy = $2 ORDER BY start_date, created_at`,
		pg.p.StaffProfileID, pg.fy)
	if err != nil {
		return nil, fmt.Errorf("mytargets: the development requests: %w", err)
	}
	defer rows.Close()
	var out []portfolioRow
	for rows.Next() {
		var title string
		if err := rows.Scan(&title); err != nil {
			return nil, fmt.Errorf("mytargets: the development requests: %w", err)
		}
		out = append(out, portfolioRow{title: title, action: "View development", url: "/my-professional-development/?fy=" + pg.fy})
	}
	return out, rows.Err()
}

// coreTracker is _build_core_tracker as the page draws it: the package of
// each Core School the reader holds, the twelve furthest along.
func coreTracker(ctx context.Context, db schooldirectory.Querier, pg *page) ([]*screensv1.PageBlock, error) {
	_, codes, err := heldSchools(ctx, db, pg)
	if err != nil {
		return nil, err
	}
	list := []string{}
	for _, c := range codes {
		list = append(list, c)
	}
	type row struct {
		code, name, status string
		avg                *float64
		visits, trainings  int
		pct                int
	}
	var tracked []row
	if len(list) > 0 {
		rows, err := db.Query(ctx, `SELECT c.school_id, COALESCE((SELECT s.name FROM school s WHERE s.school_id = c.school_id AND s.deleted_at IS NULL ORDER BY s.id DESC LIMIT 1), c.school_id),
       c.visits_completed, c.trainings_completed, c.baseline_average
FROM core_plan c WHERE c.school_id = ANY($1) ORDER BY c.school_id`, list)
		if err != nil {
			return nil, fmt.Errorf("mytargets: the Core plans: %w", err)
		}
		for rows.Next() {
			var r row
			var visits, trainings *int
			if err := rows.Scan(&r.code, &r.name, &visits, &trainings, &r.avg); err != nil {
				rows.Close()
				return nil, fmt.Errorf("mytargets: the Core plans: %w", err)
			}
			if visits != nil {
				r.visits = min(*visits, 4)
			}
			if trainings != nil {
				r.trainings = min(*trainings, 4)
			}
			done := r.visits + r.trainings
			switch {
			case done >= 8:
				r.status = "Complete"
			case r.avg != nil && done > 0:
				r.status = "On Track"
			case r.avg != nil:
				r.status = "Not Started"
			default:
				r.status = "SSA Required"
			}
			r.pct = round(float64(done) / 8 * 100)
			tracked = append(tracked, r)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	sort.SliceStable(tracked, func(i, j int) bool {
		if tracked[i].pct != tracked[j].pct {
			return tracked[i].pct > tracked[j].pct
		}
		return tracked[i].name < tracked[j].name
	})
	total := len(tracked)
	if len(tracked) > 12 {
		tracked = tracked[:12]
	}
	panel := &screensv1.PagePanel{Title: "Core School Tracker", Subtitle: "The core package per school — SSA assessment, 4 visits and 4 trainings."}
	if total > 0 {
		label := "Open Core Schools →"
		if total > 12 {
			label = fmt.Sprintf("All %d core schools →", total)
		}
		panel.Items = append(panel.Items, links(&screensv1.PageLink{Text: label, Href: "/core-schools"}))
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: panel}}}
	if len(tracked) == 0 {
		panel.Items = append(panel.Items, text("When a school in your portfolio is onboarded as a core school, its 4 visits + 4 trainings package is tracked here."))
		return out, nil
	}
	cols := []*screensv1.PageColumn{}
	for _, c := range []string{"ID", "Core School", "Average SSA Score", "Visits (4)", "Trainings (4)", "Package"} {
		cols = append(cols, &screensv1.PageColumn{Label: c})
	}
	cols = append(cols, &screensv1.PageColumn{Label: "Status", Numeric: true})
	rows := []*screensv1.PageRow{}
	for _, r := range tracked {
		avg := "—"
		if r.avg != nil {
			avg = allocations.FloatFormatFloat(*r.avg, 1) + "/10"
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: r.code}, {Text: r.name, Href: "/schools/" + r.code}, {Text: avg},
			{Text: fmt.Sprintf("%d/4", r.visits)}, {Text: fmt.Sprintf("%d/4", r.trainings)}, {Text: fmt.Sprintf("%d%%", r.pct)},
			{Text: r.status, Tone: "primary", Badge: true},
		}})
	}
	return append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: cols, Rows: rows}}}), nil
}

// pyTitle is Python's str.title(): each run of letters capitalised.
func pyTitle(s string) string {
	out := []rune{}
	prev := false
	for _, r := range s {
		isLetter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case isLetter && !prev:
			out = append(out, []rune(strings.ToUpper(string(r)))...)
		case isLetter:
			out = append(out, []rune(strings.ToLower(string(r)))...)
		default:
			out = append(out, r)
		}
		prev = isLetter
	}
	return string(out)
}
