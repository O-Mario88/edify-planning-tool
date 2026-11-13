//go:build integration

package integration

import (
	"context"
	"errors"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The officer's day the test files: a sign-in, active time in two parts of
// the platform, a Core visit scheduled (two audit rows of one request, the
// echo written last) and a refused request. Removed when the test ends.
const staffActivityDay = "2025-06-10" // a Tuesday

func fileOfficersDay(t *testing.T, user, school string) {
	t.Helper()
	ctx := context.Background()
	t.Cleanup(func() {
		for _, sql := range []string{
			`DELETE FROM audit_log WHERE id LIKE 'gpsa%'`,
			`DELETE FROM presence_time WHERE id LIKE 'gpsa%'`,
			`DELETE FROM login_event WHERE id LIKE 'gpsa%'`,
		} {
			if _, err := admin.Exec(context.Background(), sql); err != nil {
				t.Errorf("removing the test's rows: %v", err)
			}
		}
	})
	for _, sql := range []string{
		`INSERT INTO login_event (id, at, role, user_agent, user_id, active_seconds, device, last_active_at)
VALUES ('gpsal1', '2025-06-10 09:00+03', 'CCEO', '', $1, 0, 'mobile', '2025-06-10 11:00+03')`,
		`INSERT INTO presence_time (id, day, section, working_on, seconds, user_id) VALUES
('gpsap1', '2025-06-10', 'My Plan', 'Viewing My Plan', 600, $1), ('gpsap2', '2025-06-10', 'Planning', 'Viewing Planning', 300, $1)`,
		`INSERT INTO audit_log (id, action, subject_kind, subject_id, actor_id, correlation_id, success, created_at) VALUES
('gpsaa1', 'schedule_core_visit', 'School', $2, $1, 'gpsa-c1', true, '2025-06-10 10:00:00.001+03'),
('gpsaa2', 'activity.scheduled', 'School', $2, $1, 'gpsa-c1', true, '2025-06-10 10:00:00.002+03'),
('gpsaa3', 'request_failed', 'Request', NULL, $1, 'gpsa-c2', false, '2025-06-10 10:30+03')`,
	} {
		args := []any{user}
		if strings.Contains(sql, "$2") {
			args = append(args, school)
		}
		if _, err := admin.Exec(ctx, sql, args...); err != nil {
			t.Fatalf("filing the officer's day: %v", err)
		}
	}
}

func officerRow(t *testing.T, page *screensv1.GetPageResponse) []string {
	t.Helper()
	for _, b := range page.GetBlocks() {
		if table := b.GetTable(); table != nil {
			rows := table.GetRows()
			if len(rows) < 2 {
				t.Fatalf("the table: %v", rows)
			}
			cells := []string{}
			for _, c := range rows[1].GetCells() {
				cells = append(cells, c.GetText())
			}
			return cells
		}
	}
	t.Fatal("no table")
	return nil
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTheStaffActivityLogCountsAnOfficersDay(t *testing.T) {
	officer := userIDOf(t, "cceo@edify.org")
	var name, school string
	if err := admin.QueryRow(context.Background(), `SELECT name FROM "user" WHERE id = $1`, officer).Scan(&name); err != nil {
		t.Fatal(err)
	}
	if err := admin.QueryRow(context.Background(), `SELECT id FROM school ORDER BY id LIMIT 1`).Scan(&school); err != nil {
		t.Fatal(err)
	}
	var already int
	if err := admin.QueryRow(context.Background(), `SELECT count(*) FROM audit_log WHERE created_at::date = $1 AND actor_id = $2`,
		staffActivityDay, officer).Scan(&already); err != nil || already != 0 {
		t.Skipf("the test database already holds the officer's actions that day (%d, %v)", already, err)
	}
	fileOfficersDay(t, officer, school)

	borrowAccount(t, "cd@edify.org")
	token := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/staff-activity", map[string]string{"on": staffActivityDay, "q": name})
	if err != nil {
		t.Fatal(err)
	}
	if page.GetHeader().GetTitle() != "Staff Activity Log" || len(page.GetHeader().GetActions()) != 1 {
		t.Fatalf("the header: %v", page.GetHeader())
	}
	cells := officerRow(t, page)
	want := map[int]string{
		1: "", 5: "1", 6: "10/06 09:00", 8: "15m", 9: "1 · 1 failed", 10: "1",
		12: "Scheduled a core school visit · 10/06 10:00", 13: "Normal",
	}
	for i, w := range want {
		if i == 1 {
			if !strings.HasSuffix(cells[1], " "+name) {
				t.Errorf("the name cell %q", cells[1])
			}
			continue
		}
		if cells[i] != w {
			t.Errorf("cell %d: %q, want %q (%v)", i, cells[i], w, cells)
		}
	}
	strip := page.GetBlocks()[0].GetStrip().GetMetrics()
	if strip[5].GetValue() != "1" || strip[5].GetHelper() != "1 school acted on" {
		t.Errorf("Meaningful Actions: %v", strip[5])
	}
	insights := page.GetBlocks()[4].GetPanel().GetItems()
	last := insights[len(insights)-1].GetLinks().GetLinks()
	if len(last) != 3 || last[1].GetText() != "100% Mobile" {
		t.Errorf("the devices: %v", last)
	}

	// A hand-over names its school only in its payload, which the gateway
	// may not read: the reader is passed on, and with nothing behind this
	// gateway the page is unavailable rather than wrong.
	if _, err := admin.Exec(context.Background(), `INSERT INTO audit_log (id, action, subject_kind, subject_id, actor_id, success, created_at)
VALUES ('gpsaa4', 'partner.assigned', 'PartnerAssignment', 'gpsa-pa', $1, true, '2025-06-10 12:00+03')`, officer); err != nil {
		t.Fatal(err)
	}
	if _, err := pageOf(token, "/staff-activity", map[string]string{"on": staffActivityDay}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("a payload-named school was answered: %v", err)
	}
}

func TestTheStaffActivityLogSendsAndRefusesAsThePageDoes(t *testing.T) {
	for _, c := range []struct {
		email string
		code  connect.Code
	}{
		{"cceo@edify.org", connect.CodeNotFound},
		{"ia@edify.org", connect.CodePermissionDenied},
	} {
		borrowAccount(t, c.email)
		token := sessionOf(t, c.email, seededPassword).GetAccessToken()
		_, err := pageOf(token, "/staff-activity", nil)
		var ce *connect.Error
		if !errors.As(err, &ce) || ce.Code() != c.code {
			t.Errorf("%s: %v, want %v", c.email, err, c.code)
		}
	}
	borrowAccount(t, "pl1@edify.org")
	token := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/staff-activity", map[string]string{"period": "week"})
	if err != nil || page.GetRedirect() != "/dashboard?sa=period%3Dweek#staff-activity" {
		t.Fatalf("a Programme Lead: %v %v", page.GetRedirect(), err)
	}
}
