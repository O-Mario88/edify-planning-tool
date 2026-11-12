package schoolprofile

import (
	"context"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The SSA tab of a school's profile: the engine's Intervention Matrix and
// charts (partials/profiles/_sections.html, chart_tags), then the school's
// own SSA records (partials/schools/_ssa_records.html, built by
// analytics.ia_workflow.school_progress).

func (s *Service) ssaTab(ctx context.Context, sc school, l lens) ([]*screensv1.PageBlock, error) {
	book, err := s.ruleBook(ctx)
	if err != nil {
		return nil, err
	}
	cmp, err := s.interventionComparison(ctx, sc.ID, l.fy)
	if err != nil {
		return nil, err
	}
	for i := range cmp.rows {
		cmp.rows[i].verdict = book.interventionChange(cmp.rows[i].key, cmp.rows[i].previous, cmp.rows[i].current)
	}
	overall := book.overallChange(cmp.previous, cmp.current)
	scores, err := s.schoolYearScores(ctx, []string{sc.ID}, l.fy)
	if err != nil {
		return nil, err
	}
	yearLabel, previousLabel := fyLabel(l.fy), fyLabel(previousFY(l.fy))
	records := l.records()
	target := rules.Engine.SSATarget

	// ── Intervention Matrix ────────────────────────────────────────────────
	toTarget := func(current *float64) *screensv1.PageCell {
		if current == nil {
			return &screensv1.PageCell{Text: "—"}
		}
		left := pyRound(math.Max(target-*current, 0), 2)
		if left == 0 {
			return &screensv1.PageCell{Text: "Reached", Tone: "success"}
		}
		return &screensv1.PageCell{Text: twoPlaces(left)}
	}
	changeCell := func(c change) *screensv1.PageCell {
		if c.delta == nil {
			return &screensv1.PageCell{Text: "—"}
		}
		return &screensv1.PageCell{Text: signedTwoPlaces(*c.delta), Tone: c.tone()}
	}
	targetText := floatformat(target, 1)
	matrix := &screensv1.PageTable{
		Title: "Intervention Matrix",
		Subtitle: fmt.Sprintf("%s school%s in %s · %s in %s", intcomma(cmp.previousSchools), plural(cmp.previousSchools),
			previousLabel, intcomma(cmp.schools), yearLabel),
		Columns: []*screensv1.PageColumn{{Label: "Intervention"}, {Label: "Previous (" + previousLabel + ")", Numeric: true},
			{Label: "Current (" + yearLabel + ")", Numeric: true}, {Label: "Change", Numeric: true}, {Label: "Status"},
			{Label: "Target", Numeric: true}, {Label: "To Target", Numeric: true}},
	}
	for _, r := range cmp.rows {
		matrix.Rows = append(matrix.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: r.label, Href: records + "intervention&key=" + r.key},
			{Text: score(r.previous)}, {Text: score(r.current), Strong: true}, changeCell(r.verdict),
			{Text: r.verdict.label()}, {Text: targetText}, toTarget(r.current),
		}})
	}
	matrix.Rows = append(matrix.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: "All interventions", Href: records + "ssa"},
		{Text: score(cmp.previous)}, {Text: score(cmp.current), Strong: true}, changeCell(overall),
		{Text: overall.label()}, {Text: targetText}, toTarget(cmp.current),
	}})
	atTarget := 0
	if mine := scores[sc.ID]; mine.current != nil && *mine.current >= target {
		atTarget = 1
	}
	isAre := "are"
	if atTarget == 1 {
		isAre = "is"
	}
	matrix.Footnote = fmt.Sprintf("%s school%s %s at or above the target of %s. A school's score for a year is its latest confirmed SSA of that year. %s",
		intcomma(atTarget), plural(atTarget), isAre, targetText, rules.Engine.RuleSentence)
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: matrix}}}

	// ── SSA score by intervention (chart_tags.ssa_year_chart) ──────────────
	hasCurrent, hasPrevious := false, false
	names, previous, current := []string{}, []float64{}, []float64{}
	value := func(v *float64) float64 {
		if v == nil {
			return 0
		}
		return *v
	}
	for _, r := range cmp.rows {
		hasCurrent = hasCurrent || r.current != nil
		hasPrevious = hasPrevious || r.previous != nil
		names = append(names, r.label)
		previous, current = append(previous, value(r.previous)), append(current, value(r.current))
	}
	if hasCurrent || hasPrevious {
		subtitle := yearLabel
		series := []*screensv1.PageSeries{{Name: yearLabel, Values: current}}
		if hasPrevious {
			subtitle = previousLabel + " and " + yearLabel
			series = append([]*screensv1.PageSeries{{Name: previousLabel, Values: previous}}, series...)
		}
		blocks = append(blocks, ssaChart("SSA score by intervention", subtitle, names, series))
	}

	// ── Annual SSA Progress (ssa.services.get_ssa_progress_by_fy) ──────────
	progress, err := s.progressByYear(ctx, sc.ID)
	if err != nil {
		return nil, err
	}
	if len(progress.years) > 0 {
		blocks = append(blocks, ssaChart("Annual SSA Progress", "Average confirmed SSA score of these schools, by financial year.",
			progress.years, []*screensv1.PageSeries{{Name: "Average SSA score", Values: progress.averages}}))
	}

	own, err := s.schoolProgress(ctx, sc, book)
	if err != nil {
		return nil, err
	}
	return append(blocks, own...), nil
}

func ssaChart(title, subtitle string, categories []string, series []*screensv1.PageSeries) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: &screensv1.PageChart{
		Title: title, Subtitle: subtitle, Horizontal: true, Categories: categories, Series: series,
		Min: 0, Max: 10, AxisTitle: "SSA score (0–10)",
	}}}
}

type progressRows struct {
	years    []string
	averages []float64
}

// progressByYear is every confirmed record's average, year by year, and the
// schools assessed in it.
func (s *Service) progressByYear(ctx context.Context, schoolID string) (progressRows, error) {
	var out progressRows
	rows, err := s.db.Query(ctx, `
SELECT fy, AVG(average_score), COUNT(DISTINCT school_id) FROM ssa_record
WHERE school_id = $1 AND verification_status = 'confirmed' AND deleted_at IS NULL
GROUP BY fy ORDER BY fy`, schoolID)
	if err != nil {
		return out, fmt.Errorf("schoolprofile: reading SSA progress: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var fy string
		var average *float64
		var n int
		if err := rows.Scan(&fy, &average, &n); err != nil {
			return out, err
		}
		v := 0.0
		if average != nil {
			v = pyRound(*average, 2)
		}
		out.years = append(out.years, fmt.Sprintf("%s (%d school%s)", fyLabel(fy), n, plural(n)))
		out.averages = append(out.averages, v)
	}
	return out, rows.Err()
}

// ssaRecordRow is one of the school's SSA records.
type ssaRecordRow struct {
	id, fy, status, source string
	onVisit                bool
	held                   time.Time
	average                *float64
}

// ssaPair is a confirmed assessment and the one of the year after it.
type ssaPair struct{ before, after ssaRecordRow }

// schoolProgress is ia_workflow.school_progress as the page draws it: the
// change between confirmed assessments of consecutive years, with the
// verified support between them, and every record.
func (s *Service) schoolProgress(ctx context.Context, sc school, book ruleBook) ([]*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, fy, date_of_ssa, average_score, verification_status, COALESCE(verification_source, ''), COALESCE(source_activity_id, '') <> ''
FROM ssa_record WHERE school_id = $1 AND deleted_at IS NULL ORDER BY date_of_ssa DESC, created_at DESC`, sc.ID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading SSA records: %w", err)
	}
	all := []ssaRecordRow{}
	for rows.Next() {
		var r ssaRecordRow
		if err := rows.Scan(&r.id, &r.fy, &r.held, &r.average, &r.status, &r.source, &r.onVisit); err != nil {
			rows.Close()
			return nil, err
		}
		all = append(all, r)
	}
	rows.Close()
	confirmed := []ssaRecordRow{}
	for _, r := range all {
		if r.status == "confirmed" {
			confirmed = append(confirmed, r)
		}
	}
	newerUnconfirmed := 0
	for _, r := range all {
		if r.status != "confirmed" && (len(confirmed) == 0 || r.held.After(confirmed[0].held)) {
			newerUnconfirmed++
		}
	}

	// The latest confirmed record of each year, newest year first, and the
	// pairs of consecutive years.
	byYear := map[string]ssaRecordRow{}
	years := []string{}
	for _, r := range confirmed {
		if _, seen := byYear[r.fy]; !seen {
			byYear[r.fy] = r
			years = append(years, r.fy)
		}
	}
	yearOf := func(fy string) int {
		n, err := strconv.Atoi(fy)
		if err != nil {
			return 0
		}
		return n
	}
	// Python's sorted is stable; an insertion sort keeps equals in order.
	for i := 1; i < len(years); i++ {
		for j := i; j > 0 && yearOf(years[j]) > yearOf(years[j-1]); j-- {
			years[j], years[j-1] = years[j-1], years[j]
		}
	}
	pairs := []ssaPair{}
	for _, newer := range years {
		if n, err := strconv.Atoi(newer); err == nil {
			if older, ok := byYear[strconv.Itoa(n-1)]; ok {
				pairs = append(pairs, ssaPair{older, byYear[newer]})
			}
		}
		if len(pairs) >= rules.Engine.SchoolPairsShown {
			break
		}
	}

	change := &screensv1.PagePanel{Title: "SSA change between confirmed assessments", Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{}}
	if len(pairs) == 0 {
		change.Subtitle = "0 year-on-year comparisons"
		change.Items = append(change.Items, text("0 comparisons: this school does not yet have confirmed SSAs in two consecutive financial years."))
	} else {
		verdicts, err := s.pairVerdicts(ctx, sc, pairs, book)
		if err != nil {
			return nil, err
		}
		improved, declined := 0, 0
		for i, p := range pairs {
			v := verdicts[i]
			switch v.classification {
			case "improved":
				improved++
			case "declined":
				declined++
			}
			days := int(math.Floor(p.after.held.Sub(p.before.held).Hours() / 24))
			when := fmt.Sprintf("%s → %s · %d days apart", localJMY(p.before.held), localJMY(p.after.held), days)
			if v.ruleLabel != "" {
				when += " · " + v.ruleLabel
			}
			said := v.label
			if v.meanDelta != nil {
				// |floatformat:"+2" writes two places and no sign.
				said += " (" + floatformat(*v.meanDelta, 2) + ")"
			}
			support := "none recorded"
			if v.supportCount > 0 {
				noun := "activities"
				if v.supportCount == 1 {
					noun = "activity"
				}
				support = fmt.Sprintf("%d %s — %s", v.supportCount, noun, strings.Join(v.support, ", "))
				if v.supportCount > len(v.support) {
					support += " …"
				}
			}
			change.Items = append(change.Items,
				heading("FY"+p.before.fy+" vs FY"+p.after.fy),
				text(when),
				&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: said}, Tone: v.tone},
				text("Verified support between the readings: "+support+"."))
		}
		comparisons := "comparison"
		if len(pairs) != 1 {
			comparisons += "s"
		}
		change.Subtitle = fmt.Sprintf("%d improved · %d declined across %d year-on-year %s", improved, declined, len(pairs), comparisons)
	}

	history := &screensv1.PagePanel{Title: "SSA history", Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{}}
	if newerUnconfirmed > 0 {
		isAre := "are"
		if newerUnconfirmed == 1 {
			isAre = "is"
		}
		history.Items = append(history.Items, &screensv1.PagePanelItem{
			Kind: &screensv1.PagePanelItem_Text{Text: fmt.Sprintf("%d newer assessment%s %s not confirmed yet and %s not counted.",
				newerUnconfirmed, plural(newerUnconfirmed), isAre, isAre)},
			Tone: "warning",
		})
	}
	if len(all) == 0 {
		history.Items = append(history.Items, text("No SSA recorded for this school yet."))
	}
	for _, r := range all {
		said := label(rules.SSAStatuses, r.status)
		if r.status != "confirmed" {
			said += " • not counted"
		}
		said += " • Source: " + (ssaRecord{source: r.source, onVisit: r.onVisit}).sourceLabel()
		figure := "—"
		if r.average != nil {
			figure = floatformat(*r.average, 1)
		}
		history.Items = append(history.Items, text(localJMY(r.held)+" • FY"+r.fy),
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
				{Label: said, Value: figure},
			}}}})
	}
	return []*screensv1.PageBlock{panelBlock(change), panelBlock(history)}, nil
}

// pairVerdict is what the one rule calls a pair, and the support between.
type pairVerdict struct {
	classification, label, tone, ruleLabel string
	meanDelta                              *float64
	supportCount                           int
	support                                []string
}

// readingDay is a reading's day as stored (UTC), as the pairs' windows read it.
func readingDay(t time.Time) time.Time {
	u := t.UTC()
	return time.Date(u.Year(), u.Month(), u.Day(), 0, 0, 0, 0, time.UTC)
}

// pairVerdicts are change_rules.classify_pairs and school_verdicts over each
// pair's interventions, by the school's country's rules, and the verified
// activities delivered between the two readings.
func (s *Service) pairVerdicts(ctx context.Context, sc school, pairs []ssaPair, book ruleBook) ([]pairVerdict, error) {
	var country string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(TRIM(r.country), '') FROM school s LEFT JOIN region r ON r.id = s.region_id WHERE s.id = $1`,
		sc.ID).Scan(&country); err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the school's country: %w", err)
	}
	ids := []string{}
	for _, p := range pairs {
		ids = append(ids, p.before.id, p.after.id)
	}
	scores := map[string]map[string]float64{}
	rows, err := s.db.Query(ctx, `SELECT ssa_record_id, intervention, score FROM ssa_score WHERE ssa_record_id = ANY($1) AND score IS NOT NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading SSA scores: %w", err)
	}
	for rows.Next() {
		var id, intervention string
		var v float64
		if err := rows.Scan(&id, &intervention, &v); err != nil {
			rows.Close()
			return nil, err
		}
		if scores[id] == nil {
			scores[id] = map[string]float64{}
		}
		scores[id][intervention] = v
	}
	rows.Close()

	support, err := s.support(ctx, sc.ID, pairs)
	if err != nil {
		return nil, err
	}
	out := []pairVerdict{}
	for i, p := range pairs {
		start, end := readingDay(p.before.held), readingDay(p.after.held)
		farEnough := int(end.Sub(start).Hours()/24) >= rules.Engine.MinIntervalDays
		deltas, interventions := []float64{}, []string{}
		if farEnough {
			for _, code := range rules.Engine.InterventionOrder {
				before, okB := scores[p.before.id][code]
				after, okA := scores[p.after.id][code]
				if !okB || !okA {
					continue
				}
				c := between(before, after, book.ruleIn(code, country))
				deltas = append(deltas, *c.delta)
				interventions = append(interventions, code)
			}
		}
		v := pairVerdict{
			label: fmt.Sprintf("Not compared (readings less than %d days apart)", rules.Engine.MinIntervalDays),
			tone:  "neutral", supportCount: len(support[i]), support: support[i][:min(6, len(support[i]))],
		}
		if len(interventions) > 0 {
			mean := pyRound(pySum(deltas)/float64(len(deltas)), 4)
			rule, ruleLabel := book.schoolRuleIn(interventions, country)
			c := between(0, mean, rule)
			v.classification, v.meanDelta, v.ruleLabel = c.status, &mean, ruleLabel
			v.label = status(c.status)
			v.tone = rules.Engine.StateTones[c.status]
			if v.tone == "" {
				v.tone = "neutral"
			}
		}
		out = append(out, v)
	}
	return out, nil
}

// support are the verified activities at the school delivered inside each
// pair's window (after the first reading, up to the second), in the order
// the database returns them, as the existing page reads them.
func (s *Service) support(ctx context.Context, schoolID string, pairs []ssaPair) ([][]string, error) {
	out := make([][]string, len(pairs))
	earliest, latest := readingDay(pairs[0].before.held), readingDay(pairs[0].after.held)
	for _, p := range pairs[1:] {
		if d := readingDay(p.before.held); d.Before(earliest) {
			earliest = d
		}
		if d := readingDay(p.after.held); d.After(latest) {
			latest = d
		}
	}
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(activity_name_snapshot, ''), COALESCE(activity_type, ''), actual_delivery_date, planned_date
FROM activity WHERE school_id = $1 AND deleted_at IS NULL AND status = ANY($2)
  AND (actual_delivery_date >= $3::date OR (actual_delivery_date IS NULL AND planned_date >= $3::date))`,
		schoolID, rules.Engine.VerifiedActivityStatuses, earliest)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading verified support: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var name, kind string
		var actual, planned *time.Time
		if err := rows.Scan(&name, &kind, &actual, &planned); err != nil {
			return nil, err
		}
		delivered := actual
		if delivered == nil {
			delivered = planned
		}
		if delivered == nil || delivered.After(latest) {
			continue
		}
		what := name
		if what == "" {
			what = kind
		}
		for i, p := range pairs {
			if delivered.After(readingDay(p.before.held)) && !delivered.After(readingDay(p.after.held)) {
				out[i] = append(out[i], strings.ReplaceAll(what, "_", " "))
			}
		}
	}
	return out, rows.Err()
}
