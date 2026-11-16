package disbursements

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	_ "time/tzdata" // the page's day is Nairobi's wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// PagePath is the dashboard's path.
const PagePath = "/disbursements"

// ownQuery is what the view reads (_disb_filters).
var ownQuery = []string{"fy", "month", "status", "q", "item"}

var (
	plainYear  = regexp.MustCompile(`^\d{4}$`)
	plainMonth = regexp.MustCompile(`^\d{1,2}$`)
)

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("disbursements: " + err.Error())
	}
	return z
}()

// Service builds the dashboard.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService returns the dashboard's builder.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

type ask struct {
	fy, status, search, selected string
	month                        int
	monthAsked                   bool
}

// Build answers /disbursements.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	doors, known := rules.Doors[p.ActiveRole]
	if !known || !doors.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return nil, false, nil
		}
	}
	now := s.now()
	today := now.In(zone)
	a := ask{
		fy: query.Get("fy"), status: query.Get("status"),
		search:   strings.ToLower(strings.TrimSpace(query.Get("q"))),
		selected: query.Get("item"), month: int(today.Month()),
	}
	if a.fy == "" {
		a.fy = schooldirectory.OperationalFY(now)
	} else if !plainYear.MatchString(a.fy) {
		return nil, false, nil
	}
	if m := query.Get("month"); m != "" {
		n, err := strconv.Atoi(m)
		if !plainMonth.MatchString(m) || err != nil || n < 1 || n > 12 {
			return nil, false, nil
		}
		a.month, a.monthAsked = n, true
	}

	q := &queue{db: s.db, names: map[string]string{}}
	all, err := q.read(ctx, a.fy, a.month)
	if err != nil {
		return nil, true, err
	}
	if len(all) == 0 && !a.monthAsked {
		m, err := busiestMonth(ctx, s.db, a.fy)
		if err != nil {
			return nil, true, err
		}
		if m != 0 && m != a.month {
			if m < 1 || m > 12 {
				return nil, false, nil
			}
			a.month = m
			if all, err = q.read(ctx, a.fy, a.month); err != nil {
				return nil, true, err
			}
		}
	}
	visible := []item{}
	for _, it := range all {
		if a.status != "" && it.status != a.status {
			continue
		}
		if a.search != "" && !strings.Contains(strings.ToLower(it.name), a.search) &&
			!strings.Contains(strings.ToLower(it.kindLabel), a.search) &&
			!strings.Contains(strings.ToLower(it.subtitle), a.search) {
			continue
		}
		visible = append(visible, it)
	}

	f, err := s.figures(ctx, a, all, today)
	if err != nil {
		return nil, true, err
	}
	blocks := []*screensv1.PageBlock{filterBlock(a, now), f.strip()}
	if len(visible) == 0 {
		blocks = append(blocks, panel("", text("No fund items match your filters"),
			text("Change the month or status, or clear the search.")))
	} else {
		sel := visible[0]
		for _, it := range visible {
			if it.key == a.selected {
				sel = it
				break
			}
		}
		tabs := &screensv1.PageLinks{}
		for _, it := range visible {
			tabs.Links = append(tabs.Links, &screensv1.PageLink{Text: it.name,
				Href: fmt.Sprintf("/disbursements/detail?item=%s&fy=%s&month=%d", it.key, a.fy, a.month)})
		}
		detail, ok, err := detailTable(ctx, s.db, sel)
		if err != nil {
			return nil, true, err
		}
		if !ok {
			return nil, false, nil
		}
		blocks = append(blocks,
			panel("", text(fmt.Sprintf("Consolidated Fund Queue %d", len(visible)))),
			panel("", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: tabs}}),
			detail)
	}
	m, err := mixOf(ctx, s.db, all)
	if err != nil {
		return nil, true, err
	}
	recent, err := s.recent(ctx, q)
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, f.side(a, all))
	blocks = append(blocks, mixBlocks(a, m)...)
	blocks = append(blocks, recent)

	h := &screensv1.PageHeader{
		Title:       "Fund Disbursement Dashboard",
		Description: "Monitor approved funds, disbursements, balances and reconciliation across every fund type.",
	}
	if doors.Export {
		h.Actions = []*screensv1.PageAction{{Key: "export", Label: "Export", Enabled: true, Download: true,
			Href: fmt.Sprintf("/disbursements?export=csv&fy=%s&month=%d", a.fy, a.month)}}
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, WebPath: PagePath}, true, nil
}

func filterBlock(a ask, now time.Time) *screensv1.PageBlock {
	years := schooldirectory.FYOptions(now)
	if !slices.Contains(years, a.fy) {
		years = append(years, a.fy)
	}
	sort.Sort(sort.Reverse(sort.StringSlice(years)))
	fy := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: a.fy, Caption: "Financial Year"}
	for _, y := range years {
		fy.Options = append(fy.Options, &screensv1.PageFilterOption{Value: y, Label: y})
	}
	month := &screensv1.PageFilter{Name: "month", Label: "Month", Value: strconv.Itoa(a.month)}
	for i := 1; i <= 12; i++ {
		month.Options = append(month.Options, &screensv1.PageFilterOption{Value: strconv.Itoa(i), Label: rules.Months[i]})
	}
	status := &screensv1.PageFilter{Name: "status", Label: "Status", Caption: "Fund Status",
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All Statuses"}}}
	for _, o := range rules.StatusOptions {
		status.Options = append(status.Options, &screensv1.PageFilterOption{Value: o, Label: o})
		if o == a.status {
			status.Value = o
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{fy, month, status}}}}
}

// figures is what the strip and the month's panel read.
type figures struct {
	total, pendingDisb, awaiting, heldAmt, disbToday int64
	items, pendingCount, awaitingCount               int
	allocation, disbursedMonth                       int64
}

func (s *Service) figures(ctx context.Context, a ask, all []item, today time.Time) (figures, error) {
	f := figures{items: len(all)}
	for _, it := range all {
		f.total += it.amount
		switch it.status {
		case pendingDisbursement:
			f.pendingDisb += it.amount
			f.pendingCount++
		case pendingApproval:
			f.awaiting += it.amount
			f.awaitingCount++
		case held:
			f.heldAmt += it.amount
		}
	}
	day := today.Format(time.DateOnly)
	err := s.db.QueryRow(ctx, `
		SELECT COALESCE((SELECT SUM(COALESCE(NULLIF(disbursed_amount, 0), total_amount)) FROM fund_request
		                 WHERE period = 'monthly' AND (disbursed_at AT TIME ZONE 'Africa/Nairobi')::date = $1::date), 0)
		     + COALESCE((SELECT SUM(COALESCE(NULLIF(disbursed_amount, 0), total_amount)) FROM weekly_fund_request
		                 WHERE (disbursed_at AT TIME ZONE 'Africa/Nairobi')::date = $1::date), 0),
		       COALESCE((SELECT SUM(disbursed_amount) FROM advance_request
		                 WHERE fy = $2 AND month = $3 AND status = ANY($4)), 0),
		       COALESCE((SELECT SUM(l.amount) FROM activity_schedule_cost_line l JOIN activity a ON a.id = l.activity_id
		                 WHERE a.fy = $2 AND l.month = $3 AND a.deleted_at IS NULL
		                   AND (a.status IS NULL OR NOT (a.status = ANY($5)))), 0)`,
		day, a.fy, a.month, rules.MoneyMovedAdvanceStatuses, rules.NonFundableStatuses).
		Scan(&f.disbToday, &f.disbursedMonth, &f.allocation)
	if err != nil {
		return f, fmt.Errorf("disbursements: reading the month's money: %w", err)
	}
	return f, nil
}

func plural(n int, one, many string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, one)
	}
	return fmt.Sprintf("%d %s", n, many)
}

func (f figures) strip() *screensv1.PageBlock {
	ugx := budgetpage.UGXCompact
	values := []string{ugx(f.total), ugx(f.pendingDisb), ugx(f.disbToday), ugx(f.awaiting)}
	helpers := []string{plural(f.items, "item", "items"), plural(f.pendingCount, "request", "requests"),
		"Released today", fmt.Sprintf("%d in approval chain", f.awaitingCount)}
	strip := &screensv1.PageStrip{Title: "Disbursement context"}
	for i, label := range rules.MetricLabels {
		m := &screensv1.PageMetric{Label: label, Value: values[i], Helper: helpers[i]}
		if brief := schoolprofile.BriefHelper(helpers[i]); brief != helpers[i] {
			m.Helper, m.Note = brief, helpers[i]
		}
		strip.Metrics = append(strip.Metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

// pyRound is Python's round() to a whole number: a half to the even one.
func pyRound(x float64) int64 { return int64(math.RoundToEven(x)) }

// side is the month's panel as the feed reads it: the allocation and its
// use, then the disbursement rate (the month's rows are not read).
func (f figures) side(a ask, all []item) *screensv1.PageBlock {
	ugx := budgetpage.UGXCompact
	committed := f.pendingDisb + f.heldAmt
	available := max(0, f.allocation-f.disbursedMonth-committed)
	var pct int64
	if f.allocation != 0 {
		pct = pyRound(float64(f.disbursedMonth) / float64(f.allocation) * 100)
	}
	state := "On Track"
	if pct > 100 {
		state = "Over plan"
	}
	items := []*screensv1.PagePanelItem{
		heading(rules.Months[a.month] + " Allocation & Utilization"),
		text(state),
		{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
			{Label: "Total Allocation", Value: ugx(f.allocation)}}}}},
		text(fmt.Sprintf("Utilized · committed %s · available %s", ugx(committed), ugx(available))),
		text(fmt.Sprintf("%s (%d%%)", ugx(f.disbursedMonth), min(pct, 100))),
		links(&screensv1.PageLink{Text: "View budget overview", Href: "/budgets/overview"}),
		heading("Disbursement Rate This Month"),
	}
	counts := map[string]int64{}
	for _, it := range all {
		counts[it.status]++
	}
	approved := counts[disbursed] + counts[awaitingRecon] + counts[closed]
	back := counts[returned]
	waiting := counts[pendingDisbursement] + counts[held] + counts[pendingApproval]
	total := approved + back + waiting
	if total == 0 {
		items = append(items, text("No fund items this month yet."))
	} else {
		pcts := []struct {
			label string
			value int64
		}{{"Approved", approved}, {"Returned", back}, {"Pending", waiting}}
		rows := &screensv1.PageDataRows{}
		legend := []*screensv1.PageLink{}
		for _, p := range pcts {
			v := fmt.Sprintf("%d%%", budgetpage.Percentage(p.value, total))
			rows.Rows = append(rows.Rows, &screensv1.PageDataRow{Label: p.label, Value: v})
			legend = append(legend, &screensv1.PageLink{Text: p.label + v})
		}
		items = append(items, text(fmt.Sprintf("%d%% · Disbursed", budgetpage.Percentage(approved, total))),
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: rows}}, links(legend...))
	}
	return panel("All Fund Types This Month", items...)
}

// mixBlocks is fund_workspace.budget_mix drawn: a share for each of the five
// largest labels (the rest folded into Other), each share's figure when it
// is 7% or more, then the legend; the empty state when nothing is costed.
func mixBlocks(a ask, m *mix) []*screensv1.PageBlock {
	title := fmt.Sprintf("Disbursement Mix (%s)", rules.Months[a.month])
	ordered := []labelled{}
	for _, l := range m.labels {
		if m.totals[l] != 0 {
			ordered = append(ordered, labelled{label: l, total: m.totals[l]})
		}
	}
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].total > ordered[j].total })
	if len(ordered) > 5 {
		var rest int64
		for _, l := range ordered[5:] {
			rest += l.total
		}
		ordered = append(ordered[:5:5], labelled{label: "Other", total: rest})
	}
	if len(ordered) == 0 {
		// The card's empty state, read as an empty table under the card's
		// title (its two lines run together).
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: title, EmptyMessage: "No costed activities this monthThe budget mix fills in as plans are costed."}}}}
	}
	var total int64
	for _, l := range ordered {
		total += l.total
	}
	items := []*screensv1.PagePanelItem{}
	legend := []*screensv1.PageLink{}
	for _, l := range ordered {
		pct := budgetpage.Percentage(l.total, total)
		if pct >= 7 {
			items = append(items, text(fmt.Sprintf("%d%%", pct)))
		}
		legend = append(legend, &screensv1.PageLink{Text: l.label + budgetpage.UGXCompact(l.total)})
	}
	return []*screensv1.PageBlock{panel(title, append(items, links(legend...))...)}
}

type event struct {
	who, what, action, amount string
	at                        time.Time
}

// recent is _recent: the latest disbursements, partner payments and
// returned plans, newest first, six at most, by the names the queue
// learned.
func (s *Service) recent(ctx context.Context, q *queue) (*screensv1.PageBlock, error) {
	events := []event{}
	read := func(sql string, each func(r pgx.Rows) (event, bool, error), args ...any) error {
		rows, err := s.db.Query(ctx, sql, args...)
		if err != nil {
			return fmt.Errorf("disbursements: reading the recent activity: %w", err)
		}
		return forEach(rows, func(r pgx.Rows) error {
			e, keep, err := each(r)
			if keep {
				events = append(events, e)
			}
			return err
		})
	}
	money := func(disbursed *int64, total int64) string {
		if disbursed != nil && *disbursed != 0 {
			return budgetpage.UGXCompact(*disbursed)
		}
		return budgetpage.UGXCompact(total)
	}
	err := read(`SELECT COALESCE(submitted_by_user_id, ''), period_key, disbursed_amount, total_amount, disbursed_at
		FROM fund_request WHERE period = 'monthly' AND disbursed_at IS NOT NULL ORDER BY disbursed_at DESC LIMIT 6`,
		func(r pgx.Rows) (event, bool, error) {
			var owner, key string
			var amount *int64
			var total int64
			var at time.Time
			err := r.Scan(&owner, &key, &amount, &total, &at)
			return event{q.name(owner, "CCEO"), key + " Fund Plan", "Disbursed", money(amount, total), at}, err == nil, err
		})
	if err == nil {
		err = read(`SELECT COALESCE(responsible_user, ''), week_start_date, disbursed_amount, total_amount, disbursed_at
			FROM weekly_fund_request WHERE disbursed_at IS NOT NULL ORDER BY disbursed_at DESC LIMIT 6`,
			func(r pgx.Rows) (event, bool, error) {
				var owner string
				var start, at time.Time
				var amount *int64
				var total int64
				err := r.Scan(&owner, &start, &amount, &total, &at)
				return event{q.name(owner, "Staff"), "Weekly Advance " + shortDay(start), "Disbursed", money(amount, total), at}, err == nil, err
			})
	}
	if err == nil {
		err = read(`SELECT partner_name, amount_paid, payment_date FROM partner_payment ORDER BY payment_date DESC LIMIT 4`,
			func(r pgx.Rows) (event, bool, error) {
				var e event
				var paid int64
				err := r.Scan(&e.who, &paid, &e.at)
				e.what, e.action, e.amount = "Partner Payment", "Paid", budgetpage.UGXCompact(paid)
				return e, err == nil, err
			})
	}
	if err == nil {
		err = read(`SELECT COALESCE(submitted_by_user_id, ''), period_key, total_amount, reviewed_at
			FROM fund_request WHERE period = 'monthly' AND status = 'returned_by_accountant'
			ORDER BY reviewed_at DESC LIMIT 3`,
			func(r pgx.Rows) (event, bool, error) {
				var owner, key string
				var total int64
				var at *time.Time
				if err := r.Scan(&owner, &key, &total, &at); err != nil || at == nil {
					return event{}, false, err
				}
				return event{q.name(owner, "CCEO"), key + " Fund Plan", "Returned", budgetpage.UGXCompact(total), *at}, true, nil
			})
	}
	if err != nil {
		return nil, err
	}
	sort.SliceStable(events, func(i, j int) bool { return events[i].at.After(events[j].at) })
	list := []*screensv1.PageLink{}
	for i, e := range events {
		if i == 6 {
			break
		}
		list = append(list, &screensv1.PageLink{Text: fmt.Sprintf("%s — %s %s %s %s", e.who, e.what,
			strings.ToLower(e.action), e.amount, e.at.UTC().Format("Jan 2, 3:04 PM"))})
	}
	if len(list) == 0 {
		list = append(list, &screensv1.PageLink{Text: "No decisions recorded yet."})
	}
	list = append(list, &screensv1.PageLink{Text: "View all activity", Href: "/accounts/audit-log"})
	return panel("Recent Disbursement Activity", links(list...)), nil
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: t}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}
