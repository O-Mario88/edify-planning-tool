//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The officer's quiet day this test files (a Wednesday): a sign-in on a
// phone, time on one part of the platform doing two things, a Core visit
// scheduled (two audit rows of one request, the echo written last) and a
// follow-up their Country Director sent. Removed when the test ends.
const staffActivityPersonDay = "2025-06-11"

func filePersonsDay(t *testing.T, officer, director, school string) {
	t.Helper()
	ctx := context.Background()
	t.Cleanup(func() {
		for _, sql := range []string{
			`DELETE FROM audit_log WHERE id LIKE 'gpsb%'`,
			`DELETE FROM presence_time WHERE id LIKE 'gpsb%'`,
			`DELETE FROM login_event WHERE id LIKE 'gpsb%'`,
			`DELETE FROM staff_usage_follow_up WHERE id LIKE 'gpsb%'`,
		} {
			if _, err := admin.Exec(context.Background(), sql); err != nil {
				t.Errorf("removing the test's rows: %v", err)
			}
		}
	})
	for _, sql := range []string{
		`INSERT INTO login_event (id, at, role, user_agent, user_id, active_seconds, device, last_active_at, ended_at)
VALUES ('gpsbl1', '2025-06-11 09:00+03', 'CCEO', '', $1, 900, 'mobile', '2025-06-11 09:20+03', '2025-06-11 09:30+03')`,
		`INSERT INTO presence_time (id, day, section, working_on, seconds, user_id) VALUES
('gpsbp1', '2025-06-11', 'Planning', 'Viewing Planning', 600, $1), ('gpsbp2', '2025-06-11', 'Planning', 'Scheduling a visit', 300, $1)`,
		`INSERT INTO audit_log (id, action, subject_kind, subject_id, actor_id, correlation_id, success, created_at) VALUES
('gpsba1', 'schedule_core_visit', 'School', $2, $1, 'gpsb-c1', true, '2025-06-11 09:10:00.001+03'),
('gpsba2', 'activity.scheduled', 'School', $2, $1, 'gpsb-c1', true, '2025-06-11 09:10:00.002+03')`,
		`INSERT INTO staff_usage_follow_up (id, created_at, updated_at, route, period_key, period_start, period_end, trigger, snapshot, note,
priority, due_date, status, resolution, history, assignee_id, subject_id, created_by_id)
VALUES ('gpsbf1', '2025-06-12 08:00+03', '2025-06-12 08:00+03', 'manager_to_staff', 'day', '2025-06-11', '2025-06-11', 'training', '{}', '[Go parity check]',
'normal', '2025-06-20', 'sent', '', '[]', $1, $1, $2)`,
	} {
		args := []any{officer}
		switch {
		case strings.Contains(sql, "staff_usage_follow_up"):
			args = append(args, director)
		case strings.Contains(sql, "$2"):
			args = append(args, school)
		}
		if _, err := admin.Exec(ctx, sql, args...); err != nil {
			t.Fatalf("filing the officer's day: %v", err)
		}
	}
}

func panelTexts(page *screensv1.GetPageResponse, block int) []string {
	out := []string{}
	for _, item := range page.GetBlocks()[block].GetPanel().GetItems() {
		switch {
		case item.GetHeading() != "":
			out = append(out, "# "+item.GetHeading())
		case item.GetText() != "":
			out = append(out, item.GetText())
		case item.GetRows() != nil:
			for _, r := range item.GetRows().GetRows() {
				out = append(out, r.GetLabel()+"="+r.GetValue())
			}
		case item.GetLinks() != nil:
			for _, l := range item.GetLinks().GetLinks() {
				out = append(out, "> "+l.GetText()+" "+l.GetHref())
			}
		}
	}
	return out
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestAPersonsStaffActivityDetailShowsTheirDay(t *testing.T) {
	ctx := context.Background()
	officer := userIDOf(t, "cceo@edify.org")
	director := userIDOf(t, "cd@edify.org")
	var school string
	if err := admin.QueryRow(ctx, `SELECT id FROM school ORDER BY id LIMIT 1`).Scan(&school); err != nil {
		t.Fatal(err)
	}
	var already int
	if err := admin.QueryRow(ctx, `SELECT (SELECT count(*) FROM audit_log WHERE created_at::date = $1 AND actor_id = $2)
 + (SELECT count(*) FROM login_event WHERE at::date = $1 AND user_id = $2)`, staffActivityPersonDay, officer).Scan(&already); err != nil || already != 0 {
		t.Skipf("the test database already holds the officer's day (%d, %v)", already, err)
	}
	filePersonsDay(t, officer, director, school)
	path := "/staff-activity/people/" + officer
	query := map[string]string{"on": staffActivityPersonDay}

	borrowAccount(t, "cd@edify.org")
	token := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, path, query)
	if err != nil {
		t.Fatal(err)
	}
	if page.GetWebPath() != path || len(page.GetBlocks()) != 2 {
		t.Fatalf("the detail: %v", page)
	}
	top := panelTexts(page, 0)
	for _, want := range []string{"Logins=1", "15m", "Meaningful actions=1", "Schools acted on=1",
		"> Follow up /staff-activity/people/" + officer + "/follow-up?period=day&on=2025-06-11", "×"} {
		if !contains(top, want) {
			t.Errorf("the top lacks %q: %v", want, top)
		}
	}
	quads := panelTexts(page, 1)
	for _, want := range []string{
		"1 session · Wed 11 Jun 2025",
		"> Wed 11 Jun 2025, 09:00 · Mobile Active 15m · Idle 15m · Span 30m Signed out 11/06 09:30 ",
		"2 tasks across 1 part of the platform",
		"> Planning15m1 action ",
		"1 in the period · 1 done · page views are not actions",
		"> Scheduled a core school visit /schools/" + school,
		"Signed in on 1 day · active time and actions",
		"> Wed ",
		"> Training required /staff-activity/follow-ups/gpsbf1",
	} {
		if !contains(quads, want) {
			t.Errorf("the boxes lack %q: %v", want, quads)
		}
	}

	// The Admin reads it too, without the Country Director's Follow up.
	borrowAccount(t, "admin@edify.org")
	adminToken := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	page, err = pageOf(adminToken, path, query)
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range panelTexts(page, 0) {
		if strings.Contains(line, "Follow up") {
			t.Errorf("the Admin was offered %q", line)
		}
	}

	// A refused request is named by its audit reason, which the gateway does
	// not read: the reader is passed on (unavailable with nothing behind).
	if _, err := admin.Exec(ctx, `INSERT INTO audit_log (id, action, subject_kind, actor_id, success, reason, created_at)
VALUES ('gpsba3', 'request_failed', 'Request', $1, false, 'Unhandled ValueError', '2025-06-11 09:15+03')`, officer); err != nil {
		t.Fatal(err)
	}
	if _, err := pageOf(token, path, query); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("a refused request was answered: %v", err)
	}
}

func TestAPersonsStaffActivityDetailRefusesAsThePageDoes(t *testing.T) {
	officer := userIDOf(t, "cceo@edify.org")
	director := userIDOf(t, "cd@edify.org")
	for _, c := range []struct {
		email, person string
		code          connect.Code
	}{
		{"cceo@edify.org", officer, connect.CodeNotFound},
		{"ia@edify.org", officer, connect.CodePermissionDenied},
		// Not on the country's roster: the Country Director themselves.
		{"cd@edify.org", director, connect.CodePermissionDenied},
		{"cd@edify.org", "no-such-person", connect.CodePermissionDenied},
		// A Programme Lead's team is the existing application's.
		{"pl1@edify.org", officer, connect.CodeUnavailable},
	} {
		borrowAccount(t, c.email)
		token := sessionOf(t, c.email, seededPassword).GetAccessToken()
		if _, err := pageOf(token, "/staff-activity/people/"+c.person, nil); connect.CodeOf(err) != c.code {
			t.Errorf("%s reading %s: %v, want %v", c.email, c.person, err, c.code)
		}
	}
}

func contains(lines []string, want string) bool {
	for _, l := range lines {
		if l == want {
			return true
		}
	}
	return false
}
