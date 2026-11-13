package staffactivity

import (
	"net/url"
	"testing"
	"time"
)

// The strip is held to the page's own rendering of the exported samples
// (components/context_metrics.html read by the feed).
func TestTheStripReadsAsThePageDrawsIt(t *testing.T) {
	for i, sample := range rules.StripSamples {
		n := func(key string) int { return int(sample.KPIs[key].(float64)) }
		k := kpis{
			expected: n("staff_expected"), total: n("staff_total"), active: n("staff_active"), noLogin: n("no_login"),
			totalLabel: sample.KPIs["total_active_label"].(string), medianLabel: sample.KPIs["median_active_label"].(string),
			actions: n("meaningful_actions"), schools: n("schools"), openFollowUps: n("open_follow_ups"), suggested: n("suggested"),
		}
		if v, ok := sample.KPIs["active_share"].(float64); ok {
			s := int(v)
			k.activeShare = &s
		}
		got := stripBlock(k).GetStrip()
		if got.GetTitle() != sample.Strip.Title || len(got.GetMetrics()) != len(sample.Strip.Metrics) {
			t.Fatalf("sample %d: %v", i, got)
		}
		for j, want := range sample.Strip.Metrics {
			m := got.GetMetrics()[j]
			if m.GetLabel() != want.Label || m.GetValue() != want.Value || m.GetHelper() != want.Helper ||
				m.GetNote() != want.Note || m.GetTone() != want.Tone || m.GetHref() != want.Href {
				t.Errorf("sample %d figure %d: got %v, want %+v", i, j, m, want)
			}
		}
	}
}

func TestPeriodsAreThePresencePeriods(t *testing.T) {
	today := civil(2026, time.November, 13)
	for _, c := range []struct{ key, on, label, start, end string }{
		{"", "", "today", "2026-11-13", "2026-11-13"},
		{"day", "2026-11-01", "Sun 1 Nov 2026", "2026-11-01", "2026-11-01"},
		{"nonsense", "garbage", "today", "2026-11-13", "2026-11-13"},
		{"week", "", "week of 9–15 Nov 2026", "2026-11-09", "2026-11-15"},
		{"week", "2026-12-01", "week of 30 Nov – 6 Dec 2026", "2026-11-30", "2026-12-06"},
		{"week", "2026-12-30", "week of 28 Dec 2026 – 3 Jan 2027", "2026-12-28", "2027-01-03"},
		{"month", "2026-02-10", "February 2026", "2026-02-01", "2026-02-28"},
		{"quarter", "", "Q1 FY2027 (Oct 2026 – Dec 2026)", "2026-10-01", "2026-12-31"},
		{"quarter", "2026-05-05", "Q3 FY2026 (Apr 2026 – Jun 2026)", "2026-04-01", "2026-06-30"},
		{"fy", "", "FY2027 (Oct 2026 – Sep 2027)", "2026-10-01", "2027-09-30"},
		{"day", " 20261112 ", "Thu 12 Nov 2026", "2026-11-12", "2026-11-12"},
		{"day", "2026-W46-4", "Thu 12 Nov 2026", "2026-11-12", "2026-11-12"},
		{"day", "2026W46", "Mon 9 Nov 2026", "2026-11-09", "2026-11-09"},
		{"day", "2026-W46-8", "today", "2026-11-13", "2026-11-13"},
		{"day", "2026W46-4", "today", "2026-11-13", "2026-11-13"},
		{"day", "2026-02-30", "today", "2026-11-13", "2026-11-13"},
		{"day", "2020-W53", "Mon 28 Dec 2020", "2020-12-28", "2020-12-28"},
		{"day", "2026-W53", "Mon 28 Dec 2026", "2026-12-28", "2026-12-28"},
		{"day", "2027-W53", "today", "2026-11-13", "2026-11-13"},
	} {
		p := choosePeriod(c.key, c.on, today)
		if p.label != c.label || p.start.Format(time.DateOnly) != c.start || p.end.Format(time.DateOnly) != c.end {
			t.Errorf("%q %q: %q %s..%s", c.key, c.on, p.label, p.start.Format(time.DateOnly), p.end.Format(time.DateOnly))
		}
	}
	if p := choosePeriod("week", "", today); !p.elapsed.Equal(today) || p.isFuture {
		t.Errorf("a week read on its Friday is judged to Friday: %v", p.elapsed)
	}
	if p := choosePeriod("day", "2026-11-20", today); !p.isFuture {
		t.Error("a day still to come is in the future")
	}
}

func TestDurationsAndClocks(t *testing.T) {
	for _, c := range []struct {
		s    float64
		want string
	}{{0, "0m"}, {1, "<1m"}, {59, "<1m"}, {60, "1m"}, {3599, "59m"}, {3600, "1h 00m"}, {45.5, "<1m"}, {90061, "25h 01m"}} {
		if got := minutes(c.s); got != c.want {
			t.Errorf("minutes(%v) = %q, want %q", c.s, got, c.want)
		}
	}
	today := civil(2026, time.November, 13)
	at := time.Date(2026, 11, 12, 22, 5, 0, 0, time.UTC) // 01:05 on the 13th in Nairobi
	if got := clock(&at, today); got != "01:05" {
		t.Errorf("clock = %q", got)
	}
	before := time.Date(2026, 11, 12, 20, 5, 0, 0, time.UTC)
	if got := clock(&before, today); got != "12/11 23:05" {
		t.Errorf("clock = %q", got)
	}
	if clock(nil, today) != "—" {
		t.Error("no time is a dash")
	}
}

func TestSectionsAreThePresenceLabels(t *testing.T) {
	for _, c := range []struct{ path, want string }{
		{"/", "Dashboard"},
		{"/my-plan", "My Plan"},
		{"/my-plan/past-due?x=1", "My Plan"},
		{"/partners/p1", "Partners"},
		{"/partner-oversight", "Partner Oversight"},
		{"/some-new_page/x", "Some New Page"},
		{"/abc1def", "Abc1Def"},
		{"https://example.org/todos/", "To-Do"},
	} {
		if got := sectionFor(c.path); got != c.want {
			t.Errorf("sectionFor(%q) = %q, want %q", c.path, got, c.want)
		}
	}
	for path, want := range map[string]bool{"/sw.js": true, "/api/x": true, "/staff-activity/beat": true, "/schools/x": false, "/a.b/c": false} {
		if untracked(path) != want {
			t.Errorf("untracked(%q) != %v", path, want)
		}
	}
}

func TestUsageIsJudgedAgainstTheRole(t *testing.T) {
	week := choosePeriod("week", "", civil(2026, time.November, 13)) // five working days so far
	people := []*person{
		{role: "CCEO", logins: 1, seconds: 600, expected: 5, actions: 1},
		{role: "CCEO", logins: 1, seconds: 600, expected: 5, actions: 1},
		{role: "CCEO", logins: 1, seconds: 700, expected: 5, actions: 1},
		{role: "CCEO", logins: 1, seconds: 8000, expected: 5, actions: 1},
		{role: "CCEO", logins: 0, seconds: 0, expected: 5},
		{role: "CCEO", logins: 2, seconds: 60, expected: 5, actions: 0},
		{role: "CCEO", logins: 2, seconds: 60, expected: 2, actions: 0},
		{role: "CCEO", logins: 2, seconds: 60, expected: 5, actions: 3, failed: 3},
		{role: "CCEO", expected: 0, leaveDays: 2},
		{role: "CCEO", expected: 0},
	}
	judgeUsage(people, week)
	want := []string{"normal", "normal", "normal", "follow_up", "no_login", "follow_up", "normal", "follow_up", "on_leave", "not_expected"}
	for i, w := range want {
		if people[i].usageKey != w {
			t.Errorf("person %d: %s, want %s", i, people[i].usageKey, w)
		}
	}
	future := []*person{{role: "CCEO", expected: 5}}
	judgeUsage(future, choosePeriod("day", "2026-11-20", civil(2026, time.November, 13)))
	if future[0].usageLabel != "Not yet" {
		t.Errorf("a day to come: %s", future[0].usageLabel)
	}
}

func TestGroupsFollowTheProgrammeLeads(t *testing.T) {
	pl := &person{id: "pl", name: "Zed Lead", role: "Program Lead", status: "online", seconds: 120, actions: 1}
	a := &person{id: "a", name: "Amy", role: "CCEO", lead: &lead{"pl", "Zed Lead"}, usageKey: "no_login"}
	b := &person{id: "b", name: "Bob", role: "CCEO", lead: &lead{"pl2", "Ann Lead"}, actions: 2}
	c := &person{id: "c", name: "Cy", role: "CCEO"}
	gs := groups([]*person{a, pl, b, c})
	if len(gs) != 3 || gs[0].label != "Ann Lead" || gs[1].label != "Zed Lead" || gs[2].kind != "cceo" {
		t.Fatalf("groups: %+v", gs)
	}
	if g := gs[1]; g.lead != pl || g.total != 2 || g.online != 1 || g.noLogin != 1 || g.actions != 1 {
		t.Errorf("Zed's group: %+v", g)
	}
	if gs[0].actions != 2 || plural(gs[0].actions) != "s" || plural(1) != "" {
		t.Errorf("Ann's group: %+v", gs[0])
	}
}

func TestAProgrammeLeadIsSentToTheirDashboard(t *testing.T) {
	for _, c := range []struct {
		q    url.Values
		want string
	}{
		{url.Values{}, "/dashboard#staff-activity"},
		{url.Values{"period": {"week"}}, "/dashboard?sa=period%3Dweek#staff-activity"},
		{url.Values{"fy": {"2026"}, "period": {"fy"}}, "/dashboard?fy=2026&sa=fy%3D2026%26period%3Dfy#staff-activity"},
		{url.Values{"q": {"a b"}, "export": {"1"}}, "/dashboard?sa=q%3Da%2Bb#staff-activity"},
	} {
		if got := toDashboard(c.q); got != c.want {
			t.Errorf("%v: %q, want %q", c.q, got, c.want)
		}
	}
}

func TestInitialsAndSlugs(t *testing.T) {
	for name, want := range map[string]string{"Deo M.": "DM", "o'neil smith": "OS", "": "?", "9 Lives": "L", "Ruth": "R"} {
		if got := initials(name); got != want {
			t.Errorf("initials(%q) = %q, want %q", name, got, want)
		}
	}
	if slug("Follow-up Queue 3") != "follow_up_queue_3" {
		t.Error(slug("Follow-up Queue 3"))
	}
}

func TestFiguresCountTheListedRows(t *testing.T) {
	people := []*person{
		{expected: 2, logins: 1, seconds: 100, actions: 2, schoolIDs: map[string]bool{"s1": true, "s2": true}},
		{expected: 2, usageKey: "no_login", suggestions: 1},
		{expected: 0, logins: 1, seconds: 30, schoolIDs: map[string]bool{"s1": true}, openFollowUps: 1, suggestions: 1},
		{expected: 1, seconds: 31, actions: 1},
	}
	k := figures(people)
	if k.expected != 3 || k.active != 3 || *k.activeShare != 67 || k.noLogin != 1 || k.schools != 2 ||
		k.suggested != 1 || k.openFollowUps != 1 || k.totalLabel != "2m" || k.medianLabel != "<1m" || k.actions != 3 {
		t.Errorf("%+v", k)
	}
	if share(1, 8) != 12 || share(5, 8) != 62 || share(3, 8) != 38 {
		t.Error("shares are rounded half to even")
	}
}
