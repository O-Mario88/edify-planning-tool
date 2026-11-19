package budgetpage

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// FundAllocationPath is the Consolidated Fund Allocation
// (finance_views.fund_allocation_view, pages/finance/fund_allocation.html):
// budget_workspace's country roll-up of every staff member's planned costs
// for a week, month, quarter or year, the country admin plan beside them in
// the month, quarter and year, narrowed to a district on request.
//
// Handed on: an export, a search of the groups (it matches the owners'
// names the ledger does not carry), a year or date that is not plain, a
// reader whose Budget is not the country's, a platform of several
// countries with no request country, and a ledger longer than one page.
const FundAllocationPath = "/finance/fund-allocation"

// fundQuery are the keys the page reads; page, per_page, month and
// export_mode only shape an export, which is handed on.
var fundQuery = []string{"fy", "date", "period", "district", "groups_page", "page", "per_page", "month", "export_mode"}

func (s *Service) fundAllocation(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, error) {
	for key := range query {
		if !slices.Contains(fundQuery, key) {
			return nil, errPassOn
		}
	}
	now := s.now()
	local := now.In(zone)
	today := date(local.Year(), local.Month(), local.Day())
	fyText := query.Get("fy")
	if fyText == "" {
		fyText = schooldirectory.OperationalFY(now)
	}
	if !plainYear.MatchString(fyText) {
		return nil, errPassOn
	}
	fy, _ := strconv.Atoi(fyText)
	anchor := today
	if d := query.Get("date"); d != "" {
		parsed, err := time.Parse(time.DateOnly, d)
		if err != nil || !plainDate.MatchString(d) {
			return nil, errPassOn
		}
		anchor = parsed
	}
	a := ask{fy: fy, anchor: anchor, period: query.Get("period"), budgetScope: "country",
		district: strings.TrimSpace(query.Get("district"))}
	if !slices.Contains([]string{"week", "month", "quarter", "fy"}, a.period) {
		a.period = "week"
	}
	a.settle()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: resolving the reader's scope: %w", err)
	}
	if !scope.CountryScope && !in(rules.CountryLedgerRoles, p.ActiveRole) {
		return nil, errPassOn
	}
	if p.Country != nil {
		a.countryIDs = []string{p.Country.ID}
	} else if several, err := s.multiCountry(ctx); err != nil || several {
		if err != nil {
			return nil, err
		}
		return nil, errPassOn
	}
	includeAdmin := a.district == ""
	var admin []adminLine
	if includeAdmin {
		if admin, err = s.adminLines(ctx, fyText); err != nil {
			return nil, err
		}
	}
	lines, err := s.lines(ctx, a, nil)
	if err != nil {
		return nil, err
	}
	dayRates, err := s.dayRates(ctx, lines)
	if err != nil {
		return nil, err
	}
	gs := groups(lines, dayRates)
	if includeAdmin && a.period != "week" {
		if g := adminGroup(admin, a.selected); g != nil {
			gs = append(gs, g)
			sort.SliceStable(gs, func(i, j int) bool {
				if gs[i].total != gs[j].total {
					return gs[i].total > gs[j].total
				}
				return gs[i].label < gs[j].label
			})
		}
	}
	if len(gs) > groupsPageSize {
		return nil, errPassOn
	}
	f := fundView{a: a, groups: gs, now: now}
	for _, key := range []string{"week", "month", "quarter", "fy"} {
		pr := a.periods[key]
		total, err := s.programTotal(ctx, a, pr)
		if err != nil {
			return nil, err
		}
		if includeAdmin && key != "week" {
			total += adminTotal(admin, pr)
		}
		f.totals = append(f.totals, total)
	}
	if f.currency, err = registry.CurrencyOf(ctx, s.db, p.Country); err != nil {
		return nil, err
	}
	if f.districts, err = s.districts(ctx); err != nil {
		return nil, err
	}
	f.adminNote = includeAdmin && a.period == "week"
	return &screensv1.GetPageResponse{Header: f.header(), Blocks: f.blocks(), WebPath: FundAllocationPath}, nil
}

// programTotal is the period's share of operational_totals: the money of
// the lines planned in it.
func (s *Service) programTotal(ctx context.Context, a ask, pr period) (int64, error) {
	where, args := a.lineWhere(nil, pr.start, pr.end)
	var total int64
	err := s.db.QueryRow(ctx, `
		SELECT COALESCE(SUM(l.amount), 0)::bigint
		FROM activity_schedule_cost_line l
		JOIN activity a ON a.id = l.activity_id
		LEFT JOIN school s ON s.id = a.school_id
		LEFT JOIN cluster cl ON cl.id = a.cluster_id
		WHERE `+where, args...).Scan(&total)
	if err != nil {
		return 0, fmt.Errorf("budgetpage: summing the %s's cost lines: %w", pr.key, err)
	}
	return total, nil
}

// adminLine is one active line of the year's country admin plan.
type adminLine struct {
	description, category string
	unitCost, totalCost   int64
	quantity              pydecimal.Decimal
	planned               *time.Time
}

func (s *Service) adminLines(ctx context.Context, fy string) ([]adminLine, error) {
	rows, err := s.db.Query(ctx, `
		SELECT COALESCE(l.description, ''), COALESCE(l.cost_category, ''), COALESCE(l.unit_cost, 0), COALESCE(l.total_cost, 0),
		       COALESCE(l.quantity, 0)::text, COALESCE(b.month_key, '')
		FROM admin_budget_line l JOIN monthly_work_plan_budget b ON b.id = l.monthly_budget_id
		WHERE b.fy = $1 AND l.status = 'active'`, fy)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: reading the country admin plan: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (adminLine, error) {
		var l adminLine
		var quantity, key string
		if err := row.Scan(&l.description, &l.category, &l.unitCost, &l.totalCost, &quantity, &key); err != nil {
			return l, err
		}
		q, err := pydecimal.Parse(quantity)
		if err != nil {
			return l, fmt.Errorf("budgetpage: an admin line's quantity %q: %w", quantity, err)
		}
		l.quantity, l.planned = q, monthStart(key)
		return l, nil
	})
}

// monthStart is _month_start_for_key: "2027-3" as the first of its month,
// nil when it does not read.
func monthStart(key string) *time.Time {
	year, month, ok := strings.Cut(key, "-")
	if !ok {
		return nil
	}
	y, err1 := strconv.Atoi(strings.TrimSpace(year))
	m, err2 := strconv.Atoi(strings.TrimSpace(month))
	if err1 != nil || err2 != nil || m < 1 || m > 12 || y < 1 || y > 9999 {
		return nil
	}
	d := date(y, time.Month(m), 1)
	return &d
}

func inPeriod(d *time.Time, pr period) bool {
	return d != nil && !d.Before(pr.start) && !d.After(pr.end)
}

// adminTotal is admin_total(period): the admin plan's money planned in it.
func adminTotal(lines []adminLine, pr period) int64 {
	var total int64
	for _, l := range lines {
		if inPeriod(l.planned, pr) {
			total += l.totalCost
		}
	}
	return total
}

// adminGroup is budget_groups' "Country Admin Plan": a row an item and its
// unit cost, the item its description or its category made readable, its
// quantity summed; nil when nothing is planned in the period.
func adminGroup(lines []adminLine, pr period) *group {
	var g *group
	for _, l := range lines {
		if !inPeriod(l.planned, pr) {
			continue
		}
		if g == nil {
			g = &group{label: "Country Admin Plan", kind: "admin", isAdmin: true, byKey: map[string]*row{}, activityIDs: map[string]bool{}}
		}
		item := l.description
		if item == "" {
			item = pyTitle(strings.ReplaceAll(l.category, "_", " "))
		}
		key := item + "\x00" + strconv.FormatInt(l.unitCost, 10)
		r, ok := g.byKey[key]
		if !ok {
			zero := pydecimal.Int(0)
			r = &row{item: item, rate: l.unitCost, dates: map[string]bool{}, people: map[string]int64{}, activityIDs: map[string]bool{}, quantity: &zero}
			g.byKey[key] = r
			g.rows = append(g.rows, r)
		}
		r.dates[l.planned.Format(time.DateOnly)] = true
		sum := r.quantity.Add(l.quantity)
		r.quantity = &sum
		r.staffTotal += l.totalCost
		r.total += l.totalCost
		g.staffTotal += l.totalCost
		g.total += l.totalCost
	}
	if g != nil {
		sort.SliceStable(g.rows, func(i, j int) bool {
			a, b := g.rows[i], g.rows[j]
			if a.total != b.total {
				return a.total > b.total
			}
			if a.item != b.item {
				return a.item < b.item
			}
			return a.rate < b.rate
		})
	}
	return g
}

// fundView is the page as the feed reads it.
type fundView struct {
	a         ask
	groups    []*group
	totals    []int64
	districts []district
	currency  string
	adminNote bool
	now       time.Time
}

func (f fundView) code() string {
	if f.currency == "" {
		return "UGX"
	}
	return f.currency
}

func (f fundView) amount(n int64) string { return inCurrency(f.code(), n) }

func (f fundView) header() *screensv1.PageHeader {
	fy := strconv.Itoa(f.a.fy)
	month := f.a.selected.start.Format("January")
	return &screensv1.PageHeader{
		Eyebrow: "Country funding roll-up", Title: "Consolidated Fund Allocation",
		Description: "Every staff member’s planned costs, nationally · " + f.a.selected.title + " · FY " + fy,
		Actions: []*screensv1.PageAction{
			{Key: "admin_budget_breakdown", Label: "Admin Budget Breakdown", Enabled: true, Drawer: true,
				Href: FundAllocationPath + "/admin-budget-drilldown?fy=" + fy + "&month=" + month},
			{Key: "export", Label: "Export", Enabled: true, Drawer: true,
				Href: FundAllocationPath + "/export-drawer?fy=" + fy + "&month=" + month},
		},
	}
}

func (f fundView) blocks() []*screensv1.PageBlock {
	a := f.a
	fy := strconv.Itoa(a.fy)
	day := a.anchor.Format(time.DateOnly)
	rail := &screensv1.PageLinks{}
	for i, key := range []string{"week", "month", "quarter", "fy"} {
		rail.Links = append(rail.Links, &screensv1.PageLink{Text: a.periods[key].title,
			Href: "?fy=" + fy + "&date=" + day + "&period=" + key, Caption: f.amount(f.totals[i])})
	}
	out := []*screensv1.PageBlock{
		panel("", "", text("Finance"), text("Consolidated Fund Allocation")),
		panel("", "", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: rail}}),
		panel("Activity cost plan — whole country", "", text("Costs are grouped by activity and item across every staff member. "+
			"Training and meeting tables show sessions and participants; the country admin budget is included in the Month, Quarter and Fiscal Year views.")),
	}
	if len(f.districts) > 0 {
		district := &screensv1.PageFilter{Name: "district", Label: "District", Value: a.district,
			Options: []*screensv1.PageFilterOption{{Value: "", Label: "All districts"}}}
		for _, d := range f.districts {
			district.Options = append(district.Options, &screensv1.PageFilterOption{Value: d.id, Label: d.name})
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
			Filters: []*screensv1.PageFilter{district},
			Hidden:  map[string]string{"fy": fy, "date": day, "period": a.period},
		}}})
	}
	if f.adminNote {
		out = append(out, panel("", "", text("Country admin costs are planned by month, so they appear in the Month, Quarter and Fiscal Year views rather than being estimated into a week.")))
	}
	var program, admin, staff int64
	for _, g := range f.groups {
		staff += g.staffTotal
		if g.isAdmin {
			admin += g.total
		} else {
			program += g.total
		}
	}
	total := program + admin
	rows := []*screensv1.PageRow{
		cells("No costed activities in this period. Schedule activities in My Plan to populate this budget."),
		cells("Grand total", f.amount(staff), f.amount(total)),
	}
	if len(f.groups) > 0 {
		rows = ledgerRows(f.code(), f.groups, staff, total)
	}
	out = append(out, panel("", "", figure("Grand total", f.amount(total))),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Rows: rows}}})
	if len(f.groups) == 0 {
		return append(out, panel("", "", text("No costed activities in this period"),
			text("Choose another time view; the country roll-up fills in as staff schedule and cost their work.")))
	}
	footer := "Program costs: " + f.amount(program)
	if admin != 0 {
		footer += " · Country admin plan: " + f.amount(admin)
	}
	// timezone.now().strftime: the moment in UTC.
	footer += " · Updated " + f.now.UTC().Format("January 02, 2006 03:04 PM")
	return append(out, panel("", "", text(footer)))
}
