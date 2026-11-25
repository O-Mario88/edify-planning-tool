package mytargets

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// period is one of get_page's period cards: the month, Q1 to Q4, the year.
type period struct {
	kind, label string
	months      []int
	pct         int
}

// areaCard is one agreed priority in the month.
type areaCard struct {
	area             targets.Area
	target, achieved int
	pct              *int
	status, tone     string
}

// figures is what get_page derives from the reader's targets and ledger.
type figures struct {
	areas    []targets.Area
	series   [2]targets.Series // targets, achieved
	periods  []period
	cards    []areaCard
	paceNow  int
	actual   []int
	expected []int
	focus    []focusItem
}

type focusItem struct {
	card   areaCard
	reason string
}

// round is Python's round() of a float to a whole number.
func round(x float64) int { return int(math.RoundToEven(x)) }

func share(a, t int) *int {
	if t == 0 {
		return nil
	}
	v := round(float64(a) / float64(t) * 100)
	return &v
}

// statusFor is MyTargetQueryService.status_for.
func statusFor(achieved, target, pace int, started bool) (string, string) {
	if target == 0 {
		return "Not Assigned", "neutral"
	}
	if !started {
		return "Not Started", "neutral"
	}
	pct := round(float64(achieved) / float64(target) * 100)
	switch {
	case pct > 100:
		return "Exceeded", "success"
	case pct == 100:
		return "Complete", "success"
	}
	gap := pace - pct
	switch {
	case gap <= rules.OnTrackBand:
		return "On Track", "success"
	case gap <= rules.AtRiskBand:
		return "At Risk", "warning"
	}
	return "Off Track", "danger"
}

func sum(s [12]int, months []int) int {
	n := 0
	for _, m := range months {
		n += s[m-1]
	}
	return n
}

func through(m int) []int {
	out := make([]int, m)
	for i := range out {
		out[i] = i + 1
	}
	return out
}

func (pg *page) figures(ctx context.Context, db schooldirectory.Querier) (*figures, error) {
	f := &figures{areas: pg.roster.Areas(pg.person)}
	tg, ach := pg.roster.Targets(pg.person), pg.roster.Achieved(pg.person)
	f.series = [2]targets.Series{tg, ach}
	weighted := func(months []int) int {
		pct, _, _ := targets.WeightedPct(f.areas, tg, ach, months)
		if pct == nil {
			return 0
		}
		return *pct
	}
	monthLabel := targets.MonthLabel(pg.fy, pg.month)
	f.periods = append(f.periods, period{kind: "month", label: monthLabel, months: []int{pg.month}})
	for _, q := range []string{"Q1", "Q2", "Q3", "Q4"} {
		f.periods = append(f.periods, period{kind: "quarter", label: q, months: targets.MonthsOfQuarter(q)})
	}
	f.periods = append(f.periods, period{kind: "fy", label: "FY", months: through(12)})
	for i := range f.periods {
		f.periods[i].pct = weighted(f.periods[i].months)
	}

	mStart, mEnd := targets.MonthRange(pg.fy, pg.month)
	f.paceNow = 100
	if pg.current {
		f.paceNow = pg.roster.Pace(pg.person, mStart, mEnd, pg.today)
	}
	started := !pg.today.Before(mStart)
	for _, a := range f.areas {
		t, got := tg[a.Key][pg.month-1], ach[a.Key][pg.month-1]
		status, tone := statusFor(got, t, f.paceNow, started)
		f.cards = append(f.cards, areaCard{area: a, target: t, achieved: got, pct: share(got, t), status: status, tone: tone})
	}

	// The cumulative trend: weighted actual and expected shares by month.
	for m := 1; m <= 12; m++ {
		wsum, psum, esum := 0, 0.0, 0.0
		for _, a := range f.areas {
			tf := sum(tg[a.Key], through(12))
			if tf > 0 {
				wsum += a.Weight
				psum += float64(sum(ach[a.Key], through(m))) / float64(tf) * 100 * float64(a.Weight)
				esum += float64(sum(tg[a.Key], through(m))) / float64(tf) * 100 * float64(a.Weight)
			}
		}
		actual, expected := 0, 0
		if wsum != 0 {
			actual, expected = round(psum/float64(wsum)), round(esum/float64(wsum))
		}
		f.expected = append(f.expected, expected)
		if pg.current && m > pg.currentMonth {
			actual = 0 // null in the chart, which the feed reads as 0
		}
		f.actual = append(f.actual, actual)
	}

	// The three furthest behind pace, unless on pace.
	behind := []areaCard{}
	for _, c := range f.cards {
		if c.target != 0 {
			behind = append(behind, c)
		}
	}
	gap := func(c areaCard) int {
		if c.pct == nil {
			return -f.paceNow
		}
		return *c.pct - f.paceNow
	}
	sort.SliceStable(behind, func(i, j int) bool { return gap(behind[i]) < gap(behind[j]) })
	if len(behind) > 3 {
		behind = behind[:3]
	}
	for _, c := range behind {
		switch c.status {
		case "Complete", "Exceeded", "On Track":
			continue
		}
		reason, err := gapReason(ctx, db, pg, c.area.Key, mStart, mEnd)
		if err != nil {
			return nil, err
		}
		f.focus = append(f.focus, focusItem{card: c, reason: reason})
	}
	return f, nil
}

func comma(n int) string {
	s := strconv.Itoa(n)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if neg {
		return "-" + s
	}
	return s
}

func pctText(p *int) string {
	if p == nil {
		return "—"
	}
	return strconv.Itoa(*p) + "%"
}

// top is the performance priorities (or their absence), the period matrix
// of the agreed priorities and the approved milestones, and the contract's
// own matrix.
func (f *figures) top(pg *page, c contract) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{f.priorities(pg)}
	if len(f.cards) > 0 || len(c.milestones) > 0 {
		out = append(out,
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Cumulative progress by time period"}}},
			f.matrix(pg, c), textPanel("", f.weighting()))
	}
	return append(out, c.matrix(pg)...)
}

// priorities is the agreed priorities' tiles, or their absence.
func (f *figures) priorities(pg *page) *screensv1.PageBlock {
	if len(f.cards) == 0 {
		panel := &screensv1.PagePanel{
			Title: "No measurable performance priorities agreed for FY " + pg.fy,
			Items: []*screensv1.PagePanelItem{text("This table is populated from your agreed performance priorities. Add a measurable priority and complete manager agreement to make it appear here.")},
		}
		if opens(pg.p.ActiveRole, "/my-performance") {
			panel.Items = append(panel.Items, links(&screensv1.PageLink{Text: "Open My Performance →", Href: "/my-performance"}))
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: panel}}
	}
	strip := &screensv1.PageStrip{Title: "Performance priorities"}
	for _, c := range f.cards {
		helper := c.status
		if c.pct != nil {
			helper = fmt.Sprintf("%d%% · %s", *c.pct, c.status)
		}
		m := &screensv1.PageMetric{Label: c.area.Label, Value: comma(c.achieved) + " / " + comma(c.target),
			Href: fmt.Sprintf("/my-targets/area-drawer?area=%s&fy=%s&month=%d", c.area.Key, pg.fy, pg.month)}
		brief := schoolprofile.BriefHelper(helper)
		m.Helper = brief
		if brief != helper {
			m.Note = helper
		}
		if brief != "" {
			m.Tone = c.tone
		}
		strip.Metrics = append(strip.Metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

// matrix is partials/targets/_period_matrix.html for the agreed priorities
// and the approved milestones.
func (f *figures) matrix(pg *page, c contract) *screensv1.PageBlock {
	cols := matrixColumns(pg)
	tg, ach := f.series[0], f.series[1]
	rows := []*screensv1.PageRow{}
	for _, a := range f.areas {
		cells := []*screensv1.PageCell{{Text: a.Label}}
		for _, pr := range f.periods {
			t, got := sum(tg[a.Key], pr.months), sum(ach[a.Key], pr.months)
			cells = append(cells, &screensv1.PageCell{Text: strconv.Itoa(t)}, &screensv1.PageCell{Text: strconv.Itoa(got)},
				&screensv1.PageCell{Text: pctText(share(got, t))})
		}
		rows = append(rows, &screensv1.PageRow{Cells: cells})
	}
	rows = append(rows, c.milestoneRows()...)
	overall := []*screensv1.PageCell{{Text: "Operational overall progress"}}
	for _, pr := range f.periods {
		overall = append(overall, &screensv1.PageCell{Text: strconv.Itoa(pr.pct) + "%"})
	}
	rows = append(rows, &screensv1.PageRow{Cells: overall})
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: cols, Rows: rows}}}
}

func (f *figures) weighting() string {
	parts := []string{}
	for _, c := range f.cards {
		parts = append(parts, fmt.Sprintf("%s %d%%", c.area.Label, c.area.Weight))
	}
	weights := ""
	if len(parts) > 0 {
		weights = " (" + strings.Join(parts, ", ") + ")"
	}
	return "Operational overall progress is priority-weighted" + weights +
		". Strategic milestone rows are approved allocations and are not weighted into it."
}

// charts are the cumulative trend and the contribution to the roll-up.
func (f *figures) charts(pg *page) []*screensv1.PageBlock {
	floats := func(xs []int) []float64 {
		out := make([]float64, len(xs))
		for i, x := range xs {
			out[i] = float64(x)
		}
		return out
	}
	trend := &screensv1.PageChart{
		Title: "Progress Trend (Cumulative, FY " + pg.fy + ")", Horizontal: true, Categories: monthLabels(),
		Series: []*screensv1.PageSeries{{Name: "Actual", Values: floats(f.actual)}, {Name: "Expected Target Pace", Values: floats(f.expected)}},
	}
	rollup := &screensv1.PageChart{Title: "Contribution to Roll-up", Horizontal: true, Max: 100, AxisTitle: "%"}
	values := []float64{}
	for _, pr := range f.periods {
		label := pr.label
		switch pr.kind {
		case "month":
			label += " (Monthly)"
		case "fy":
			label = "FY Cumulative"
		}
		rollup.Categories = append(rollup.Categories, label)
		values = append(values, float64(pr.pct))
	}
	rollup.Series = []*screensv1.PageSeries{{Name: "Contribution to Roll-up", Values: values}}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Chart{Chart: trend}},
		{Kind: &screensv1.PageBlock_Chart{Chart: rollup}},
	}
}

func monthLabels() []string {
	out := []string{}
	for m := 1; m <= 12; m++ {
		s, _ := targets.MonthRange("2027", m)
		out = append(out, s.Format("Jan"))
	}
	return out
}

// focusPanel is "Top Areas to Focus".
func (f *figures) focusPanel() *screensv1.PageBlock {
	panel := &screensv1.PagePanel{Title: "Top Areas to Focus"}
	if len(f.focus) == 0 {
		panel.Items = append(panel.Items, text("All assigned areas are on pace — keep executing the plan."))
	}
	for i, item := range f.focus {
		c := item.card
		action := rules.NextActions[c.area.Key]
		panel.Items = append(panel.Items, text(strconv.Itoa(i+1)), text(c.area.Label), text(c.status),
			text(fmt.Sprintf("%d of %d achieved · %s", c.achieved, c.target, item.reason)))
		if action[1] == "?mscs=new" {
			panel.Items = append(panel.Items, text(action[0]+" →"))
		} else {
			panel.Items = append(panel.Items, links(&screensv1.PageLink{Text: action[0] + " →", Href: action[1]}))
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: panel}}
}

// gapReason is MyTargetQueryService._gap_reason: the first thing holding
// the area's month back, from its pipeline.
func gapReason(ctx context.Context, db schooldirectory.Querier, pg *page, area string, start, end time.Time) (string, error) {
	c, err := CountPipeline(ctx, db, pg.userIDs(), pg.p.UserID, pg.fy, area, start, end)
	if err != nil {
		return "", err
	}
	switch {
	case c.PendingSF > 0:
		return fmt.Sprintf("%d completed item(s) missing Activity SF IDs — not yet credited", c.PendingSF), nil
	case c.IAPending > 0:
		return fmt.Sprintf("%d item(s) awaiting IA verification", c.IAPending), nil
	case c.Returned > 0:
		return fmt.Sprintf("%d returned item(s) need correction", c.Returned), nil
	case c.Provisional > 0:
		return fmt.Sprintf("%d item(s) awaiting review", c.Provisional), nil
	case c.Scheduled > 0:
		return fmt.Sprintf("%d scheduled item(s) not yet executed", c.Scheduled), nil
	}
	return "No activity planned yet this month", nil
}

// Pipeline is MyTargetQueryService._pipeline counted: how many of an
// area's items in the month sit in each of its lists.
type Pipeline struct {
	Validated, PendingSF, IAPending, Returned, Scheduled, Provisional int
}

// CountPipeline is _pipeline for a person (ids are every id their work is
// recorded under, userID their account) in fy's month [start, end).
func CountPipeline(ctx context.Context, db schooldirectory.Querier, ids []string, userID, fy, area string, start, end time.Time) (Pipeline, error) {
	var c Pipeline
	src := rules.AreaSources[area]
	switch src.Kind {
	case "activity":
		rows, err := db.Query(ctx, `SELECT status, COALESCE(TRIM(salesforce_activity_id), '') <> '' FROM activity
WHERE responsible_staff_id = ANY($1) AND fy = $2 AND activity_type = ANY($3) AND planned_date >= $4::date AND planned_date < $5::date
  AND deleted_at IS NULL AND NOT (delivery_type IS NOT NULL AND delivery_type = 'partner')`, ids, fy, src.Types, start, end)
		if err != nil {
			return c, fmt.Errorf("mytargets: the area's activities: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var status string
			var sf bool
			if err := rows.Scan(&status, &sf); err != nil {
				return c, fmt.Errorf("mytargets: the area's activities: %w", err)
			}
			switch {
			case contains(rules.ReturnedForCorrection, status):
				c.Returned++
			case contains(rules.ReturnedStatuses, status):
			case contains(rules.CompletedStatuses, status):
				switch {
				case !sf:
					c.PendingSF++
				case status == "awaiting_ia_verification":
					c.IAPending++
				default:
					c.Validated++
				}
			default:
				c.Scheduled++
			}
		}
		if err := rows.Err(); err != nil {
			return c, err
		}
	case "ssa_record":
		from := time.Date(start.Year(), start.Month(), start.Day(), 0, 0, 0, 0, local)
		to := time.Date(end.Year(), end.Month(), end.Day(), 0, 0, 0, 0, local)
		if err := db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE verification_status = 'confirmed'), count(*) FILTER (WHERE verification_status <> 'confirmed')
FROM ssa_record WHERE collected_by_user_id = ANY($1) AND deleted_at IS NULL
  AND date_of_ssa >= $2 AND date_of_ssa < $3`, ids, from, to).Scan(&c.Validated, &c.IAPending); err != nil {
			return c, fmt.Errorf("mytargets: the area's SSAs: %w", err)
		}
	default:
		if err := db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE status = 'approved'), count(*) FILTER (WHERE status = 'returned'),
  count(*) FILTER (WHERE status IN ('draft', 'submitted'))
FROM mscs_story WHERE user_id = $1 AND story_date >= $2::date AND story_date < $3::date`, userID, start, end).Scan(&c.Validated, &c.Returned, &c.Provisional); err != nil {
			return c, fmt.Errorf("mytargets: the area's stories: %w", err)
		}
	}
	return c, nil
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
