package todos

import (
	"context"
	"errors"
	"strconv"
	"testing"
	"time"
)

func iaReader() *reader {
	now := time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC)
	return &reader{role: roleIA, now: now, today: time.Date(2026, 11, 13, 0, 0, 0, 0, time.UTC), fy: "2027"}
}

// _ia_todos' rows: staff work opens its review workspace, partner work its
// Partner Evidence review; a submission more than a day old is critical and
// overdue; one never submitted has no due day.
func TestIAVerificationRow(t *testing.T) {
	r := iaReader()
	at := func(h int) *time.Time { v := r.now.Add(-time.Duration(h) * time.Hour); return &v }
	cases := []struct {
		name, delivery          string
		submitted               *time.Time
		title, url, prio, state string
		due                     string
	}{
		{"staff, fresh", "staff", at(2), "Verify Activity", "/ia/verification/a1/", "high", "waiting_me", "2026-11-14"},
		{"partner, fresh", "partner", at(2), "Review Partner Evidence and Confirm Salesforce", "/ia/partner-evidence/a1/", "high", "waiting_me", "2026-11-14"},
		{"staff, a day and more", "staff", at(30), "Verify Activity", "/ia/verification/a1/", "critical", "overdue", "2026-11-13"},
		{"exactly a day is not late", "staff", at(24), "Verify Activity", "/ia/verification/a1/", "high", "waiting_me", "2026-11-13"},
		{"never submitted", "staff", nil, "Verify Activity", "/ia/verification/a1/", "high", "waiting_me", ""},
	}
	for _, c := range cases {
		got := iaVerificationRow(r, "a1", "school_visit", c.delivery, c.submitted, "Kasubi PS")
		due := ""
		if got.Due != nil {
			due = got.Due.Format(time.DateOnly)
		}
		if got.Title != c.title || got.ActionURL != c.url || got.Priority != c.prio || got.StatusKey != c.state || due != c.due {
			t.Errorf("%s: %+v (due %q)", c.name, got, due)
		}
		if got.Linked != "Kasubi PS · "+typeLabel("school_visit") || got.Category != rules.IA.Category {
			t.Errorf("%s: linked %q, category %q", c.name, got.Linked, got.Category)
		}
	}
	if place(false, "", true, "Kira cluster") != "Kira cluster" || place(false, "", false, "") != "—" || place(true, "S", true, "C") != "S" {
		t.Error("place")
	}
}

// _owner_rows: eight owners by count then id, the rest folded into one low
// row, unowned schools by district (most first, ties in the order the
// groups came, no district as "No district"), names from the accounts.
func TestCollectionRows(t *testing.T) {
	r := iaReader()
	var groups []collectionGroup
	for i := 1; i <= 10; i++ {
		groups = append(groups, collectionGroup{owner: "o" + strconv.Itoa(i), n: i})
	}
	groups = append(groups,
		collectionGroup{owner: "o10", n: 1}, // a second district of o10's
		collectionGroup{n: 2, district: "d1", hasDistrict: true, districtName: "Wakiso", hasName: true},
		collectionGroup{n: 3, district: "d2", hasDistrict: true, districtName: "Mukono", hasName: true},
		collectionGroup{n: 3},
		collectionGroup{n: 1, district: "d1", hasDistrict: true, districtName: "Wakiso", hasName: true},
	)
	rows := collectionRows(r, groups, map[string]string{"o10": "Paul N.", "o9": "Staff member"})
	var titles []string
	for _, row := range rows {
		titles = append(titles, row.Title+" | "+row.ActionURL+" | "+row.Priority)
	}
	want := []string{
		"11 schools without this year's SSA · Paul N. | /ia/dashboard/?view=collection&owner=o10 | medium",
		"9 schools without this year's SSA · Staff member | /ia/dashboard/?view=collection&owner=o9 | medium",
		"8 schools without this year's SSA · an unmatched owner | /ia/dashboard/?view=collection&owner=o8 | medium",
		"7 schools without this year's SSA · an unmatched owner | /ia/dashboard/?view=collection&owner=o7 | medium",
		"6 schools without this year's SSA · an unmatched owner | /ia/dashboard/?view=collection&owner=o6 | medium",
		"5 schools without this year's SSA · an unmatched owner | /ia/dashboard/?view=collection&owner=o5 | medium",
		"4 schools without this year's SSA · an unmatched owner | /ia/dashboard/?view=collection&owner=o4 | medium",
		"3 schools without this year's SSA · an unmatched owner | /ia/dashboard/?view=collection&owner=o3 | medium",
		"3 more schools without this year's SSA | /ia/dashboard/?view=collection | low",
		"3 unowned schools without this year's SSA · Wakiso | /ia/dashboard/?view=collection&district=d1 | low",
		"3 unowned schools without this year's SSA · Mukono | /ia/dashboard/?view=collection&district=d2 | low",
		"3 unowned schools without this year's SSA · No district | /ia/dashboard/?view=collection | low",
	}
	if len(titles) != len(want) {
		t.Fatalf("%d rows: %q", len(titles), titles)
	}
	for i := range want {
		if titles[i] != want[i] {
			t.Errorf("row %d: %q, want %q", i, titles[i], want[i])
		}
	}
	if rows[0].Linked != "11 schools" || rows[0].Shape != "/ia/dashboard/?view=collection&owner={id}" || rows[0].Due == nil || !rows[0].Due.Equal(r.today) {
		t.Errorf("%+v", rows[0])
	}
	one := collectionRows(r, []collectionGroup{{owner: "x", n: 1}, {n: 1}}, nil)
	if one[0].Title != "1 school without this year's SSA · an unmatched owner" || one[1].Title != "1 unowned school without this year's SSA · No district" {
		t.Errorf("%+v", one)
	}
}

// get_operational_fy(today) of the local day: October opens the next year.
func TestLocalFY(t *testing.T) {
	for day, want := range map[string]string{"2026-09-30": "2026", "2026-10-01": "2027", "2027-01-15": "2027"} {
		d, _ := time.Parse(time.DateOnly, day)
		if got := localFY(d); got != want {
			t.Errorf("%s: %s, want %s", day, got, want)
		}
	}
}

// Only Impact Assessment is answered by the IA builders; anyone else who
// reaches them is passed on, and the builders that branch on the role keep
// the field officer's answer for everyone else.
func TestIABuildersPassOtherRolesOn(t *testing.T) {
	r := iaReader()
	r.role = "Program Lead"
	for _, name := range []string{"_ia_todos", "_cd_flag_todos", "apps.activities.ia_todos:ia_queue_todos",
		"apps.impact.framework_todos:framework_todos", "apps.impact.learning_todos:learning_todos",
		"apps.impact.report_todos:report_todos", "apps.planning.coverage_todos:missing_training_todos"} {
		if _, err := Handled[name](context.Background(), nil, r); !errors.Is(err, errPassOn) {
			t.Errorf("%s: %v, want passed on", name, err)
		}
	}
	called := ""
	b := byRole(func(context.Context, *Service, *reader) ([]todo, error) { called = "base"; return nil, nil },
		func(context.Context, *Service, *reader) ([]todo, error) { called = "ia"; return nil, nil })
	if _, _ = b(context.Background(), nil, r); called != "base" {
		t.Errorf("a lead got %s", called)
	}
	r.role = roleIA
	if _, _ = b(context.Background(), nil, r); called != "ia" {
		t.Errorf("IA got %s", called)
	}
	if !contains(rules.IA.CoverageRoles, roleIA) || !contains(rules.Roles[roleIA].Builders, "_ia_todos") {
		t.Error("the exported rules no longer give IA its builders")
	}
}
