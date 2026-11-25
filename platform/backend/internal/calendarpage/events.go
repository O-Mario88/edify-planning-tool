package calendarpage

import (
	"sort"
	"strings"
	"time"
)

// event is one entry of a day (the view's events_by_date), as far as the
// feed reads it: what kind it is, its words, its link and its tick box.
type event struct {
	kind              string
	title, meta, href string
	pick              bool
	// What the month block (PageCalendar) carries beside the words: the
	// activity's colour family, the activity it ticks, a later day of a run
	// and a day-off mark.
	family, pickID    string
	continued, dayOff bool
}

// kindOrder is the view's event_order: events, holidays, leave, work.
var kindOrder = map[string]int{"event": 0, "holiday": 1, "leave": 2, "activity": 3}

// month is the events of one month, by day, and their counts by kind.
type month struct {
	start, end time.Time
	days       map[time.Time][]event
	counts     map[string]int
	// dayOff are the activities to reschedule, in the order the page lists
	// them.
	dayOff []dayOffRow
	// A partner's calendar names who delivers each entry and lists today's
	// work on top (partner_today.html); leads is whether the reader may name
	// that person.
	partner     bool
	leads       bool
	today       time.Time
	partnerDays []todayRow
}

// todayRow is one of a partner's activities today.
type todayRow struct {
	id, title, code, place, who, stage, tone, href string
	canName                                        bool
}

type dayOffRow struct {
	date              time.Time
	title, place, why string
	href              string
}

func newMonth(start, end time.Time) *month {
	return &month{start: start, end: end, days: map[time.Time][]event{},
		counts: map[string]int{"activity": 0, "leave": 0, "holiday": 0, "event": 0}}
}

func (m *month) total() int {
	return m.counts["activity"] + m.counts["leave"] + m.counts["holiday"] + m.counts["event"]
}

// spans are the days each activity runs on: from its start to an end date
// after it.
func spans(rows []*activity) map[string]span {
	out := map[string]span{}
	for _, a := range rows {
		start := a.start()
		if start == nil {
			continue
		}
		end := *start
		if a.end != nil && a.end.After(*start) {
			end = *a.end
		}
		out[a.id] = span{start: *start, end: end}
	}
	return out
}

// addActivities is the view's activity loop: one entry for each day of the
// month an activity runs on, counted once.
func (m *month) addActivities(rows []*activity, sp map[string]span, marks map[string]dayOffMark, ticks, closed map[string]bool) {
	for _, a := range rows {
		s, ok := sp[a.id]
		if !ok {
			continue
		}
		first, last := later(s.start, m.start), earlier(s.end, m.end)
		if first.After(last) {
			continue
		}
		place, title := a.place(), a.title()
		total := int(s.end.Sub(s.start).Hours()/24) + 1
		rng := rangeLabel(s.start, s.end)
		href := "/my-plan/" + a.id
		if closed[a.id] {
			href = ""
		}
		mark, dayOff := marks[a.id]
		if dayOff {
			m.dayOff = append(m.dayOff, dayOffRow{date: mark.days[0].day, title: title, place: place, why: mark.why(), href: href})
		}
		who := strings.TrimSpace(a.contact)
		if m.partner && !s.start.After(m.today) && !s.end.Before(m.today) {
			p := rules.Partner
			stage, tone := p.ScheduledStage[0], p.ScheduledStage[1]
			if st, ok := p.Stages[a.status]; ok {
				stage, tone = st[0], st[1]
			}
			m.partnerDays = append(m.partnerDays, todayRow{id: a.id, title: title, code: a.schoolCode, place: place,
				who: who, stage: stage, tone: tone, href: href, canName: m.leads && !in(p.NotRenamedStatuses, a.status)})
		}
		m.counts["activity"]++
		for d := first; !d.After(last); d = d.AddDate(0, 0, 1) {
			meta := place
			switch {
			case total == 1:
			case d.Equal(s.start):
				meta = place + " · " + rng
			default:
				meta = place + " · Day " + itoa(int(d.Sub(s.start).Hours()/24)+1) + " of " + itoa(total)
			}
			if m.partner {
				// First: a month cell has room for a few words, and the
				// person is what this calendar is read for.
				meta = orText(who, rules.Partner.NobodyNamed) + " · " + meta
			}
			if dayOff {
				meta = "Reschedule: " + strings.ToLower(mark.label()) + " · " + meta
			}
			e := event{kind: "activity", title: title, meta: meta, href: href, pick: ticks[a.id],
				family: family(a.kind), continued: d.After(s.start), dayOff: dayOff}
			if e.pick {
				e.pickID = a.id
			}
			m.days[d] = append(m.days[d], e)
		}
	}
	sort.SliceStable(m.dayOff, func(i, j int) bool { return m.dayOff[i].date.Before(m.dayOff[j].date) })
}

// addLeave is the view's leave loop: approved leave, and the reader's own
// request still waiting, on each day of the month it covers.
func (m *month) addLeave(rows []leave, ownStaffID string) {
	for _, l := range rows {
		ownPending := l.status == "pending" && ownStaffID != "" && l.staffID == ownStaffID
		if l.status == "pending" && !ownPending {
			continue
		}
		start, okStart := isoDate(l.start)
		end, okEnd := isoDate(l.end)
		if !okStart || !okEnd {
			continue
		}
		who := "None"
		if l.name != nil {
			who = *l.name
		}
		if ownStaffID != "" && l.staffID == ownStaffID {
			who = "Your"
		}
		meta := pyTitle(strings.ReplaceAll(l.kind, "_", " "))
		if ownPending {
			meta += " · Awaiting approval"
		}
		for d := later(start, m.start); !d.After(earlier(end, m.end)); d = d.AddDate(0, 0, 1) {
			m.days[d] = append(m.days[d], event{kind: "leave", title: who + " leave", meta: meta, href: "/personal-time-off"})
			m.counts["leave"]++
		}
	}
}

// addHolidays is the view's holiday loop: each named day once per name.
func (m *month) addHolidays(days []holiday) {
	seen := map[string]bool{}
	for _, h := range days {
		key := h.date.Format(time.DateOnly) + "\x00" + casefold(strip(h.name))
		if seen[key] {
			continue
		}
		seen[key] = true
		detail := "Observance"
		if h.public {
			detail = "Public holiday"
		}
		m.days[h.date] = append(m.days[h.date], event{kind: "holiday", title: h.label(), meta: detail})
		m.counts["holiday"]++
	}
}

// addEvents is the view's organization event loop.
func (m *month) addEvents(events []orgEvent) {
	for _, e := range events {
		meta := e.description
		if meta == "" {
			meta = "Planning blocked"
		}
		for d := later(e.start, m.start); !d.After(earlier(e.end, m.end)); d = d.AddDate(0, 0, 1) {
			m.days[d] = append(m.days[d], event{kind: "event", title: e.title, meta: meta, continued: d.After(e.start)})
			m.counts["event"]++
		}
	}
}

// family is _calendar_event_family: the exported colour family of an
// activity type, "activity" for a type the vocabulary does not know.
func family(activityType string) string {
	if f, ok := rules.EventFamilies[activityType]; ok {
		return f
	}
	return "activity"
}

// sortDays puts each day's entries in the view's order: by kind, then title.
func (m *month) sortDays() {
	for _, list := range m.days {
		sort.SliceStable(list, func(i, j int) bool {
			if kindOrder[list[i].kind] != kindOrder[list[j].kind] {
				return kindOrder[list[i].kind] < kindOrder[list[j].kind]
			}
			return list[i].title < list[j].title
		})
	}
}

// agendaDays are the days of the month with entries, in order.
func (m *month) agendaDays() []time.Time {
	out := []time.Time{}
	for d := m.start; !d.After(m.end); d = d.AddDate(0, 0, 1) {
		if len(m.days[d]) > 0 {
			out = append(out, d)
		}
	}
	return out
}

// orText is text, else the fallback.
func orText(text, fallback string) string {
	if text != "" {
		return text
	}
	return fallback
}
