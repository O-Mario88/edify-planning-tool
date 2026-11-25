package planningmonitor

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Execution & Completion page's figures (country_execution.service).

const cexBase = "/country-planning-oversight/execution"

// cexPage are the page's words (exported with the rules).
type cexPage struct {
	KPILabels       map[string]string `json:"kpi_labels"`
	IssueOrder      [][2]string       `json:"issue_order"`
	ViewBy          [][2]string       `json:"view_by"`
	PeriodLabels    map[string]string `json:"period_labels"`
	ForecastOnTrack float64           `json:"forecast_on_track"`
	ForecastMinDue  int               `json:"forecast_min_due"`
	LeadManageable  []string          `json:"lead_manageable"`
	ExportRoles     []string          `json:"export_roles"`
}

// query is ExecFilters.query.
func (f cexFilters) query() string {
	q := "view=execution&fy=" + f.fy + "&period=" + f.period
	switch {
	case f.period == "quarter" && f.quarter != "":
		q += "&quarter=" + f.quarter
	case f.period == "month" && f.month != 0:
		q += "&month=" + strconv.Itoa(f.month)
	case f.period == "week" && f.week != "":
		q += "&week=" + f.week
	}
	for _, kv := range [][2]string{{"region", f.region}, {"program_lead", f.programLead}, {"cceo", f.cceo},
		{"channel", f.channel}, {"partner", f.partner}, {"activity_type", f.activType}} {
		if kv[1] != "" {
			q += "&" + kv[0] + "=" + kv[1]
		}
	}
	return q
}

func shareText(p *int) string {
	if p == nil {
		return "—"
	}
	return strconv.Itoa(*p) + "%"
}

// cexForecast is forecast: decision support only.
type cexForecast struct {
	status, label string
	share         *int
}

func cexForecastOf(t cexTally, w cpoWindow, today time.Time) cexForecast {
	page := rules.CountryExecution.Page
	due := t.n("due")
	if !today.Before(w.end) {
		return cexForecast{"closed", "Period closed", t.share(t.n("verified"), due)}
	}
	arrived := due - t.n("upcoming")
	if due < page.ForecastMinDue || arrived < 5 {
		return cexForecast{"insufficient", "Insufficient Data", nil}
	}
	started, executed, verified := float64(t.n("started")), float64(t.n("executed")), float64(t.n("verified"))
	startRate := 0.0
	if arrived > 0 {
		startRate = math.Min(1, started/float64(arrived))
	}
	submitRate, verifyRate := 0.0, 0.0
	if started > 0 {
		submitRate = executed / started
	}
	if executed > 0 {
		verifyRate = verified / executed
	}
	expected := verified + (executed-verified)*verifyRate + (started-executed)*submitRate*verifyRate +
		(float64(due)-started)*startRate*submitRate*verifyRate
	share := percentageFloat(expected, due)
	if share != nil && float64(*share) >= page.ForecastOnTrack*100 {
		return cexForecast{"on_track", "On Track", share}
	}
	return cexForecast{"at_risk", "At Risk", share}
}

// percentageFloat is metrics.percentage for a fractional part.
func percentageFloat(part float64, whole int) *int {
	if whole == 0 {
		return nil
	}
	v := int(math.RoundToEven(part / float64(whole) * 100))
	return &v
}

func (f cexForecast) text(w cpoWindow) string {
	switch f.status {
	case "insufficient":
		return "Too little planned work has reached its date to project this period."
	case "closed":
		return w.label() + " has ended: " + shareText(f.share) + " of its planned work was verified."
	}
	return "At the current conversion, " + shareText(f.share) + " of the work planned in " + w.label() + " is expected to be verified by its end."
}

// cexCard is one of kpis.
type cexCard struct{ label, value, note, href string }

func (s *cexSnapshot) kpis() []cexCard {
	c := s.tree.country
	q := s.filters.query()
	labels := rules.CountryExecution.Page.KPILabels
	card := func(metric, stage string, part int, note string) cexCard {
		return cexCard{labels[metric], cpoFmt(part), note, cexBase + "/records/" + stage + "?" + q}
	}
	of := func(name string) string { return shareText(c.share(c.n(name), c.n("due"))) + " of planned" }
	return []cexCard{
		card("cxo_activities_due", "due", c.n("due"), "Unique schools: "+cpoFmt(s.uniqueSchools)),
		card("cxo_started", "started", c.n("started"), of("started")),
		card("cxo_execution_completed", "executed", c.n("executed"), of("executed")),
		card("cxo_ia_verified", "verified", c.n("verified"), of("verified")),
		card("cxo_fully_closed", "closed", c.n("closed"), of("closed")),
		card("cxo_overdue", "overdue", c.n("overdue"), of("overdue")+" · "+cpoFmt(c.n("carried_forward"))+" carried forward"),
	}
}

// cexCells is row_cells.
type cexCells struct {
	due, inProgress, complete, overdue, carried, returned, reminders int
	onTime, remaining                                                *int
	forecast                                                         cexForecast
	atRisk, suggested                                                bool
	blocker                                                          string
}

func (s *cexSnapshot) cells(t cexTally, remaining *int, reminders int, suggest bool) cexCells {
	out := cexCells{due: t.n("due"), inProgress: t.n("in_progress"), complete: t.n("complete"), overdue: t.n("overdue"),
		carried: t.n("carried_forward"), returned: t.n("returned"), reminders: reminders, onTime: t.share(t.n("on_time"), t.n("due")),
		remaining: remaining, forecast: cexForecastOf(t, s.data.window, s.data.today)}
	out.atRisk = out.forecast.status == "at_risk"
	if suggest && reminders == 0 {
		for _, o := range rules.CountryExecution.Page.LeadManageable {
			if t.n("own_"+o) > 0 {
				out.suggested = true
			}
		}
	}
	best, bestN := [2]string{}, -1
	for _, o := range rules.CountryExecution.Stages.OwnerLabels {
		if n := t.n("own_" + o[0]); n > bestN {
			best, bestN = o, n
		}
	}
	if bestN > 0 {
		label := best[1]
		if best[0] == "pl" {
			label = "PL review"
		}
		out.blocker = "Waiting on " + label
	}
	return out
}

func (s *cexSnapshot) remainingOf(level, key string) *int {
	if v, ok := s.remaining[[2]string{level, key}]; ok {
		return &v
	}
	return nil
}

// cexIssue is one row of issues.
type cexIssue struct {
	label string
	count int
	share *int
}

func (s *cexSnapshot) issues() []cexIssue {
	counts := map[string]int{}
	for _, r := range s.records() {
		if r.cancelled || (r.overdue == "" && !r.financeOpen) {
			continue
		}
		switch {
		case r.financeOpen && r.owner == "finance":
			counts["finance"]++
		case r.financeOpen:
			counts["closure"]++
		case r.owner == "external":
			counts["external"]++
		case r.owner == "finance":
			counts["funds"]++
		case r.channel == "partner" && (r.overdue == "execution" || r.overdue == "evidence" || r.overdue == "correction"):
			counts["partner"]++
		case r.overdue == "execution":
			counts["execution_staff"]++
		default:
			counts[r.overdue]++
		}
	}
	total := 0
	for _, it := range rules.CountryExecution.Page.IssueOrder {
		total += counts[it[0]]
	}
	out := []cexIssue{}
	for _, it := range rules.CountryExecution.Page.IssueOrder {
		if n := counts[it[0]]; n > 0 {
			out = append(out, cexIssue{it[1], n, percentage(n, total)})
		}
	}
	return out
}

// cexEvent is one row of recent_activity.
type cexEvent struct {
	day          time.Time
	what, detail string
}

func (s *cexSnapshot) recent(ctx context.Context, db schooldirectory.Querier) ([]cexEvent, error) {
	since := s.data.today.AddDate(0, 0, -14)
	type key struct {
		day           time.Time
		what, channel string
	}
	counts, order := map[key]int{}, []key{}
	add := func(k key) {
		if _, ok := counts[k]; !ok {
			order = append(order, k)
		}
		counts[k]++
	}
	for _, r := range s.records() {
		if r.verifiedDay != nil && !r.verifiedDay.Before(since) {
			ch := "staff"
			if r.channel == "partner" {
				ch = "partner"
			}
			add(key{*r.verifiedDay, "Verified", ch})
		}
		if r.returned && r.lastAction != nil && !r.lastAction.Before(since) {
			add(key{*r.lastAction, "Returned for correction", ""})
		}
		if r.executed && !r.verified && r.lastAction != nil && !r.lastAction.Before(since) {
			add(key{*r.lastAction, "Evidence submitted", ""})
		}
	}
	out := []cexEvent{}
	for _, k := range order {
		n := counts[k]
		detail := fmt.Sprintf("%d %s", n, map[bool]string{true: "activity", false: "activities"}[n == 1])
		if k.what == "Verified" {
			detail += " verified"
			if k.channel == "partner" {
				detail += " (Partner work, by IA)"
			} else {
				detail += " (staff work)"
			}
		}
		out = append(out, cexEvent{k.day, k.what, detail})
	}
	rows, err := db.Query(ctx, `SELECT assigned_at, program_lead_name, remaining_value FROM planning_oversight_follow_up
		WHERE module = 'execution' AND (assigned_at AT TIME ZONE '`+cpoZone+`')::date >= $1::date ORDER BY assigned_at DESC LIMIT 8`, since)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the execution follow-ups sent: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var at time.Time
		var to string
		var n int
		if err := rows.Scan(&at, &to, &n); err != nil {
			return nil, err
		}
		out = append(out, cexEvent{localDay(at), "Follow-up sent", "To " + to + ": " + cpoFmt(n) + " open"})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].day.After(out[j].day) })
	if len(out) > 8 {
		out = out[:8]
	}
	return out, nil
}

// cexRequirement is requirement_row.
type cexRequirement struct {
	key, label                      string
	needsVisits, needsTrainings     bool
	cells                           [][2]any // figure, share (nil for none)
	trainingCells                   [][2]any
	visitsLeft, trainingsLeft       int
	visitsLeftShare, trainingsLeft2 *int
}

func cexRequirementRow(key, label string, v []int, needVisits, needTrainings bool) cexRequirement {
	t := cpoTally(v)
	sh := func(a, b int) *int {
		if s, ok := share(a, b); ok {
			return &s
		}
		return nil
	}
	slots, trainings := t.n("visit_slots"), t.n("training_slots")
	planned := t.n("staff") + t.n("partner_scheduled")
	verified := t.n("staff_verified") + t.n("partner_verified")
	visitsLeft := max(0, slots-verified)
	trainingPlanned := t.n("training_staff") + t.n("training_partner_assigned")
	trainingsLeft := max(0, trainings-t.n("training_verified"))
	r := cexRequirement{key: key, label: label, needsVisits: needVisits, needsTrainings: needTrainings}
	r.cells = [][2]any{
		{t.n("schools"), nil}, {slots, nil}, {planned, sh(planned, slots)}, {t.n("staff_expected"), sh(t.n("staff_expected"), slots)},
		{t.n("staff_verified"), sh(t.n("staff_verified"), t.n("staff_expected"))},
		{t.n("partner_expected"), sh(t.n("partner_expected"), slots)},
		{t.n("partner_verified"), sh(t.n("partner_verified"), t.n("partner_expected"))},
		{verified, sh(verified, slots)},
	}
	r.visitsLeft, r.visitsLeftShare = visitsLeft, sh(visitsLeft, slots)
	r.trainingCells = [][2]any{
		{trainings, nil}, {trainingPlanned, sh(trainingPlanned, trainings)},
		{t.n("training_partner_assigned"), sh(t.n("training_partner_assigned"), trainings)},
		{t.n("training_verified"), sh(t.n("training_verified"), trainings)},
	}
	r.trainingsLeft, r.trainingsLeft2 = trainingsLeft, sh(trainingsLeft, trainings)
	return r
}
