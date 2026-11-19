package financedesks

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The finance overviews: the Budget Overview (budget_overview_view over
// budget.services.fy_budget and monthly_budgets, pages/budget/index.html)
// and the Submitted Budgets history (country_budget_history_view over
// country_budget_service.list_submitted_budgets).

//go:embed overviews.json
var overviewsJSON []byte

// overviewDoors are what one role is given on the overviews.
type overviewDoors struct {
	Overview     bool `json:"overview"`
	History      bool `json:"history"`
	HistoryReads bool `json:"history_reads"`
}

var overviewRules = func() (r struct {
	Roles                    map[string]overviewDoors `json:"roles"`
	NonFundableStatuses      []string                 `json:"non_fundable_statuses"`
	RequestedAdvanceStatuses []string                 `json:"requested_advance_statuses"`
	ApprovedAdvanceStatuses  []string                 `json:"approved_advance_statuses"`
	DisbursedAdvanceStatuses []string                 `json:"disbursed_advance_statuses"`
	AccountedAdvanceStatuses []string                 `json:"accounted_advance_statuses"`
	AwaitingWeeklyStatuses   []string                 `json:"awaiting_weekly_statuses"`
	LockedBudgetStatuses     []string                 `json:"locked_budget_statuses"`
	BudgetStatusLabels       map[string]string        `json:"budget_status_labels"`
}) {
	if err := json.Unmarshal(overviewsJSON, &r); err != nil {
		panic(fmt.Sprintf("financedesks: reading overviews.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.RequestedAdvanceStatuses) == 0 {
		panic("financedesks: overviews.json lacks the doors or the advance states")
	}
	return r
}()

const (
	overviewPath = "/budgets/overview"
	historyPath  = "/country-budget/history"
)

// buildOverview answers an overview path; handled is false for any other.
func (s *Service) buildOverview(ctx context.Context, role, path string, query url.Values) (page *screensv1.GetPageResponse, handled, served bool, err error) {
	if path != overviewPath && path != historyPath {
		return nil, false, false, nil
	}
	doors, ok := overviewRules.Roles[role]
	if !ok {
		return nil, true, false, nil
	}
	fy := schooldirectory.OperationalFY(s.now())
	switch {
	case path == overviewPath && !doors.Overview, path == historyPath && !doors.History:
		return nil, true, true, errNotAvailable
	case path == overviewPath:
		page, err = s.budgetOverview(ctx, fy)
	case !doors.HistoryReads:
		// list_submitted_budgets refuses the reader after the page's door
		// let them in: the existing page errors, which Go does not draw.
		return nil, true, false, nil
	default:
		if query.Get("q") != "" || (query.Get("fy") != "" && query.Get("fy") != fy) {
			// A search or another year is the existing page's.
			return nil, true, false, nil
		}
		page, err = s.submittedBudgets(ctx, fy, query)
	}
	return page, true, true, err
}

// rollup is _rollup_from: a period's figures.
type rollup struct {
	planned, requested, approved, disbursed, accounted int64
	activities                                         int64
}

func (r rollup) cleared() int64 { return r.accounted }
func (r rollup) pending() int64 { return r.planned - r.accounted }

// rollupFrom is _rollup_base with _rollup_sums, grouped by the cost line's
// calendar month when byMonth: the line amounts summed over each line's
// advances (a LEFT JOIN, so a line with two advances counts twice, as the
// existing aggregate does), the fundable figures over live work only, the
// money moved over every line.
func (s *Service) rollupFrom(ctx context.Context, fy string, byMonth bool) (map[int]*rollup, error) {
	group, key := "", "0"
	if byMonth {
		group, key = " GROUP BY l.month", "COALESCE(l.month, -1)"
	}
	base := `FROM activity_schedule_cost_line l JOIN activity a ON a.id = l.activity_id
LEFT JOIN advance_request ar ON ar.budget_line_id = l.id
WHERE a.deleted_at IS NULL AND a.fy = $1 AND NOT (a.delivery_type = 'partner' AND a.planned_date IS NULL)`
	fundable := ` AND NOT (a.status IS NOT NULL AND a.status = ANY($2))`
	out := map[int]*rollup{}
	at := func(k int) *rollup {
		if out[k] == nil {
			out[k] = &rollup{}
		}
		return out[k]
	}
	rows, err := s.db.Query(ctx, `SELECT `+key+`, COALESCE(SUM(l.amount), 0),
  COALESCE(SUM(l.amount) FILTER (WHERE ar.status = ANY($3)), 0), COALESCE(SUM(l.amount) FILTER (WHERE ar.status = ANY($4)), 0),
  COUNT(DISTINCT l.activity_id) `+base+fundable+group,
		fy, overviewRules.NonFundableStatuses, overviewRules.RequestedAdvanceStatuses, overviewRules.ApprovedAdvanceStatuses)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the budget rollup: %w", err)
	}
	for rows.Next() {
		var k int
		var planned, requested, approved, n int64
		if err := rows.Scan(&k, &planned, &requested, &approved, &n); err != nil {
			rows.Close()
			return nil, err
		}
		r := at(k)
		r.planned, r.requested, r.approved, r.activities = planned, requested, approved, n
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT `+key+`, COALESCE(SUM(ar.disbursed_amount) FILTER (WHERE ar.status = ANY($2)), 0),
  COALESCE(SUM(ar.accounted_amount) FILTER (WHERE ar.status = ANY($3)), 0) `+base+group,
		fy, overviewRules.DisbursedAdvanceStatuses, overviewRules.AccountedAdvanceStatuses)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the money moved: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var k int
		var disbursed, accounted int64
		if err := rows.Scan(&k, &disbursed, &accounted); err != nil {
			return nil, err
		}
		r := at(k)
		r.disbursed, r.accounted = disbursed, accounted
	}
	return out, rows.Err()
}

// fyMonthNames are budget_overview_view's names for the months of the FY.
var fyMonthNames = []string{"October", "November", "December", "January", "February", "March", "April", "May", "June",
	"July", "August", "September"}

func (s *Service) budgetOverview(ctx context.Context, fy string) (*screensv1.GetPageResponse, error) {
	year, err := s.rollupFrom(ctx, fy, false)
	if err != nil {
		return nil, err
	}
	total := year[0]
	if total == nil {
		total = &rollup{}
	}
	metric := func(label string, v int64) *screensv1.PageMetric {
		return &screensv1.PageMetric{Label: label, Value: ugxInt(v)}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Performance overview",
		Metrics: []*screensv1.PageMetric{
			metric("Planned Budget", total.planned), metric("Requested Budget", total.requested),
			metric("Approved Budget", total.approved), metric("Disbursed Amount", total.disbursed),
			metric("Cleared Amount", total.cleared()), metric("Pending Amount", total.pending()),
			metric("Variance", total.pending()),
			// The template reads fy_data.activity_count, which fy_budget
			// does not carry (its key is activityCount): the figure is
			// always empty.
			{Label: "Scheduled Activities", Value: "—"},
		},
	}}}}
	var awaiting int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM weekly_fund_request WHERE status = ANY($1)`,
		overviewRules.AwaitingWeeklyStatuses).Scan(&awaiting); err != nil {
		return nil, fmt.Errorf("financedesks: counting the requests awaiting approval: %w", err)
	}
	if awaiting > 0 {
		words := strconv.Itoa(awaiting) + " Weekly Request"
		if awaiting != 1 {
			words += "s"
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{
				{Kind: &screensv1.PagePanelItem_Text{Text: "⏳"}},
				{Kind: &screensv1.PagePanelItem_Text{Text: words + " awaiting approval"}},
				{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
					{Text: "Review Requests →", Href: "/fund-requests"}}}}},
			}}}})
	}
	months, err := s.rollupFrom(ctx, fy, true)
	if err != nil {
		return nil, err
	}
	var rows []*screensv1.PageRow
	for m := 1; m <= 12; m++ {
		r := months[calendarMonthOfFY(m)]
		if r == nil || (r.planned <= 0 && r.requested <= 0) {
			continue
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(fyMonthNames[m-1]), cell(ugxInt(r.planned)), cell(ugxInt(r.requested)), cell(ugxInt(r.approved)),
			cell(ugxInt(r.disbursed)), cell(ugxInt(r.cleared())), cell(ugxInt(r.pending())), cell(ugxInt(r.pending())),
		}})
	}
	breakdown := &screensv1.PagePanel{Title: "Monthly Breakdown", Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{}}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: breakdown}})
	if len(rows) == 0 {
		breakdown.Items = append(breakdown.Items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "No budget data found for this FY"}})
	} else {
		blocks = append(blocks, table(columns([]string{"Month", "Planned", "Requested", "Approved", "Disbursed", "Cleared",
			"Pending", "Variance"}, "Planned", "Requested", "Approved", "Disbursed", "Cleared", "Pending", "Variance"),
			rows, "", "monthly_data_page", url.Values{})...)
	}
	return page(header("", "Budget Overview", "FY"+fy+" budget performance across all requests"), blocks...), nil
}

// calendarMonthOfFY is _calendar_month_of_fy: month 1 of the FY is October.
func calendarMonthOfFY(m int) int {
	c := 9 + m
	if c > 12 {
		c -= 12
	}
	return c
}

// calendarMonths are pl_approval_service.MONTHS (index = calendar month).
var calendarMonths = []string{"", "January", "February", "March", "April", "May", "June", "July", "August", "September",
	"October", "November", "December"}

func (s *Service) submittedBudgets(ctx context.Context, fy string, query url.Values) (*screensv1.GetPageResponse, error) {
	rows, err := s.db.Query(ctx, `SELECT b.id, b.month_key, b.fy, b.total_amount, b.submitted_at, COALESCE(b.submitted_by_user_id, ''),
  b.status, b.submission_version
FROM monthly_work_plan_budget b WHERE b.fy = $1 AND b.status = ANY($2) ORDER BY b.month_key DESC`,
		fy, overviewRules.LockedBudgetStatuses)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the submitted budgets: %w", err)
	}
	type budget struct {
		id, monthKey, fy, submitter, status string
		total                               int64
		submitted                           *time.Time
		version                             int
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (budget, error) {
		var b budget
		return b, row.Scan(&b.id, &b.monthKey, &b.fy, &b.total, &b.submitted, &b.submitter, &b.status, &b.version)
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the submitted budgets: %w", err)
	}
	ids := make([]string, 0, len(list))
	for _, b := range list {
		ids = append(ids, b.submitter)
	}
	names, err := s.submitterNames(ctx, ids)
	if err != nil {
		return nil, err
	}
	finance := "/country-budget/?fy=" + fy
	crumb := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
		Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{{Text: "Finance", Href: finance}}}}},
			{Kind: &screensv1.PagePanelItem_Text{Text: "Submitted Budgets · FY " + fy}},
		}}}}
	back := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
		Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{{Text: "Back to active month", Href: finance}}}}},
		}}}}
	h := header("Finance", "Submitted Budgets",
		"Months already sent to the RVP. Each row is an immutable snapshot of what was submitted — it does not change when later activities or costs change.")
	if len(list) == 0 {
		empty := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{
				{Kind: &screensv1.PagePanelItem_Text{Text: "No submitted budgets for FY " + fy}},
				{Kind: &screensv1.PagePanelItem_Text{Text: "Months you submit to the RVP will appear here as immutable records."}},
			}}}}
		return page(h, crumb, empty, back), nil
	}
	var out []*screensv1.PageRow
	for _, b := range list {
		month, _ := strconv.Atoi(b.monthKey[strings.LastIndex(b.monthKey, "-")+1:])
		label := strconv.Itoa(month)
		if month >= 1 && month <= 12 {
			label = calendarMonths[month]
		}
		by, ok := names[b.submitter]
		if !ok {
			by = b.submitter
		}
		if by == "" {
			by = "—"
		}
		when := ""
		if b.submitted != nil {
			when = djangoDateTime(local(*b.submitted))
		}
		status, ok := overviewRules.BudgetStatusLabels[b.status]
		if !ok {
			status = b.status
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(label + " " + b.monthKey), cell("FY " + b.fy), cell(budgetpage.UGXCompact(b.total)), cell(by), cell(when),
			badge(status), cell("v" + strconv.Itoa(b.version)),
			{Text: "View details", Href: "/country-budget/history/" + b.id},
		}})
	}
	blocks := []*screensv1.PageBlock{crumb}
	blocks = append(blocks, table(columns([]string{"Month", "Financial Year", "Submitted amount", "Submitted by",
		"Submitted date", "RVP status", "Version", "Details"}, "Submitted amount", "Details"), out, "", "rows_page", query)...)
	return page(h, append(blocks, back)...), nil
}

// djangoDateTime is date:"j M Y, g:i A": "17 Nov 2026, 7:54 AM".
func djangoDateTime(t time.Time) string { return t.Format("2 Jan 2006, 3:04 PM") }

// submitterNames is country_budget_service._submitter_names: an account's
// name, else a profile's account name, for the ids that have one.
func (s *Service) submitterNames(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT id, name FROM "user" WHERE id = ANY($1) AND COALESCE(name, '') <> ''`, ids)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the submitters: %w", err)
	}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return nil, err
		}
		out[id] = name
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var rest []string
	for _, id := range ids {
		if _, ok := out[id]; !ok && id != "" {
			rest = append(rest, id)
		}
	}
	rows, err = s.db.Query(ctx, `SELECT sp.id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) AND sp.deleted_at IS NULL AND COALESCE(u.name, '') <> ''`, rest)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the submitters: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}
