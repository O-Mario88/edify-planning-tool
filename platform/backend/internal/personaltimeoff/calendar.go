package personaltimeoff

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pynum"
)

// The Team Availability Calendar (leave_views.leave_calendar_view,
// pages/leave/leave_calendar.html). The grid is drawn in the browser from
// its events; what the feed reads is the month's activity panel
// (partials/leave/calendar_activity_panel.html): the reader's scheduled
// work of the month, by day, each day read as its first activity.

// CalendarPath is the page.
const CalendarPath = "/leave/calendar"

// excludedStatuses are the statuses the panel never lists besides the
// completed ones (off_calendar_done).
var excludedStatuses = []string{"cancelled", "rejected"}

// calendarAdminRole sees everyone's work (_calendar_staff_audience).
const calendarAdminRole = "Admin"

// calendarItem is one activity of the month.
type calendarItem struct {
	id, kind string
	day      time.Time
}

// monthWindow is _calendar_month_window: ?month=&year= as int() reads them,
// else today's month; a month or year out of range is today's.
func monthWindow(query url.Values, today time.Time) time.Time {
	month, year := int(today.Month()), today.Year()
	m, mOK := month, true
	if raw, ok := query["month"]; ok {
		m, mOK = pynum.Int(raw[len(raw)-1])
	}
	y, yOK := year, true
	if raw, ok := query["year"]; ok {
		y, yOK = pynum.Int(raw[len(raw)-1])
	}
	if mOK && yOK && m >= 1 && m <= 12 && y >= 2000 && y <= 2100 {
		month, year = m, y
	}
	return time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
}

// calendarOwners is _calendar_staff_audience's activity owners: nil (all)
// for the Admin, else the reader's user id and staff profile id.
func (s *Service) calendarOwners(ctx context.Context, p auth.Principal) ([]string, error) {
	if p.ActiveRole == calendarAdminRole {
		return nil, nil
	}
	owners := []string{p.UserID}
	var staff string
	err := s.db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1`, p.UserID).Scan(&staff)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("personaltimeoff: reading the reader's staff profile: %w", err)
	}
	if staff != "" {
		owners = append(owners, staff)
	}
	return owners, nil
}

// readCalendarItems is _calendar_activities' queryset, in its order.
func (s *Service) readCalendarItems(ctx context.Context, owners []string, start, end time.Time) ([]calendarItem, error) {
	zone := calendarpage.Location().String()
	args := []any{zone, start, end, append(append([]string{}, excludedStatuses...), calendarpage.OfficerCompletedStatuses()...)}
	audience := ""
	if owners != nil {
		args = append(args, owners)
		audience = ` AND (a.responsible_staff_id = ANY($5) OR (a.monitored_by_staff_id = ANY($5) AND a.delivery_type = 'partner'))`
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.activity_type, COALESCE((a.scheduled_date AT TIME ZONE $1)::date, a.planned_date)
FROM activity a
WHERE a.deleted_at IS NULL AND (
  (a.scheduled_date AT TIME ZONE $1)::date BETWEEN $2 AND $3
  OR (a.scheduled_date IS NULL AND a.planned_date BETWEEN $2 AND $3))
  AND NOT (a.status = ANY($4))`+audience+`
ORDER BY a.planned_date ASC, a.scheduled_date ASC, a.created_at ASC`, args...)
	if err != nil {
		return nil, fmt.Errorf("personaltimeoff: reading the month's activities: %w", err)
	}
	defer rows.Close()
	out := []calendarItem{}
	for rows.Next() {
		var it calendarItem
		var day *time.Time
		if err := rows.Scan(&it.id, &it.kind, &day); err != nil {
			return nil, fmt.Errorf("personaltimeoff: reading an activity: %w", err)
		}
		// A day the activity has neither scheduled nor planned is skipped.
		if day == nil {
			continue
		}
		it.day = *day
		out = append(out, it)
	}
	return out, rows.Err()
}

// calendarPage draws the page.
func (s *Service) calendarPage(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	r, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !r.Calendar {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now().In(calendarpage.Location())
	start := monthWindow(query, time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC))
	end := start.AddDate(0, 1, -1)
	owners, err := s.calendarOwners(ctx, p)
	if err != nil {
		return nil, true, err
	}
	items, err := s.readCalendarItems(ctx, owners, start, end)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Time & Availability", Title: "Team Availability Calendar",
		Description: "Leave, coverage, holidays and scheduled activities on one grid.",
		Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	return &screensv1.GetPageResponse{Header: header, Blocks: []*screensv1.PageBlock{monthPanel(start, items)},
		WebPath: CalendarPath}, true, nil
}

// monthPanel is the month's activity panel: the count, then each day as its
// first activity's link (the feed reads a day's list item as one link), or
// the empty month's sentence.
func monthPanel(start time.Time, items []calendarItem) *screensv1.PageBlock {
	count := text(fmt.Sprint(len(items)))
	if len(items) == 0 {
		return panel("Scheduled activities", start.Format("January 2006"), count,
			text("Nothing scheduled in "+start.Format("January")+"."))
	}
	first := map[time.Time]calendarItem{}
	days := []time.Time{}
	for _, it := range items {
		if _, seen := first[it.day]; !seen {
			first[it.day] = it
			days = append(days, it.day)
		}
	}
	slices.SortFunc(days, func(a, b time.Time) int { return a.Compare(b) })
	links := []*screensv1.PageLink{}
	for _, d := range days {
		it := first[d]
		links = append(links, &screensv1.PageLink{Text: calendarpage.ActivityTypeLabel(it.kind), Href: "/my-plan/" + it.id})
	}
	return panel("Scheduled activities", start.Format("January 2006"), count,
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})
}
