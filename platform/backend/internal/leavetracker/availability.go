package leavetracker

import (
	"context"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// AvailabilityPath is the Team Availability Heatmap.
const AvailabilityPath = "/leave/team-availability"

// The window team_availability_view offers: four to twelve weeks, eight
// unless asked.
var weekOptions = []int{4, 8, 12}

const (
	defaultWeeks = 8
	minWeeks     = 4
	maxWeeks     = 12
)

// weeksAsked is int(request.GET.get("weeks", 8)) held within the window.
func weeksAsked(raw string, present bool) int {
	if !present {
		return defaultWeeks
	}
	n, err := strconv.Atoi(strings.TrimSpace(raw))
	if err != nil {
		return defaultWeeks
	}
	return max(minWeeks, min(maxWeeks, n))
}

// availability is team_availability_view.
func (s *Service) availability(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Availability {
		return nil, true, pagegate.ErrNotAvailable
	}
	_, present := query["weeks"]
	weeks := weeksAsked(query.Get("weeks"), present)
	local := s.now().In(zone)
	heat, err := Heatmap(ctx, s.db, p, slices.Contains(rules.HeatmapEveryoneRoles, p.ActiveRole), 0, weeks, local)
	if err != nil {
		return nil, true, err
	}
	return availabilityPage(role.AvailabilityStrip, heat, weeks, local, query), true, nil
}

// weekHeader is "Wk 3 · 14–20 Sep", or "Wk 4 · 30 Nov–6 Dec" across months.
func weekHeader(i int, start time.Time) string {
	end := start.AddDate(0, 0, 6)
	span := strconv.Itoa(start.Day()) + "–" + strconv.Itoa(end.Day()) + " " + end.Format("Jan")
	if start.Month() != end.Month() {
		span = strconv.Itoa(start.Day()) + " " + start.Format("Jan") + "–" + strconv.Itoa(end.Day()) + " " + end.Format("Jan")
	}
	return "Wk " + strconv.Itoa(i+1) + " · " + span
}

func plural(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// availabilityPage is pages/leave/team_availability.html as the feed reads
// it.
func availabilityPage(strip *decisionlog.Strip, heat []HeatRow, weeks int, local time.Time, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Time & Availability", Title: "Team Availability Heatmap",
		Description: "Workload, approved leave and calendar blocks for your team over the next " + strconv.Itoa(weeks) + " weeks"}
	// A window the select does not offer selects nothing, and a select with
	// nothing selected reads as its first option.
	value := strconv.Itoa(weekOptions[0])
	options := []*screensv1.PageFilterOption{}
	for _, w := range weekOptions {
		options = append(options, &screensv1.PageFilterOption{Value: strconv.Itoa(w), Label: "Next " + strconv.Itoa(w) + " weeks"})
		if w == weeks {
			value = strconv.Itoa(w)
		}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
		{Name: "weeks", Label: "Window", Value: value, Options: options}}}}}}
	if strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: strip.Label, Scrolls: strip.Scrolls}
		for _, t := range strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	if c := collisions(heat); c != nil {
		blocks = append(blocks, c)
	}
	blocks = append(blocks, panel("Availability Status Legend", text("Available"), text("On Leave (Approved)"),
		text("Staff Conference Week"), text("Blocked (Blackout Date)"), text("High Workload (5+ Activities)")),
		panel("4-Week Heatmap Matrix"))
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	monday := today.AddDate(0, 0, -((int(today.Weekday()) + 6) % 7))
	headers := []string{}
	for i := range weeks {
		headers = append(headers, weekHeader(i, monday.AddDate(0, 0, 7*i)))
	}
	number, pages := closedschools.PageOf(query.Get("weeks_headers_page"), len(headers), rules.PageSize)
	shown := headers[(number-1)*rules.PageSize : min(number*rules.PageSize, len(headers))]
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Staff Member & Role"}}}
	for _, h := range shown {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: h})
	}
	for _, r := range heat {
		row := &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: closedschools.Collapse(r.Name + " " + r.Role), Href: "/staff/" + r.StaffID}}}
		for _, w := range r.Weeks {
			row.Cells = append(row.Cells, &screensv1.PageCell{Text: w.Status + " " + strconv.Itoa(w.Activities)})
		}
		t.Rows = append(t.Rows, row)
	}
	if len(heat) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No team members found under your supervisor scope."}}}}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("weeks_headers_page", number, pages, len(headers), rules.PageSize, query, nil))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: AvailabilityPath}
}

// collisions is collision_report_from as the feed reads its card: the
// visits booked against absent staff, and each person with any, worst
// first; nil when there are none.
func collisions(heat []HeatRow) *screensv1.PageBlock {
	type hit struct {
		row   HeatRow
		total int
	}
	hits := []hit{}
	visits := 0
	for _, r := range heat {
		n := 0
		for _, w := range r.Weeks {
			n += w.Stranded
		}
		if n > 0 {
			hits = append(hits, hit{r, n})
			visits += n
		}
	}
	if visits == 0 {
		return nil
	}
	sort.SliceStable(hits, func(i, j int) bool { return hits[i].total > hits[j].total })
	items := []*screensv1.PagePanelItem{}
	for _, h := range hits {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: h.row.Name, Href: "/staff/" + h.row.StaffID, Caption: "· " + h.row.Role}}}}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: strconv.Itoa(visits) + " school " + plural(visits, "visit", "visits") + " scheduled against absent staff",
		Subtitle: strconv.Itoa(len(hits)) + " staff " + plural(len(hits), "member", "members") +
			" have field work booked in a week they are away. Reassign the visit or arrange cover.",
		Items: items}}}
}
