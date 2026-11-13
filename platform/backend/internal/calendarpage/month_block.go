package calendarpage

import (
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The month as one block (PageCalendar), as apps.mobile_feed.calendar_block
// reads it from the phone's month and agenda: each day with entries, each
// entry's kind, colour family, words, link, tick box, multi-day run and
// day-off mark, and the event-type tabs with their keys.

// kindTabs are the event-type tabs: their keys (the template's
// setEventFilter values) and labels, in the page's order.
var kindTabs = []struct{ key, label string }{
	{"all", "All events"}, {"activity", "Activities"}, {"leave", "Leave"},
	{"holiday", "Holidays"}, {"event", "Other events"},
}

func (v *view) kindCount(key string) int {
	if key == "all" {
		return v.m.total()
	}
	return v.m.counts[key]
}

func (v *view) calendar() *screensv1.PageBlock {
	c := &screensv1.PageCalendar{Year: int32(v.year), Month: int32(v.mon), Kind: v.eventKind}
	if !v.today.Before(v.m.start) && !v.today.After(v.m.end) {
		c.Today = v.today.Format(time.DateOnly)
	}
	for _, t := range kindTabs {
		c.Kinds = append(c.Kinds, &screensv1.PageChip{Value: t.key, Label: t.label, Count: itoa(v.kindCount(t.key))})
	}
	for _, d := range v.m.agendaDays() {
		day := &screensv1.PageCalendarDay{Date: d.Format(time.DateOnly), Today: d.Equal(v.today)}
		for _, e := range v.m.days[d] {
			day.DayOff = day.DayOff || e.dayOff
			day.Events = append(day.Events, &screensv1.PageCalendarEvent{
				Kind: e.kind, Family: e.family, Title: collapse(e.title), Meta: collapse(e.meta),
				Href: e.href, PickId: e.pickID, Continued: e.continued, DayOff: e.dayOff,
			})
		}
		c.Days = append(c.Days, day)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Calendar{Calendar: c}}
}
