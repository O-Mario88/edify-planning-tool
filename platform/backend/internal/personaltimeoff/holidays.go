package personaltimeoff

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// Public Holidays & Blackout Dates (leave_views.public_holidays_view,
// pages/leave/public_holidays.html): the recorded public holidays still to
// come and the national calendar's own, then the blackout dates, the staff
// conference weeks and the regional events. Its writes (adding, removing
// and seeding blocks) are the existing application's.

// HolidaysPath is the page.
const HolidaysPath = "/public-holidays"

// nationalLimit is upcoming_public_holidays(..., limit=40).
const nationalLimit = 40

// holidaysRole is what a role is given on the page.
type holidaysRole struct {
	Page   bool               `json:"page"`
	Strip  *decisionlog.Strip `json:"strip"`
	Editor bool               `json:"editor"`
}

// calendarBlock is one active CalendarBlock.
type calendarBlock struct {
	title, description, kind, region string
	start, end                       time.Time
}

// apMonths are Django's "N" month names.
var apMonths = [...]string{"Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."}

// djangoDate is a date as a template prints one (DATE_FORMAT "N j, Y").
func djangoDate(t time.Time) string {
	return apMonths[t.Month()-1] + " " + strconv.Itoa(t.Day()) + ", " + strconv.Itoa(t.Year())
}

// readBlocks is CalendarBlock.objects.filter(is_active=True).order_by("start_date").
func (s *Service) readBlocks(ctx context.Context) ([]calendarBlock, error) {
	rows, err := s.db.Query(ctx, `
SELECT b.title, COALESCE(b.description, ''), b.block_type, COALESCE(r.name, ''), b.start_date, b.end_date
FROM calendar_block b LEFT JOIN region r ON r.id = b.region_id
WHERE b.is_active ORDER BY b.start_date`)
	if err != nil {
		return nil, fmt.Errorf("personaltimeoff: reading the calendar blocks: %w", err)
	}
	defer rows.Close()
	out := []calendarBlock{}
	for rows.Next() {
		var b calendarBlock
		if err := rows.Scan(&b.title, &b.description, &b.kind, &b.region, &b.start, &b.end); err != nil {
			return nil, fmt.Errorf("personaltimeoff: reading a calendar block: %w", err)
		}
		out = append(out, b)
	}
	return out, rows.Err()
}

// holidays draws the page.
func (s *Service) holidays(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	r, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	h := r.Holidays
	if !h.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	// An editor's ?action=seed files the default blocks: a write.
	if h.Editor && query.Get("action") == "seed" {
		return nil, false, nil
	}
	now := s.now().In(kampala)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	blocks, err := s.readBlocks(ctx)
	if err != nil {
		return nil, true, err
	}
	upcoming, err := calendarpage.Upcoming(ctx, s.db, today, nationalLimit)
	if err != nil {
		return nil, true, fmt.Errorf("personaltimeoff: reading the national calendar: %w", err)
	}
	out := []*screensv1.PageBlock{}
	if st := h.Strip; st != nil {
		out = append(out, stripBlock(st))
	}
	out = append(out, holidayPanels(blocks, upcoming, today)...)
	header := &screensv1.PageHeader{Eyebrow: "Time & Availability", Title: "Public Holidays & Blackout Dates",
		Description: "Configure organization blackout dates, public holidays, and staff conference weeks",
		Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	if h.Editor {
		header.Actions = append(header.Actions,
			&screensv1.PageAction{Key: "seed_default_blocks", Label: "Seed Default Blocks", Enabled: true, Href: HolidaysPath + "?action=seed"},
			&screensv1.PageAction{Key: "add_block", Label: "Add Block", Enabled: true, Href: "#dialog=showAddDrawer", Drawer: true})
	}
	// The add drawer is on the page for every reader; only an editor is
	// offered the button that opens it.
	dialogs := []*screensv1.PageDialog{{Key: "showAddDrawer", Title: "Add Calendar Block",
		Blocks: []*screensv1.PageBlock{panel("Add Calendar Block", "")}}}
	return &screensv1.GetPageResponse{Header: header, Dialogs: dialogs, Blocks: out, WebPath: HolidaysPath}, true, nil
}

// holidayPanels are the four cards.
func holidayPanels(blocks []calendarBlock, upcoming []calendarpage.Holiday, today time.Time) []*screensv1.PageBlock {
	of := func(kind string) []calendarBlock {
		list := []calendarBlock{}
		for _, b := range blocks {
			if b.kind == kind {
				list = append(list, b)
			}
		}
		return list
	}
	public := []*screensv1.PagePanelItem{}
	for _, b := range of("PUBLIC_HOLIDAY") {
		if b.end.Before(today) {
			continue
		}
		when := djangoDate(b.start)
		if !b.start.Equal(b.end) {
			when += " to " + djangoDate(b.end)
		}
		public = append(public, text(b.title), text(when))
	}
	for _, n := range upcoming {
		if !n.Recorded {
			public = append(public, text(n.Label), text(n.Date.Format("Monday 2 January 2006")), text("National calendar"))
		}
	}
	listed := func(list []calendarBlock, empty string, extra func(calendarBlock) string) []*screensv1.PagePanelItem {
		items := []*screensv1.PagePanelItem{}
		for _, b := range list {
			items = append(items, text(b.title), text(djangoDate(b.start)+" to "+djangoDate(b.end)))
			if line := extra(b); line != "" {
				items = append(items, text(line))
			}
		}
		if len(items) == 0 {
			items = append(items, text(empty))
		}
		return items
	}
	description := func(b calendarBlock) string { return b.description }
	region := func(b calendarBlock) string {
		name := b.region
		if name == "" {
			name = "All"
		}
		return "Applies to: Region " + name
	}
	return []*screensv1.PageBlock{
		panel("Public Holidays", "", public...),
		panel("Organizational Blackout Dates", "", listed(of("BLACKOUT_DATE"), "No blackout dates active.", description)...),
		panel("Staff Conference Weeks", "", listed(of("STAFF_CONFERENCE"), "No staff conference weeks scheduled.", description)...),
		// The custom blocks the view reads are not drawn by the template.
		panel("Regional Events & Custom Blocks", "", listed(of("REGIONAL_EVENT"), "No regional calendar blocks.", region)...),
	}
}
