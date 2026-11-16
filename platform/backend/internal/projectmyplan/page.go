package projectmyplan

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	_ "time/tzdata" // the page's day is Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
)

// PagePath is the page's path.
const PagePath = "/projects/my-plan"

var ownQuery = []string{"fy", "quarter", "month", "week", "region", "district", "project", "partner", "activity_type", "status", "period", "q"}

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("projectmyplan: " + err.Error())
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

// filters is the page's filters as get_my_plan settles them.
type filters struct {
	fy, quarter, month, week, period                                 string
	region, district, project, partner, activityType, status, search string
}

type week struct {
	value, label string
	start, end   time.Time
}

func dayOf(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// quarterOf is get_quarter_for_date.
func quarterOf(d time.Time) string {
	switch m := d.Month(); {
	case m >= time.October:
		return "Q1"
	case m <= time.March:
		return "Q2"
	case m <= time.June:
		return "Q3"
	}
	return "Q4"
}

// weeksOf is _weeks_for_month: Monday-starting weeks that touch the month.
func weeksOf(year int, month time.Month) []week {
	first := time.Date(year, month, 1, 0, 0, 0, 0, time.UTC)
	last := first.AddDate(0, 1, -1)
	cursor := first.AddDate(0, 0, -((int(first.Weekday()) + 6) % 7))
	out := []week{}
	for !cursor.After(last) {
		end := cursor.AddDate(0, 0, 6)
		out = append(out, week{value: cursor.Format(time.DateOnly), start: cursor, end: end,
			label: fmt.Sprintf("%s %d – %s %d", cursor.Format("Jan"), cursor.Day(), end.Format("Jan"), end.Day())})
		cursor = cursor.AddDate(0, 0, 7)
	}
	return out
}

// monthYear is the calendar year a month of the year falls in.
func monthYear(fy string, month int) int {
	end, _ := strconv.Atoi(fy)
	if month >= 10 {
		return end - 1
	}
	return end
}

var fyMonths = []int{10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9}

func choose(value string, allowed []string, fallback string) string {
	value = strings.TrimSpace(value)
	if slices.Contains(allowed, value) {
		return value
	}
	return fallback
}

// Build answers /projects/my-plan.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return nil, false, nil
		}
	}
	strip, err := stripBlock(role.Strip)
	if err != nil {
		return nil, true, err
	}
	now := s.now()
	today := dayOf(now.In(zone))
	sc, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, fmt.Errorf("projectmyplan: resolving the reader's scope: %w", err)
	}
	list, err := projects(ctx, s.db, p, sc)
	if err != nil {
		return nil, true, err
	}
	h := &screensv1.PageHeader{Title: "My Plan", Description: "Manage scheduled special-project activities by week, month, quarter, and fiscal year."}
	out := []*screensv1.PageBlock{}
	if strip != nil {
		out = append(out, strip)
	}
	if len(list) == 0 {
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title:    "No special projects are assigned to your role",
			Subtitle: "Once schools are assigned to a project you oversee, planning and partner activity will appear here."}}})
		return &screensv1.GetPageResponse{Header: h, Blocks: out, WebPath: PagePath}, true, nil
	}
	pg, err := s.read(ctx, p, list, query, now, today)
	if err != nil {
		return nil, true, err
	}
	body := pg.blocks()
	if strip != nil {
		out = append(out, body...)
	} else {
		// With no strip above it the feed reads the period bar as the page's
		// tabs, each holding the whole workspace.
		segs := &screensv1.PageSegments{Caption: "Showing plans for " + pg.periodLabel}
		for _, period := range [][2]string{{"week", "Week"}, {"month", "Month"}, {"quarter", "Quarter"}, {"fy", "FY"}} {
			segs.Segments = append(segs.Segments, &screensv1.PageSegment{Label: period[1], Active: pg.f.period == period[0], Blocks: body})
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: segs}})
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: out, WebPath: PagePath}, true, nil
}

// stripBlock is partials/_section_nav.html's strip as the feed reads it.
func stripBlock(raw json.RawMessage) (*screensv1.PageBlock, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil
	}
	var st struct {
		Label   string `json:"label"`
		Scrolls bool   `json:"scrolls"`
		Tabs    []struct {
			Label, Href string
			Active      bool
		} `json:"tabs"`
	}
	if err := json.Unmarshal(raw, &st); err != nil {
		return nil, fmt.Errorf("projectmyplan: reading the strip: %w", err)
	}
	t := &screensv1.PageLinkTabs{Label: st.Label, Scrolls: st.Scrolls}
	for _, tab := range st.Tabs {
		t.Tabs = append(t.Tabs, &screensv1.PageLinkTab{Label: tab.Label, Href: tab.Href, Active: tab.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: t}}, nil
}

// page is get_my_plan's context, as far as the workspace draws it.
type page struct {
	f                           filters
	fyOptions                   []string
	months                      []int
	weeks                       []week
	projects                    []project
	districts, partners         []option
	kinds                       []string
	periodLabel                 string
	breakdown                   [4]int
	visits, trainings, meetings []row
	partnerWork                 []row
	all                         []row
	total, completed            int
	budgeted, advanced          int
	evidencePending, iaPending  int
	overdue                     int
	attention                   []attention
	upcoming                    []row
	today                       time.Time
}

type attention struct{ issue, tone, title, url string }

func (s *Service) read(ctx context.Context, p auth.Principal, list []project, query url.Values, now, today time.Time) (*page, error) {
	pg := &page{projects: list, today: today, fyOptions: schooldirectory.FYOptions(now)}
	ids := make([]string, len(list))
	names := map[string]string{}
	for i, pr := range list {
		ids[i] = pr.id
		names[pr.id] = pr.name
	}
	f := filters{
		region: query.Get("region"), district: query.Get("district"), partner: query.Get("partner"),
		activityType: query.Get("activity_type"), status: query.Get("status"), search: strings.TrimSpace(query.Get("q")),
	}
	f.fy = choose(query.Get("fy"), pg.fyOptions, schooldirectory.OperationalFY(now))
	allowedMonths := []string{}
	for _, m := range fyMonths {
		allowedMonths = append(allowedMonths, strconv.Itoa(m))
	}
	f.month = choose(query.Get("month"), allowedMonths, strconv.Itoa(int(today.Month())))
	month, _ := strconv.Atoi(f.month)
	year := monthYear(f.fy, month)
	pg.weeks = weeksOf(year, time.Month(month))
	current := today.AddDate(0, 0, -((int(today.Weekday()) + 6) % 7))
	defaultWeek := pg.weeks[0].value
	weekValues := []string{}
	for _, w := range pg.weeks {
		weekValues = append(weekValues, w.value)
		if w.start.Equal(current) {
			defaultWeek = w.value
		}
	}
	f.week = choose(query.Get("week"), weekValues, defaultWeek)
	f.quarter = choose(query.Get("quarter"), []string{"Q1", "Q2", "Q3", "Q4"}, quarterOf(today))
	f.period = choose(query.Get("period"), []string{"week", "month", "quarter", "fy"}, "week")
	if f.project = query.Get("project"); !slices.Contains(ids, f.project) {
		f.project = ""
	}
	pg.f, pg.months = f, fyMonths
	q := baseQuery(ids, f)

	var selWeek week
	for _, w := range pg.weeks {
		if w.value == f.week {
			selWeek = w
		}
	}
	fyEnd, _ := strconv.Atoi(f.fy)
	monthStart := time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
	qStartMonth := map[string]time.Month{"Q1": time.October, "Q2": time.January, "Q3": time.April, "Q4": time.July}[f.quarter]
	qYear := fyEnd
	if f.quarter == "Q1" {
		qYear = fyEnd - 1
	}
	qStart := time.Date(qYear, qStartMonth, 1, 0, 0, 0, 0, time.UTC)
	ranges := map[string][2]time.Time{
		"week":    {selWeek.start, selWeek.end},
		"month":   {monthStart, monthStart.AddDate(0, 1, -1)},
		"quarter": {qStart, qStart.AddDate(0, 3, -1)},
		"fy":      {time.Date(fyEnd-1, time.October, 1, 0, 0, 0, 0, time.UTC), time.Date(fyEnd, time.October, 1, 0, 0, 0, 0, time.UTC).AddDate(0, 0, -1)},
	}
	for i, k := range []string{"week", "month", "quarter", "fy"} {
		n, err := s.count(ctx, q, ranges[k][0], ranges[k][1])
		if err != nil {
			return nil, err
		}
		pg.breakdown[i] = n
	}
	pg.periodLabel = map[string]string{
		"week":    fmt.Sprintf("%s %d – %s %d, %d", selWeek.start.Format("Jan"), selWeek.start.Day(), selWeek.end.Format("Jan"), selWeek.end.Day(), selWeek.end.Year()),
		"month":   fmt.Sprintf("%s %d", time.Month(month).String(), year),
		"quarter": f.quarter + " · FY " + f.fy,
		"fy":      "FY " + f.fy,
	}[f.period]
	works, err := s.works(ctx, q, ranges[f.period][0], ranges[f.period][1])
	if err != nil {
		return nil, err
	}
	if pg.partners, err = s.partners(ctx, q); err != nil {
		return nil, err
	}
	if pg.districts, err = s.districts(ctx, ids, f.region); err != nil {
		return nil, err
	}
	if pg.kinds, err = s.kinds(ctx, q); err != nil {
		return nil, err
	}
	workIDs := make([]string, len(works))
	for i, w := range works {
		workIDs[i] = w.id
	}
	next, err := todos.NextActions(ctx, s.db, workIDs, today)
	if err != nil {
		return nil, err
	}
	if pg.advanced, err = s.advanced(ctx, workIDs); err != nil {
		return nil, err
	}
	partnerNames := map[string]string{}
	for _, o := range pg.partners {
		partnerNames[o.value] = o.label
	}
	pg.assemble(p, works, next, partnerNames, names)
	return pg, nil
}
