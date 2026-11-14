package calendarpage

import (
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func at(s string) time.Time {
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		panic(err)
	}
	return t
}

// A day picked in a drawer is saved as local midnight, which the database
// holds as 21:00 UTC the day before: the calendar draws it on the local day.
func TestTheCalendarDayIsTheLocalDay(t *testing.T) {
	for _, c := range []struct{ instant, want string }{
		{"2026-11-30T21:00:00Z", "2026-12-01"},
		{"2026-11-30T20:59:59Z", "2026-11-30"},
		{"2026-12-31T21:00:00Z", "2027-01-01"},
		{"2026-09-30T21:00:00Z", "2026-10-01"},
	} {
		if got := localDay(at(c.instant)).Format(time.DateOnly); got != c.want {
			t.Errorf("%s: %s, want %s", c.instant, got, c.want)
		}
		a := &activity{scheduled: ptr(at(c.instant))}
		if got := a.start().Format(time.DateOnly); got != c.want {
			t.Errorf("start of %s: %s, want %s", c.instant, got, c.want)
		}
	}
	planned := day(2026, 11, 3)
	if got := (&activity{planned: &planned, scheduled: ptr(at("2026-11-04T21:00:00Z"))}).start(); !got.Equal(day(2026, 11, 5)) {
		t.Errorf("a scheduled instant speaks before the planned date: %v", got)
	}
}

func ptr[T any](v T) *T { return &v }

// The month opens on today's (the local day at 21:00 UTC is tomorrow's),
// and a month or year that is not a whole number in range opens it too.
func TestTheMonthReadFromTheQuery(t *testing.T) {
	today := localDay(at("2026-12-31T21:30:00Z")) // 1 January 2027 in Kampala
	for _, c := range []struct {
		query string
		year  int
		month time.Month
	}{
		{"", 2027, 1},
		{"month=12&year=2026", 2026, 12},
		{"month=13&year=2026", 2027, 1},
		{"month=0", 2027, 1},
		{"month=abc&year=2026", 2027, 1},
		{"month=3&year=abc", 2027, 1},
		{"year=1999", 2027, 1},
		{"year=2100&month=12", 2100, 12},
		{"year=2101", 2027, 1},
		{"month= 3 &year=+2026", 2026, 3},
		{"month=1_0&year=2026", 2026, 10},
		{"month=10", 2027, 10},
	} {
		q, _ := url.ParseQuery(c.query)
		r := readRequest(q, today)
		if r.year != c.year || r.mon != c.month {
			t.Errorf("%q: %d-%d, want %d-%d", c.query, r.year, r.mon, c.year, c.month)
		}
	}
	q, _ := url.ParseQuery("status=done&activity_type=nope&event_kind=x&view=AGENDA")
	if r := readRequest(q, today); r.status != "" || r.kind != "" || r.eventKind != "all" || r.agenda {
		t.Errorf("unknown filters were kept: %+v", r)
	}
}

// The month's last day, across the year's turn and February.
func TestTheMonthEnds(t *testing.T) {
	for _, c := range []struct {
		year  int
		month time.Month
		last  int
	}{{2026, 12, 31}, {2027, 1, 31}, {2028, 2, 29}, {2026, 2, 28}, {2026, 9, 30}, {2026, 10, 31}} {
		if got := day(c.year, c.month, 1).AddDate(0, 1, -1).Day(); got != c.last {
			t.Errorf("%d-%d ends on %d, want %d", c.year, c.month, got, c.last)
		}
	}
}

func TestRangeLabels(t *testing.T) {
	for _, c := range []struct {
		a, b time.Time
		want string
	}{
		{day(2026, 8, 12), day(2026, 8, 12), "12 August 2026"},
		{day(2026, 8, 12), day(2026, 8, 14), "12–14 August 2026"},
		{day(2026, 7, 30), day(2026, 8, 2), "30 July – 2 August 2026"},
		{day(2026, 12, 30), day(2027, 1, 2), "30 December 2026 – 2 January 2027"},
	} {
		if got := rangeLabel(c.a, c.b); got != c.want {
			t.Errorf("%s, want %s", got, c.want)
		}
	}
}

// A recorded Eid replaces the expected one within a week of it; a recorded
// day takes a public holiday's place on its date; observances stay.
func TestRecordedHolidays(t *testing.T) {
	national := []holiday{
		{date: day(2027, 3, 9), name: rules.Holidays.EidAlFitr, public: true, expected: true},
		{date: day(2027, 12, 25), name: "Christmas Day", public: true},
		{date: day(2027, 12, 22), name: "December Solstice"},
	}
	for _, c := range []struct {
		title string
		want  string
	}{
		{"Idd el Fitri", rules.Holidays.EidAlFitr}, {"EID-UL-ADHA", rules.Holidays.EidAlAdha},
		{"Idd Adhuha", rules.Holidays.EidAlAdha}, {"Heroes Day", ""},
	} {
		if got := eidNamed(c.title); got != c.want {
			t.Errorf("%q names %q, want %q", c.title, got, c.want)
		}
	}
	if (holiday{name: "Eid al-Fitr", expected: true}).label() != "Eid al-Fitr (expected date)" {
		t.Error("an expected Eid does not say so")
	}
	merged := mergeYear(national, []holiday{
		{date: day(2027, 3, 10), name: "Idd el Fitri", public: true, recorded: true},
		{date: day(2027, 12, 25), name: "Christmas", public: true, recorded: true},
		{date: day(2027, 12, 22), name: "Long day", public: true, recorded: true},
	})
	names := []string{}
	for _, h := range merged {
		names = append(names, h.date.Format("01-02")+" "+h.name)
	}
	if got := strings.Join(names, ", "); got != "03-10 Idd el Fitri, 12-22 Long day, 12-22 December Solstice, 12-25 Christmas" {
		t.Errorf("merged %s", got)
	}
	if got := absDays(day(2027, 3, 16), day(2027, 3, 9)); got != 7 {
		t.Errorf("a week is %d days", got)
	}
}

// What a day-off mark says, for a holiday, leave, and both.
func TestDayOffMarks(t *testing.T) {
	holiday := dayOff{day: day(2026, 12, 25), holiday: true, name: "Christmas Day"}
	onLeave := dayOff{day: day(2026, 12, 26), name: "Paul N.", cover: "Deo M."}
	alone := dayOff{day: day(2026, 12, 27), name: "Paul N."}
	for _, c := range []struct {
		mark       dayOffMark
		label, why string
	}{
		{dayOffMark{days: []dayOff{holiday}}, "Public holiday", "Fri 25 Dec is a public holiday (Christmas Day)."},
		{dayOffMark{days: []dayOff{onLeave}}, "On leave", "Paul N. is on leave on Sat 26 Dec. Deo M. is covering."},
		{dayOffMark{days: []dayOff{holiday, alone}}, "Holiday and leave",
			"Fri 25 Dec is a public holiday (Christmas Day). Paul N. is on leave on Sun 27 Dec."},
	} {
		if c.mark.label() != c.label || c.mark.why() != c.why {
			t.Errorf("%q / %q, want %q / %q", c.mark.label(), c.mark.why(), c.label, c.why)
		}
	}
}

// A Lead's CCEO's calendar is their work and the partner work they
// monitor; each tab counts what its calendar draws.
func TestATeamMembersCalendar(t *testing.T) {
	rows := []*activity{
		{id: "a", staffID: "sp1"},
		{id: "b", staffID: "u1"},
		{id: "c", monitorID: "sp1", delivery: "partner"},
		{id: "d", monitorID: "sp1", delivery: "staff"},
		{id: "e", staffID: "sp2"},
	}
	got := planOf(rows, []string{"sp1", "u1"})
	if len(got) != 3 || got[0].id != "a" || got[1].id != "b" || got[2].id != "c" {
		t.Fatalf("the calendar of sp1: %v", got)
	}
	counts := planCounts(rows, map[string][]string{"mine": {"lead"}, "sp1": {"sp1", "u1"}, "sp2": {"sp2"}})
	if counts["mine"] != 0 || counts["sp1"] != 3 || counts["sp2"] != 1 {
		t.Fatalf("counts %v", counts)
	}
}

// The Director's strip: their own calendar, a tab for each team opening on
// its Lead, and the people of the team opened under it; every link keeps
// the month and filters, the person last.
func TestTheDirectorsStrips(t *testing.T) {
	teams := []team{
		{key: "l1", name: "Lead One's team", people: []person{{key: "l1", name: "Lead One", ids: []string{"l1"}}, {key: "c1", name: "Ann", ids: []string{"c1"}}}},
		{key: rules.NoLeadKey, name: rules.NoLeadLabel, people: []person{{key: "c2", name: "Bob", ids: []string{"c2"}}}},
	}
	rows := []*activity{{id: "a", staffID: "c1"}, {id: "b", staffID: "c2"}, {id: "c", staffID: "c1"}}
	q := params{{"year", "2026"}, {"month", "11"}, {"person", "c1"}, {"status", "scheduled"}}
	p := auth.Principal{Account: auth.Account{UserID: "u", StaffProfileID: "sp"}}
	teamTabs, members := peopleTabs(p, teams, &teams[0], &teams[0].people[1], rows, q)
	want := []tab{
		{label: "My calendar", count: 0, href: "/calendar?year=2026&month=11&status=scheduled"},
		{label: "Lead One's team", count: 2, href: "/calendar?year=2026&month=11&status=scheduled&person=l1"},
		{label: "No Programme Lead", count: 1, href: "/calendar?year=2026&month=11&status=scheduled&person=c2"},
	}
	if len(teamTabs) != len(want) {
		t.Fatalf("tabs %v", teamTabs)
	}
	for i := range want {
		if teamTabs[i] != want[i] {
			t.Errorf("tab %d: %+v, want %+v", i, teamTabs[i], want[i])
		}
	}
	if len(members) != 2 || members[1].href != "/calendar?year=2026&month=11&status=scheduled&person=c1" || members[1].count != 2 {
		t.Errorf("members %+v", members)
	}
	if _, found := find(teams, " c2 "); found == nil || found.key != "c2" {
		t.Error("a padded person is not found")
	}
	if _, found := find(teams, "zz"); found != nil {
		t.Error("a person off the strip opens their calendar")
	}
}

// A day with no link is read whole in the agenda: its date, Today, and each
// entry's words.
func TestAnAgendaDayWithNoLink(t *testing.T) {
	m := newMonth(day(2026, 10, 1), day(2026, 10, 31))
	m.days[day(2026, 10, 9)] = []event{{kind: "holiday", title: "Independence Day", meta: "Public holiday"}}
	m.days[day(2026, 10, 10)] = []event{{kind: "holiday", title: "X", meta: "Y"}, {kind: "leave", title: "Your leave", meta: "Annual Leave", href: "/personal-time-off"}}
	v := &view{m: m, today: day(2026, 10, 9)}
	if got := v.agendaLink(day(2026, 10, 9)).GetText(); got != "Friday 9 October Today Independence DayPublic holiday" {
		t.Errorf("%q", got)
	}
	if got := v.agendaLink(day(2026, 10, 10)); got.GetText() != "Your leaveAnnual Leave" || got.GetHref() != "/personal-time-off" {
		t.Errorf("%v", got)
	}
}

// A label line followed by a figure becomes a data row, consecutive rows
// share one list, and a pager's caption is never a label.
func TestPairedLines(t *testing.T) {
	it := items{}
	for _, s := range []string{"Sun", "1", "Today", "14", "Planning blocked", "15", "2", "Showing 1", "3"} {
		it.text(s)
	}
	got := paired(it)
	if len(got) != 4 || len(got[0].GetRows().GetRows()) != 3 || got[1].GetText() != "2" || got[2].GetText() != "Showing 1" {
		t.Fatalf("%v", got)
	}
}

func TestPythonTitle(t *testing.T) {
	for in, want := range map[string]string{"annual leave": "Annual Leave", "SICK leave": "Sick Leave", "they're 2nd": "They'Re 2Nd"} {
		if got := pyTitle(in); got != want {
			t.Errorf("%q: %q, want %q", in, got, want)
		}
	}
}

// Every year a month can be opened in has its national calendar.
func TestTheNationalCalendarCoversEveryYear(t *testing.T) {
	for y := rules.Years[0] - 1; y <= rules.Years[1]+1; y++ {
		if len(rules.Holidays.national[y]) == 0 {
			t.Errorf("no national calendar for %d", y)
		}
	}
}

// The month block carries what the text segments cannot: each entry's
// kind and family, the activity a tick box ticks on every day of its run,
// a later day of a run (an activity's or an organization event's), the
// day-off mark on the entry and its day, and today only within the month.
func TestTheMonthBlock(t *testing.T) {
	m := newMonth(day(2026, 11, 1), day(2026, 11, 30))
	run := &activity{id: "a1", kind: "core_visit", name: "Core Visit", hasSchool: true, schoolName: "Kimenyedde"}
	odd := &activity{id: "a2", kind: "no_such_type", name: "Other"}
	sp := map[string]span{"a1": {day(2026, 10, 31), day(2026, 11, 2)}, "a2": {day(2026, 11, 5), day(2026, 11, 5)}}
	marks := map[string]dayOffMark{"a1": {days: []dayOff{{day: day(2026, 11, 1), name: "Paul N."}}}}
	m.addActivities([]*activity{run, odd}, sp, marks, map[string]bool{"a1": true}, map[string]bool{})
	m.addEvents([]orgEvent{{title: "Retreat", start: day(2026, 11, 2), end: day(2026, 11, 3)}})
	m.sortDays()
	v := &view{year: 2026, mon: time.November, m: m, today: day(2026, 12, 1), eventKind: "leave"}
	c := v.calendar().GetCalendar()
	if c.GetToday() != "" || c.GetKind() != "leave" || c.GetYear() != 2026 || c.GetMonth() != 11 {
		t.Fatalf("%v", c)
	}
	if k := c.GetKinds(); len(k) != 5 || k[0].GetValue() != "all" || k[0].GetCount() != "4" || k[1].GetCount() != "2" || k[4].GetCount() != "2" {
		t.Errorf("kinds %v", k)
	}
	days := c.GetDays()
	if len(days) != 4 || days[0].GetDate() != "2026-11-01" || !days[0].GetDayOff() {
		t.Fatalf("days %v", days)
	}
	first := days[0].GetEvents()[0]
	if first.GetFamily() != "core" || first.GetPickId() != "a1" || !first.GetContinued() || !first.GetDayOff() || first.GetHref() != "/my-plan/a1" {
		t.Errorf("first %v", first)
	}
	second := days[1].GetEvents()
	if len(second) != 2 || second[0].GetKind() != "event" || second[0].GetContinued() || second[0].GetFamily() != "" {
		t.Errorf("2 Nov %v", second)
	}
	if e := days[2].GetEvents()[0]; e.GetKind() != "event" || !e.GetContinued() {
		t.Errorf("3 Nov %v", e)
	}
	if e := days[3].GetEvents()[0]; e.GetFamily() != "activity" || e.GetPickId() != "" || e.GetContinued() || e.GetDayOff() {
		t.Errorf("5 Nov %v", e)
	}
	v.today = day(2026, 11, 5)
	if c := v.calendar().GetCalendar(); c.GetToday() != "2026-11-05" || !c.GetDays()[3].GetToday() || c.GetDays()[0].GetToday() {
		t.Errorf("today %v", c)
	}
}
