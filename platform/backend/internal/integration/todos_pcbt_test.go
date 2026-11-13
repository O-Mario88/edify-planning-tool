//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
)

// The Project Coordinator's and Business Transformation's queues
// (docs/migration/58-todos-pc-bto.md): Go answers both. The coordinator's
// carries the Dashboard strip and a row for each newly enrolled school with
// no project work planned there, while its project is open; a
// Business Transformation officer gets the financing gap row, and is passed
// on while a new loan purpose
// waits for review (a section Go does not build).
func TestTodosAnswerTheCoordinatorAndBusinessTransformation(t *testing.T) {
	ctx := context.Background()
	ask := func(t *testing.T, token string) (string, error) {
		t.Helper()
		page, err := pageOf(token, "/todos", nil)
		if err != nil {
			return "", err
		}
		raw, err := protojson.Marshal(page)
		return string(raw), err
	}

	t.Run("coordinator", func(t *testing.T) {
		const who = "coordinator@edify.org"
		borrowAccount(t, who)
		token := sessionOf(t, who, seededPassword).GetAccessToken()
		got, err := ask(t, token)
		if err != nil {
			t.Fatalf("the coordinator's queue: %v", err)
		}
		if !strings.Contains(got, "Dashboard") || !strings.Contains(got, "/dashboard?view=today") {
			t.Errorf("the Dashboard strip is missing: %.600s", got)
		}
		const title = "Plan Activities for Newly Added Project School"
		if !strings.Contains(got, title) {
			t.Skipf("the integration seed gives the coordinator no school to plan")
		}
		// Pause every project the coordinator runs: a project that is no
		// longer open asks for nothing, and the rows go.
		var staffID string
		if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = $1`, who).
			Scan(&staffID); err != nil {
			t.Fatal(err)
		}
		mine := `SELECT p.id FROM project p WHERE p.manager_staff_id = $1
  OR EXISTS (SELECT 1 FROM project_staff_assignment a WHERE a.project_id = p.id AND a.staff_id = $1 AND a.is_active)`
		rows, err := admin.Query(ctx, `SELECT id, status FROM project WHERE id IN (`+mine+`)`, staffID)
		if err != nil {
			t.Fatal(err)
		}
		was := map[string]string{}
		for rows.Next() {
			var id, status string
			if err := rows.Scan(&id, &status); err != nil {
				t.Fatal(err)
			}
			was[id] = status
		}
		rows.Close()
		t.Cleanup(func() {
			for id, status := range was {
				_, _ = admin.Exec(context.Background(), `UPDATE project SET status = $2 WHERE id = $1`, id, status)
			}
		})
		if _, err := admin.Exec(ctx, `UPDATE project SET status = 'paused' WHERE id IN (`+mine+`)`, staffID); err != nil {
			t.Fatal(err)
		}
		if got, err = ask(t, token); err != nil {
			t.Fatalf("with every project paused: %v", err)
		}
		if strings.Contains(got, title) {
			t.Errorf("a paused project still asks for planning: %.600s", got)
		}
	})

	t.Run("business transformation", func(t *testing.T) {
		const who = "business-transformation@edify.org"
		borrowAccount(t, who)
		token := sessionOf(t, who, seededPassword).GetAccessToken()
		got, err := ask(t, token)
		if err != nil {
			t.Fatalf("the officer's queue: %v", err)
		}
		// The integration seed has no loan, so every district with operating
		// schools is a financing gap: one row (700 schools in Mukono, as the
		// existing builder answers over this database).
		if !strings.Contains(got, "Review Geographic Financing Gap") || !strings.Contains(got, "eligible schools") {
			t.Errorf("the financing gap row is missing: %.600s", got)
		}
		_, err = admin.Exec(ctx, `INSERT INTO bt_loan_purpose_proposal (id, created_at, updated_at, proposed_code, proposed_label, proposed_is_edtech,
  rationale, status, requested_by, review_note, description, example_loan_reference, expected_impact, expected_outputs, required_evidence,
  unit_of_measure, impact_indicators, verification_method)
VALUES ('gtbt-purpose-1', now(), now(), 'gtbt', '[Go parity check]', false, '', 'requested', 'someone', '', '', '', '', '[]', '[]', '', '[]', '')`)
		t.Cleanup(func() {
			_, _ = admin.Exec(context.Background(), `DELETE FROM bt_loan_purpose_proposal WHERE id = 'gtbt-purpose-1'`)
		})
		if err != nil {
			t.Fatal(err)
		}
		if _, err := ask(t, token); connect.CodeOf(err) != connect.CodeUnavailable {
			t.Fatalf("with a loan purpose to review: %v, want it passed to the existing application", err)
		}
	})
}
