package fundapprovals

import (
	"context"
	"errors"
	"fmt"
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
	fw "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundworkspace"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PagePath is the page's path.
const PagePath = "/fund-approvals"

// ownQuery is what the view reads.
var ownQuery = []string{"fy", "month", "week", "cceo", "status", "q", "region", "district", "sort"}

// recentFallbackLimit is the [:200] the recent decisions read when the
// month holds no request.
const recentFallbackLimit = 200

var (
	plainYear  = regexp.MustCompile(`^\d{4}$`)
	plainMonth = regexp.MustCompile(`^\d{1,2}$`)
	plainDay   = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)
	digit      = regexp.MustCompile(`\d`)
)

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("fundapprovals: " + err.Error())
	}
	return z
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService returns the page's builder.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

type ask struct {
	fy, cceo, status, region, district, sort, search string
	month                                            int
	monthAsked                                       bool
	week                                             *time.Time
}

func floor(d time.Time) time.Time {
	d = time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, time.UTC)
	return d.AddDate(0, 0, -((int(d.Weekday()) + 6) % 7))
}

// readAsk reads the query as the view does; ok is false for one Go hands
// on.
func readAsk(query url.Values, now time.Time) (ask, bool) {
	a := ask{
		fy: query.Get("fy"), cceo: query.Get("cceo"), status: query.Get("status"),
		region:   strings.TrimSpace(query.Get("region")),
		district: strings.TrimSpace(query.Get("district")),
		sort:     query.Get("sort"),
		search:   strings.ToLower(strings.TrimSpace(query.Get("q"))),
		month:    int(now.In(zone).Month()),
	}
	if a.sort != "name" && a.sort != "status" {
		a.sort = "amount"
	}
	if a.fy == "" {
		a.fy = schooldirectory.OperationalFY(now)
	} else if !plainYear.MatchString(a.fy) {
		return a, false
	}
	if m := query.Get("month"); m != "" {
		n, err := strconv.Atoi(m)
		if !plainMonth.MatchString(m) || err != nil || n < 1 || n > 12 {
			return a, false
		}
		a.month, a.monthAsked = n, true
	}
	if w := query.Get("week"); w != "" {
		if len(w) > 10 {
			w = w[:10]
		}
		switch {
		case plainDay.MatchString(w):
			if d, err := time.Parse(time.DateOnly, w); err == nil {
				d = floor(d)
				a.week = &d
			}
		case digit.MatchString(w):
			// date.fromisoformat reads more forms than the plain day
			// (20261123, 2026-W48); Go reads only that one.
			return a, false
		}
	}
	return a, true
}

// Build answers /fund-approvals.
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
	a, ok := readAsk(query, now)
	if !ok {
		return nil, false, nil
	}
	var invoices int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM partner_invoice WHERE status = 'submitted_to_pl'`).Scan(&invoices); err != nil {
		return nil, true, fmt.Errorf("fundapprovals: reading the partner invoices: %w", err)
	}
	if invoices > 0 {
		return nil, false, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	officers, err := team(ctx, s.db, scope)
	if err != nil {
		return nil, true, err
	}
	if len(officers) == 0 {
		return nil, false, nil
	}
	awaiting := "submitted_to_pl"
	if p.ActiveRole == "CountryDirector" {
		awaiting = "submitted_to_cd"
	}
	ids := teamIDs(officers)
	week, weeks, err := s.pickWeek(ctx, &a, officers, ids, awaiting, now)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	lines, err := weekLines(ctx, s.db, ids, a.fy, week)
	if err != nil {
		return nil, true, err
	}
	byOfficer := map[string][]line{}
	for _, l := range lines {
		for _, o := range officers {
			if o.holds(l.staffID) {
				byOfficer[o.userID] = append(byOfficer[o.userID], l)
				break
			}
		}
	}
	withWork := []string{}
	for _, o := range officers {
		if len(byOfficer[o.userID]) > 0 {
			withWork = append(withWork, o.userID)
		}
	}
	reqs, err := requests(ctx, s.db, withWork, week)
	if err != nil {
		return nil, true, err
	}
	plans := []plan{}
	for _, o := range officers {
		ls := byOfficer[o.userID]
		if len(ls) == 0 {
			continue
		}
		req, ok := reqs[o.userID]
		if !ok {
			// The existing page writes the missing request as it opens.
			return nil, false, nil
		}
		plans = append(plans, buildPlan(o, ls, req, awaiting))
	}
	sortPlans(plans)
	queue := filtered(a, plans)

	month, err := s.month(ctx, a, officers, ids, awaiting, now)
	if err != nil {
		return nil, true, err
	}
	if month == nil {
		return nil, false, nil
	}
	blocks := []*screensv1.PageBlock{s.filters(a, plans, week, weeks, now), strip(plans, awaiting, budgetpage.CurrencyCode(p.Country))}
	weekISO := week.Format(time.DateOnly)
	tabs := []*screensv1.PageLink{}
	for _, pl := range queue {
		tabs = append(tabs, &screensv1.PageLink{Text: pl.officer.name,
			Href: fmt.Sprintf("/fund-approvals/detail?cceo=%s&fy=%s&month=%d&week=%s", pl.officer.userID, a.fy, a.month, weekISO)})
	}
	blocks = append(blocks, fw.Queue("CCEO Fund Approval Queue", tabs,
		"No fund plans match your filters", "Change the week, month or status, or clear the search.")...)
	if len(queue) > 0 {
		sel := queue[0]
		for _, pl := range queue {
			if pl.officer.userID == a.cceo {
				sel = pl
				break
			}
		}
		detail, ok, err := detailTable(ctx, s.db, sel)
		if err != nil {
			return nil, true, err
		}
		if !ok {
			return nil, false, nil
		}
		blocks = append(blocks, detail)
	}
	blocks = append(blocks, month.side, month.mix, month.recent)

	approvable := false
	for _, pl := range plans {
		approvable = approvable || pl.canApprove
	}
	h := &screensv1.PageHeader{
		Title:       "Fund Approvals",
		Description: "All fund requests are derived from CCEO plans. You approve only funds for your own team.",
	}
	if doors.Export {
		h.Actions = append(h.Actions, &screensv1.PageAction{Key: "export", Label: "Export", Enabled: true, Download: true,
			Href: fmt.Sprintf("/fund-approvals?export=csv&fy=%s&month=%d&week=%s", a.fy, a.month, weekISO)})
	}
	approveAll := &screensv1.PageAction{Key: "approve_all_valid", Label: "Approve All Valid", Enabled: approvable}
	if !approvable {
		approveAll.Reason = "No valid plan is awaiting your approval this week."
	}
	h.Actions = append(h.Actions, approveAll)
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, WebPath: PagePath}, true, nil
}

// pickWeek is where the page opens: the asked week; with neither week nor
// month, the earliest week a request waits on this approver (else this
// week), its month the commonest of its lines'; with a month and no week,
// the month's busiest week (else this week). weeks is the week select's
// options.
func (s *Service) pickWeek(ctx context.Context, a *ask, officers []officer, ids []string, awaiting string, now time.Time) (time.Time, []*screensv1.PageFilterOption, error) {
	thisWeek := floor(now.In(zone))
	week := a.week
	if week == nil && !a.monthAsked {
		var first *time.Time
		err := s.db.QueryRow(ctx, `SELECT week_start_date FROM weekly_fund_request
			WHERE responsible_user = ANY($1) AND status = $2 AND fy = $3 ORDER BY week_start_date LIMIT 1`,
			userIDs(officers), awaiting, a.fy).Scan(&first)
		if err != nil && err != pgx.ErrNoRows {
			return time.Time{}, nil, fmt.Errorf("fundapprovals: reading the earliest waiting week: %w", err)
		}
		if first != nil {
			d := floor(*first)
			week = &d
		} else {
			week = &thisWeek
		}
	}
	if week != nil && !a.monthAsked {
		var m *int
		err := s.db.QueryRow(ctx, `SELECT l.month, COUNT(l.id) AS n`+weekBase+`
			  AND l.week_start_date = $3 AND l.month IS NOT NULL
			GROUP BY l.month ORDER BY n DESC LIMIT 1`, ids, a.fy, *week).Scan(&m, new(int))
		if err != nil && err != pgx.ErrNoRows {
			return time.Time{}, nil, fmt.Errorf("fundapprovals: reading the week's month: %w", err)
		}
		a.month = int(week.Month())
		if m != nil {
			a.month = *m
		}
		if a.month < 1 || a.month > 12 {
			return time.Time{}, nil, errHandOn
		}
	}
	rows, err := s.db.Query(ctx, `SELECT l.week_start_date, COUNT(l.id) AS n`+weekBase+`
		  AND l.month = $3
		GROUP BY l.week_start_date ORDER BY l.week_start_date`, ids, a.fy, a.month)
	if err != nil {
		return time.Time{}, nil, fmt.Errorf("fundapprovals: reading the month's weeks: %w", err)
	}
	type counted struct {
		start time.Time
		n     int
	}
	monthWeeks := []counted{}
	if err := forEach(rows, func(r pgx.Rows) error {
		var c counted
		if err := r.Scan(&c.start, &c.n); err != nil {
			return err
		}
		monthWeeks = append(monthWeeks, c)
		return nil
	}); err != nil {
		return time.Time{}, nil, fmt.Errorf("fundapprovals: reading the month's weeks: %w", err)
	}
	if week == nil {
		week = &thisWeek
		best := 0
		for _, c := range monthWeeks {
			if c.n > best {
				d := c.start
				week, best = &d, c.n
			}
		}
	}
	label := func(d time.Time) string { return d.Format("Jan 02") + " – " + d.AddDate(0, 0, 6).Format("Jan 02") }
	options := []*screensv1.PageFilterOption{}
	found := false
	for _, c := range monthWeeks {
		options = append(options, &screensv1.PageFilterOption{Value: c.start.Format(time.DateOnly), Label: label(c.start)})
		found = found || c.start.Equal(*week)
	}
	if !found {
		options = append(options, &screensv1.PageFilterOption{Value: week.Format(time.DateOnly), Label: label(*week)})
	}
	return *week, options, nil
}

// filtered is the queue: the status, region, district and search filters,
// then the asked order.
func filtered(a ask, plans []plan) []plan {
	out := []plan{}
	for _, pl := range plans {
		switch {
		case a.status != "" && pl.status != a.status,
			a.region != "" && pl.region != a.region,
			a.district != "" && pl.district != a.district,
			a.search != "" && !strings.Contains(strings.ToLower(pl.officer.name), a.search) &&
				!strings.Contains(strings.ToLower(pl.district), a.search):
			continue
		}
		out = append(out, pl)
	}
	switch a.sort {
	case "name":
		sort.SliceStable(out, func(i, j int) bool {
			return strings.ToLower(out[i].officer.name) < strings.ToLower(out[j].officer.name)
		})
	case "status":
		sort.SliceStable(out, func(i, j int) bool {
			if out[i].status != out[j].status {
				return out[i].status < out[j].status
			}
			return out[i].total > out[j].total
		})
	}
	return out
}

func (s *Service) filters(a ask, plans []plan, week time.Time, weeks []*screensv1.PageFilterOption, now time.Time) *screensv1.PageBlock {
	districts := []string{}
	for _, pl := range plans {
		if pl.district != "—" && !slices.Contains(districts, pl.district) {
			districts = append(districts, pl.district)
		}
	}
	sort.Strings(districts)
	district := &screensv1.PageFilter{Name: "district", Label: "District",
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All Districts"}}}
	for _, d := range districts {
		district.Options = append(district.Options, &screensv1.PageFilterOption{Value: d, Label: d})
		if d == a.district {
			district.Value = d
		}
	}
	order := &screensv1.PageFilter{Name: "sort", Label: "Sort the queue", Caption: "Sort by", Value: a.sort,
		Options: []*screensv1.PageFilterOption{{Value: "amount", Label: "Amount"}, {Value: "name", Label: "Name"},
			{Value: "status", Label: "Status"}}}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			fw.YearFilter(schooldirectory.FYOptions(now), a.fy),
			fw.MonthFilter(rules.Months, a.month),
			{Name: "week", Label: "Week", Value: week.Format(time.DateOnly), Options: weeks},
			district, order,
		}}}}
}

func requestsWord(n int) string {
	if n == 1 {
		return "1 request"
	}
	return fmt.Sprintf("%d requests", n)
}

// strip is the week's money across every plan: requested, awaiting this
// approver, approved and returned.
func strip(plans []plan, awaiting, code string) *screensv1.PageBlock {
	var sums [4]int64
	var counts [4]int
	for _, pl := range plans {
		add := func(i int) { sums[i] += pl.req.total; counts[i]++ }
		add(0)
		switch {
		case pl.req.status == awaiting:
			add(1)
		case pl.req.status == "confirmed_for_advance" || pl.req.status == "disbursed":
			add(2)
		case strings.HasPrefix(pl.req.status, "returned"):
			add(3)
		}
	}
	values, helpers := []string{}, []string{}
	for i := range sums {
		values = append(values, budgetpage.CompactIn(code, sums[i]))
		helpers = append(helpers, requestsWord(counts[i]))
	}
	return fw.Strip("Approval context", rules.MetricLabels, values, helpers)
}

// detailTable is the selected plan as the feed reads it: the officer's name
// and the plan, the action row's words (Approve and Return while the
// request waits on this approver, else what it waits on) and the request's
// submitted ledger.
func detailTable(ctx context.Context, db schooldirectory.Querier, pl plan) (*screensv1.PageBlock, bool, error) {
	rows, ok, err := budgetpage.WeeklyRequestLedger(ctx, db, pl.req.id)
	if err != nil || !ok {
		return nil, ok, err
	}
	words := []string{"View Full Plan"}
	if pl.canApprove || pl.canReturn {
		words = append(words, "Approve", "Return")
	} else if hint := rules.Hints[pl.req.status]; hint != "" {
		words = append(words, hint)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title: pl.officer.name + " — Weekly Fund Plan", Subtitle: strings.Join(words, " "), Rows: rows}}}, true, nil
}
