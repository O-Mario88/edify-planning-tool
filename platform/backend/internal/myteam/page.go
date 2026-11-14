package myteam

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"slices"
	"sort"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// Service answers My Team from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db, its moment read from now.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// item is one thing waiting on the lead (_needs_action's add).
type item struct {
	title, person, detail, due, url, severity string
}

// row is one officer's line of the roster.
type row struct {
	staffID, name, profile, district string
	delivery, target, ssa, waiting   string
	review, coaching, leave, risk    string
	policies                         int
	ssaAssessed, ssaPortfolio        int
	waitingTotal                     int
	fyStatus, riskBand               string
	awayNow                          bool
}

// Build answers /my-team; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	options := schooldirectory.FYOptions(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if !slices.Contains(options, fy) {
		fy = schooldirectory.OperationalFY(now)
	}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	rows, items, err := s.roster(ctx, p, fy, today, now)
	if errors.Is(err, targets.ErrHandOn) {
		// The existing page rebuilds a stale ledger on this read.
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetPageResponse{Header: header(), Blocks: blocks(rows, items, fy, options, query), WebPath: Path}, true, nil
}

func header() *screensv1.PageHeader {
	link := func(key, label, href string) *screensv1.PageAction {
		return &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href}
	}
	return &screensv1.PageHeader{
		Eyebrow: "Team leadership", Title: "My Team",
		Description: "The officers you line-manage: their delivery, targets, reviews, coaching and leave, and what is waiting on you.",
		Actions:     []*screensv1.PageAction{link("coaching", "Coaching", "/team/coaching"), link("team_leave", "Team Leave", "/leave/approvals")},
	}
}

func (s *Service) roster(ctx context.Context, p auth.Principal, fy string, today, now time.Time) ([]row, []item, error) {
	if p.StaffProfileID == "" {
		return nil, nil, nil
	}
	members, err := teamMembers(ctx, s.db, p.StaffProfileID, now)
	if err != nil || len(members) == 0 {
		return nil, nil, err
	}
	port, err := readPortfolio(ctx, s.db, members)
	if err != nil {
		return nil, nil, err
	}
	delivery, completions, err := readDelivery(ctx, s.db, members, port, fy)
	if err != nil {
		return nil, nil, err
	}
	ssa, err := readSSA(ctx, s.db, port, fy)
	if err != nil {
		return nil, nil, err
	}
	lv, err := readLeave(ctx, s.db, members, today)
	if err != nil {
		return nil, nil, err
	}
	bands, err := readBands(ctx, s.db, members, fy, today, lv)
	if err != nil {
		return nil, nil, err
	}
	reviews, err := readReviews(ctx, s.db, members, fy)
	if err != nil {
		return nil, nil, err
	}
	development, err := readDevelopment(ctx, s.db, members)
	if err != nil {
		return nil, nil, err
	}
	escalated, err := readEscalations(ctx, s.db, p, members)
	if err != nil {
		return nil, nil, err
	}
	users := ids(members, func(m member) string { return m.userID })
	extra, err := countBy(ctx, s.db, "the extra work", `
SELECT assignee_id, count(*) FROM hr_extra_assignment WHERE assignee_id = ANY($1) AND reviewer_id = $2 AND status = 'submitted'
GROUP BY 1`, users, p.UserID)
	if err != nil {
		return nil, nil, err
	}
	policies, err := countBy(ctx, s.db, "the overdue policies", `
SELECT a.user_id, count(*) FROM document_acknowledgement a JOIN document_asset d ON d.id = a.document_id
WHERE a.user_id = ANY($1) AND a.state = $2 AND a.due_date < $3::date AND d.status = ANY($4) GROUP BY 1`,
		users, rules.PendingAck, today, rules.ReadableDocuments)
	if err != nil {
		return nil, nil, err
	}
	coached, err := readCoaching(ctx, s.db, p, members)
	if err != nil {
		return nil, nil, err
	}

	rows := []row{}
	for _, m := range members {
		waiting := map[string]int{
			"completions": completions[m.staffID], "development": len(development[m.staffID]),
			"leave": lv.pending[m.staffID], "escalations": len(escalated[m.userID]), "extra_work": extra[m.userID],
		}
		total := 0
		for _, n := range waiting {
			total += n
		}
		d := delivery[m.staffID]
		deliveryText := "Nothing planned"
		if d[0] > 0 {
			deliveryText = fmt.Sprintf("%d of %d", d[1], d[0])
		}
		schools := port.byStaff[m.staffID]
		assessed := 0
		for school := range schools {
			if ssa[school] {
				assessed++
			}
		}
		ssaText := "No schools"
		if len(schools) > 0 {
			ssaText = fmt.Sprintf("%d of %d", assessed, len(schools))
		}
		b, ok := bands[m.staffID]
		if !ok {
			b = band{fyStatus: "Not Assigned", fyText: "No targets agreed"}
		}
		risk := "—"
		if words, ok := rules.RiskWords[b.monthStatus]; ok && len(words) == 2 {
			risk = words[0]
		}
		name := m.name
		if name == "" {
			name = m.title
		}
		if name == "" {
			name = "CCEO"
		}
		district := port.districtOf[m.staffID]
		if district == "" {
			district = "—"
		}
		leaveText, away := leaveCell(lv, m.staffID)
		rows = append(rows, row{
			staffID: m.staffID, name: name, profile: "/staff/" + m.userID + "?from=/my-team", district: district,
			delivery: deliveryText, target: b.fyText, ssa: ssaText, waiting: waitingText(waiting),
			review: reviewCell(reviews, m.staffID, fy), coaching: coachingCell(coached, m.staffID), leave: leaveText,
			risk: risk, policies: policies[m.userID], ssaAssessed: assessed, ssaPortfolio: len(schools),
			waitingTotal: total, fyStatus: b.fyStatus, riskBand: b.monthStatus, awayNow: away,
		})
	}
	items, err := s.needsAction(ctx, members, today, now, fy, reviews, completions, development, escalated, extra)
	if err != nil {
		return nil, nil, err
	}
	return rows, items, nil
}

// waitingText is _waiting_text.
func waitingText(w map[string]int) string {
	parts := []string{}
	if n := w["completions"]; n > 0 {
		parts = append(parts, plural(n, "completion"))
	}
	if n := w["development"]; n > 0 {
		parts = append(parts, plural(n, "PD request"))
	}
	if n := w["leave"]; n > 0 {
		parts = append(parts, plural(n, "leave request"))
	}
	if n := w["escalations"]; n > 0 {
		parts = append(parts, plural(n, "escalation"))
	}
	if n := w["extra_work"]; n > 0 {
		parts = append(parts, fmt.Sprintf("%d extra work", n))
	}
	if len(parts) == 0 {
		return "Nothing"
	}
	return strings.Join(parts, " · ")
}

// reviewCell is _review_cell's words.
func reviewCell(reviews map[string]review, staffID, fy string) string {
	r, ok := reviews[staffID]
	if !ok {
		return "No FY" + fy + " agreement"
	}
	label := labelOf(rules.ReviewStages, r.stage)
	if slices.Contains(rules.ManagerStages, r.stage) {
		return label + " · waiting on you"
	}
	return label
}

// coachingCell is _coaching_cell's words.
func coachingCell(all map[string]coaching, staffID string) string {
	c, ok := all[staffID]
	if !ok {
		return "Not coached yet"
	}
	parts := []string{}
	if c.heldOn != nil {
		parts = append(parts, dayLabel(*c.heldOn))
	}
	if label := labelOf(rules.CoachingKinds, c.kind); label != "" {
		parts = append(parts, label)
	}
	text := strings.Join(parts, " · ")
	switch {
	case c.followUp:
		return text + " · follow-up open"
	case c.shared && !c.acknowledged:
		return text + " · not acknowledged"
	case text == "":
		return "Coached"
	}
	return text
}

// leaveCell is _leave_cell.
func leaveCell(l leave, staffID string) (string, bool) {
	if until, ok := l.awayNow[staffID]; ok {
		return "On leave until " + dayLabel(until), true
	}
	if from, ok := l.nextAway[staffID]; ok {
		return "Away from " + dayLabel(from), false
	}
	return "—", false
}

var severityOrder = map[string]int{"critical": 0, "high": 1, "medium": 2}

// needsAction is _needs_action: HR's late leave decisions, overdue reviews
// and uncovered leave; missing agreements; completions, development
// requests, escalations and extra work waiting on the lead.
func (s *Service) needsAction(ctx context.Context, members []member, today, now time.Time, fy string, reviews map[string]review,
	completions map[string]int, development map[string][]pdRequest, escalated map[string][]escalation, extra map[string]int) ([]item, error) {
	nameOf, nameOfUser := map[string]string{}, map[string]string{}
	for _, m := range members {
		nameOf[m.staffID], nameOfUser[m.userID] = m.name, m.name
	}
	items, err := s.hrExceptions(ctx, members, today)
	if err != nil {
		return nil, err
	}
	for _, m := range members {
		if _, ok := reviews[m.staffID]; !ok && m.onboarding == "active" {
			items = append(items, item{title: "No performance agreement", person: nameOf[m.staffID],
				detail: "No FY" + fy + " agreement yet, so none of their delivery counts towards it.",
				url:    "/performance-conversation?staff=" + m.staffID, severity: "high"})
		}
	}
	for _, m := range members { // completions, by officer as the roster lists them
		if n := completions[m.staffID]; n > 0 {
			items = append(items, item{title: "Completions waiting for your review", person: nameOf[m.staffID],
				detail: plural(n, "completed activity") + " submitted for your confirmation.", url: "/pl/review-queue", severity: "high"})
		}
	}
	for _, m := range members {
		for _, r := range development[m.staffID] {
			detail := r.course
			if detail == "" {
				detail = "Professional development request"
			}
			items = append(items, item{title: "Development request waiting for you", person: nameOf[m.staffID], detail: detail,
				url: "/my-professional-development/request?id=" + r.id, severity: "medium"})
		}
	}
	for _, m := range members {
		for _, e := range escalated[m.userID] {
			who := nameOfUser[m.userID]
			if who == "" {
				who = e.raisedByName
			}
			if who == "" {
				who = "your officer"
			}
			severity := "medium"
			if e.severity != "normal" {
				severity = "high"
			}
			items = append(items, item{title: "Decide escalation from " + who, person: nameOfUser[m.userID], detail: e.subject,
				url: "/escalations", severity: severity, due: fmt.Sprintf("open %dd", int(now.Sub(e.createdAt).Hours()/24))})
		}
	}
	for _, m := range members {
		if n := extra[m.userID]; n > 0 {
			items = append(items, item{title: "Extra work to verify", person: nameOfUser[m.userID],
				detail: plural(n, "submitted assignment") + " waiting for your verification.", url: "/extra-work", severity: "medium"})
		}
	}
	sort.SliceStable(items, func(i, j int) bool {
		a, b := order(items[i].severity), order(items[j].severity)
		if a != b {
			return a < b
		}
		return items[i].person < items[j].person
	})
	return items, nil
}

func order(severity string) int {
	if n, ok := severityOrder[severity]; ok {
		return n
	}
	return 3
}

// hrExceptions is hr_exceptions' _leave_decisions_overdue, _reviews_overdue
// and _leave_without_coverage for the team, in that order.
func (s *Service) hrExceptions(ctx context.Context, members []member, today time.Time) ([]item, error) {
	staff := ids(members, func(m member) string { return m.staffID })
	out := []item{}
	cutoff := today.AddDate(0, 0, -rules.LeaveDecisionDays)
	rows, err := s.db.Query(ctx, `
SELECT l.id, (l.created_at AT TIME ZONE 'UTC')::date, COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), 'Staff member')
FROM leave l JOIN staff_profile sp ON sp.id = l.staff_id LEFT JOIN "user" u ON u.id = sp.user_id
WHERE l.status = 'pending' AND l.staff_id = ANY($1) AND (l.created_at AT TIME ZONE 'Africa/Nairobi')::date <= $2::date
ORDER BY l.created_at LIMIT 50`, staff, cutoff)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the leave decisions: %w", err)
	}
	for rows.Next() {
		var id, name string
		var created time.Time
		if err := rows.Scan(&id, &created, &name); err != nil {
			rows.Close()
			return nil, fmt.Errorf("myteam: reading a leave decision: %w", err)
		}
		waited := int(today.Sub(created).Hours() / 24)
		severity := "medium"
		if waited >= rules.LeaveDecisionDays*2 {
			severity = "high"
		}
		out = append(out, item{title: "Leave request has no decision", person: name,
			detail: "Submitted " + daysAgo(waited) + " ago and still pending with the manager.",
			url:    "/leave/approvals?id=" + id, severity: severity, due: "waiting " + daysAgo(waited)})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("myteam: reading the leave decisions: %w", err)
	}
	rrows, err := s.db.Query(ctx, `
SELECT r.staff_id, r.due_date, COALESCE(NULLIF(r.period, ''), NULLIF(r.fy, ''), ''), COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), 'Staff member')
FROM hr_performance_review r JOIN staff_profile sp ON sp.id = r.staff_id LEFT JOIN "user" u ON u.id = sp.user_id
WHERE r.staff_id = ANY($1) AND r.due_date IS NOT NULL AND r.due_date < $2::date
  AND (r.stage IS NULL OR r.stage <> ALL($3)) AND (r.status IS NULL OR r.status <> ALL($4))
ORDER BY r.due_date LIMIT 50`, staff, today.AddDate(0, 0, -rules.ReviewOverdueDays), rules.ClosedStages, rules.ClosedReviewStatuses)
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the overdue reviews: %w", err)
	}
	for rrows.Next() {
		var staffID, period, name string
		var due time.Time
		if err := rrows.Scan(&staffID, &due, &period, &name); err != nil {
			rrows.Close()
			return nil, fmt.Errorf("myteam: reading an overdue review: %w", err)
		}
		late := int(today.Sub(due).Hours() / 24)
		severity := "medium"
		if late > 14 {
			severity = "high"
		}
		out = append(out, item{title: "Performance review overdue", person: name,
			detail: strings.TrimSpace(fmt.Sprintf("%s review is %d days late.", period, late)),
			url:    "/performance-conversation?staff=" + staffID, severity: severity, due: dueLabel(due, today)})
	}
	rrows.Close()
	if err := rrows.Err(); err != nil {
		return nil, fmt.Errorf("myteam: reading the overdue reviews: %w", err)
	}
	crows, err := s.db.Query(ctx, `
SELECT l.start_date, l.end_date, COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), 'Staff member')
FROM leave l JOIN staff_profile sp ON sp.id = l.staff_id LEFT JOIN "user" u ON u.id = sp.user_id
WHERE l.status = 'approved' AND l.staff_id = ANY($1) AND l.end_date >= $2 AND l.start_date <= $3 AND l.covering_staff_id IS NULL
  AND l.id NOT IN (SELECT leave_request_id FROM temporary_coverage_assignment WHERE status = 'active' AND leave_request_id IS NOT NULL)
ORDER BY l.start_date LIMIT 50`, staff, today.Format(time.DateOnly), today.AddDate(0, 0, 14).Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("myteam: reading the uncovered leave: %w", err)
	}
	defer crows.Close()
	for crows.Next() {
		var start, end, name string
		if err := crows.Scan(&start, &end, &name); err != nil {
			return nil, fmt.Errorf("myteam: reading an uncovered leave: %w", err)
		}
		out = append(out, item{title: "Approved leave with nobody covering", person: name,
			detail: start + " to " + end + ". Their approvals and To-Dos stay with them while they are away.",
			url:    "/leave/coverage", severity: "high", due: "starts " + start})
	}
	return out, crows.Err()
}

func daysAgo(days int) string {
	switch {
	case days <= 0:
		return "today"
	case days == 1:
		return "1 day"
	}
	return fmt.Sprintf("%d days", days)
}

func dueLabel(target, today time.Time) string {
	delta := int(target.Sub(today).Hours() / 24)
	switch {
	case delta < 0:
		return fmt.Sprintf("%d days overdue", -delta)
	case delta == 0:
		return "due today"
	case delta == 1:
		return "due tomorrow"
	}
	return fmt.Sprintf("in %d days", delta)
}

func dash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

// tile is one figure as components/context_metrics.html draws it.
func tile(label, value, helper, tone string) *screensv1.PageMetric {
	m := &screensv1.PageMetric{Label: labelOf(rules.TileLabels, label), Value: value}
	brief := schoolprofile.BriefHelper(helper)
	m.Helper = brief
	if brief != helper {
		m.Note = helper
	}
	if brief != "" {
		m.Tone = tone
	}
	return m
}

func blocks(rows []row, items []item, fy string, options []string, query url.Values) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{}
	if len(options) > 1 {
		f := &screensv1.PageFilter{Name: "fy", Label: "Financial year", Value: fy}
		for _, o := range options {
			f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o, Label: "FY " + o})
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{f}}}})
	}
	team, onTrack, atRisk, waiting, assessed, portfolio := len(rows), 0, 0, 0, 0, 0
	for _, r := range rows {
		if slices.Contains([]string{"On Track", "Complete", "Exceeded"}, r.fyStatus) {
			onTrack++
		}
		if slices.Contains(rules.HighRiskBands, r.riskBand) {
			atRisk++
		}
		waiting += r.waitingTotal
		assessed += r.ssaAssessed
		portfolio += r.ssaPortfolio
	}
	pace, paceTone := "—", "info"
	if team > 0 {
		pace = fmt.Sprintf("%d of %d", onTrack, team)
		if onTrack == team {
			paceTone = "success"
		}
	}
	coverage, coverageHelp := "—", "no portfolio schools"
	if portfolio > 0 {
		coverage = fmt.Sprintf("%d%%", int(math.RoundToEven(float64(assessed)/float64(portfolio)*100)))
		coverageHelp = fmt.Sprintf("%d of %d schools confirmed", assessed, portfolio)
	}
	toneIf := func(n int, bad string) string {
		if n > 0 {
			return bad
		}
		return "success"
	}
	out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Your team at a glance", Metrics: []*screensv1.PageMetric{
		tile("Officers on My Team", fmt.Sprint(team), "CCEOs you line-manage", "info"),
		tile("Officers On Pace for FY Targets", pace, "on track, complete or ahead for the year", paceTone),
		tile("Officers at Target Risk This Month", fmt.Sprint(atRisk), "high risk or critical against this month's pace", toneIf(atRisk, "danger")),
		tile("Team Handoffs Waiting on You", fmt.Sprint(waiting), "completions, leave, development, escalations and extra work", toneIf(waiting, "warning")),
		tile("Team Exceptions Needing Your Action", fmt.Sprint(len(items)), "late decisions, missing agreements and uncovered leave", toneIf(len(items), "danger")),
		tile("Team Portfolio SSA Coverage This FY", coverage, coverageHelp, "info"),
	}}}})

	open := func(label, href string) *screensv1.PageCell {
		return &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: label, Primary: true, Enabled: true, Href: href}}}
	}
	text := func(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: t} }

	actionRows := []*screensv1.PageRow{}
	for _, it := range items {
		actionRows = append(actionRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			text(it.title), text(dash(it.person)), text(dash(it.detail)), text(dash(it.due)), open("Open", it.url)}})
	}
	out = append(out, card("Needs your action", []string{"What", "Officer", "Detail", "When", ""}, actionRows,
		"Nothing is waiting on you.", "Late leave decisions, overdue reviews, missing agreements, uncovered leave, completions, "+
			"development requests, escalations and extra work to verify appear here.", "action_page", query)...)

	rosterRows := []*screensv1.PageRow{}
	for _, r := range rows {
		rosterRows = append(rosterRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: r.name, Href: r.profile}, text(r.district), text(r.delivery), text(r.target), text(r.ssa), text(r.waiting),
			text(r.review), text(r.coaching), text(r.leave), text(fmt.Sprint(r.policies)), text(r.risk), open("Profile", r.profile)}})
	}
	out = append(out, card("Team roster", []string{"CCEO", "District", "Delivery verified", "Targets (FY)", "SSA coverage",
		"Waiting on you", "Review", "Last coaching", "Leave", "Policies overdue", "Risk", ""}, rosterRows,
		"No officers report to you yet.", "Officers appear here when HR records you as their supervisor, or while you cover an "+
			"absent Programme Lead.", "team_page", query)...)
	out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: footnote}}}}}})
	return out
}

const footnote = "Delivery verified is the year's activities Impact Assessment verified, out of those planned for the officer or in their schools. " +
	"Targets and risk use Team Targets' pace bands: the year so far, and this month. SSA coverage is portfolio schools with a confirmed self-assessment this year."

// card is an rpl-card: its title as a panel, then the page of its table.
func card(title string, columns []string, rows []*screensv1.PageRow, empty, hint, param string, query url.Values) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title}}}}
	t := &screensv1.PageTable{}
	if len(rows) == 0 {
		// components/empty_state.html in the table's one cell: the message
		// and its hint, read as one line, the message kept as the table's.
		t.EmptyMessage = empty
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: empty + " " + hint}}}}
		return append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	}
	for _, c := range columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	number, _ := closedschools.PageOf(query.Get(param), len(rows), rules.PageSize)
	t.Rows = rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(rows))]
	return append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
}
