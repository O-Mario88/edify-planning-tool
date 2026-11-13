//go:build integration

package integration

import (
	"context"
	"strconv"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
)

// The Programme Lead's queue (docs/migration/55-todos-pl.md): Go answers a
// lead with no portfolio, with a row for each officer whose one-to-one this
// month is still to hold (from the tenth) and each review past its date; a
// one-to-one held this month takes its officer's row away; coaching the
// lead wrote passes the lead on.
func TestTodosAnswerAProgrammeLeadsQueue(t *testing.T) {
	ctx := context.Background()
	const lead = "pl2@edify.org"
	leadID := userIDOf(t, lead)
	var leadProfile, officer, officerName string
	if err := admin.QueryRow(ctx, `SELECT sp.id, o.id, ou.name FROM staff_profile sp
JOIN staff_supervisor_assignment a ON a.supervisor_id = sp.id JOIN staff_profile o ON o.id = a.supervisee_id
JOIN "user" ou ON ou.id = o.user_id WHERE sp.user_id = $1 AND ou.active_role = 'CCEO' ORDER BY ou.name LIMIT 1`, leadID).
		Scan(&leadProfile, &officer, &officerName); err != nil {
		t.Fatal(err)
	}
	borrowAccount(t, lead)
	token := sessionOf(t, lead, seededPassword).GetAccessToken()
	ask := func() (string, error) {
		page, err := pageOf(token, "/todos", nil)
		if err != nil {
			return "", err
		}
		raw, err := protojson.Marshal(page)
		return string(raw), err
	}
	local := time.Now().In(time.FixedZone("EAT", 3*3600))
	oneToOne := "Hold " + local.Format("January") + " one-to-one with " + officerName
	overdue := "Complete " + officerName + "'s overdue performance review"

	got, err := ask()
	if err != nil {
		t.Fatalf("the lead's queue: %v", err)
	}
	if want := local.Day() >= 10; strings.Contains(got, oneToOne) != want {
		t.Errorf("one-to-one row present = %v on day %d", !want, local.Day())
	}

	fy := local.Year()
	if local.Month() >= time.October {
		fy++
	}
	_, err = admin.Exec(ctx, `INSERT INTO hr_performance_review (id, created_at, updated_at, staff_id, period, fy, review_type, stage, status, due_date, score)
VALUES ('gtpl-review-1', now(), now(), $1, 'Q1', $2, 'quarterly', 'not_started', '[Go parity check]', $3, 0)`,
		officer, strconv.Itoa(fy), local.AddDate(0, 0, -3).Format("2006-01-02"))
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `DELETE FROM hr_performance_review WHERE id = 'gtpl-review-1'`)
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = admin.Exec(ctx, `INSERT INTO cce_cceo_coaching (id, created_at, updated_at, author_id, cceo_staff_id, cceo_user_id, kind, held_on, fy, country, subject,
  strengths, growth_areas, agreed_actions, cceo_response, follow_up_note)
SELECT 'gtpl-coach-1', now(), now(), 'someone-else', $1::varchar, o.user_id, 'one_to_one', $2, $3, '', '[Go parity check]', '', '', '', '', '' FROM staff_profile o WHERE o.id = $1::varchar`,
		officer, local.Format("2006-01-02"), strconv.Itoa(fy))
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `DELETE FROM cce_cceo_coaching WHERE id LIKE 'gtpl-coach-%'`)
	})
	if err != nil {
		t.Fatal(err)
	}
	if got, err = ask(); err != nil {
		t.Fatalf("with a late review and a held one-to-one: %v", err)
	}
	if !strings.Contains(got, overdue) || strings.Contains(got, oneToOne) {
		t.Errorf("want the overdue review and no one-to-one row for %s: %s", officerName, got)
	}

	if _, err := admin.Exec(ctx, `UPDATE cce_cceo_coaching SET author_id = $1 WHERE id = 'gtpl-coach-1'`, leadID); err != nil {
		t.Fatal(err)
	}
	if _, err := ask(); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("with coaching the lead wrote: %v, want it passed to the existing application", err)
	}
}
