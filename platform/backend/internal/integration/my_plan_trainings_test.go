//go:build integration

package integration

import (
	"context"
	"strconv"
	"strings"
	"testing"
	"time"
)

// A group training at a cluster, owned by a reader who holds nothing else,
// is Go's (40-my-plan-rest, piece 3e): once on Group Trainings, and on
// Trainings once a member school it reached.
func TestMyPlanDrawsAGroupTrainingOnceAndOnceASchoolItReached(t *testing.T) {
	ctx := context.Background()
	var staffID string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'ia@edify.org'`).Scan(&staffID); err != nil {
		t.Skipf("no staff profile: %v", err)
	}
	// A cluster with live members and no Core School among them (a Core
	// School's row is still the existing application's).
	var clusterID, clusterName string
	var members int
	if err := admin.QueryRow(ctx, `SELECT c.id, c.name, count(s.id) FROM cluster c JOIN school s ON s.cluster_id = c.id AND s.deleted_at IS NULL
WHERE c.deleted_at IS NULL GROUP BY c.id, c.name
HAVING count(s.id) BETWEEN 1 AND 40 AND count(s.id) FILTER (WHERE s.school_type = 'core') = 0 ORDER BY c.id LIMIT 1`).
		Scan(&clusterID, &clusterName, &members); err != nil {
		t.Skipf("no cluster without a Core School: %v", err)
	}
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/my-plan", nil); err != nil {
		t.Skipf("the seeded Impact Assessment account holds work here: %v", err)
	}
	now := time.Now().In(time.FixedZone("EAT", 3*3600))
	fy := now.Year()
	if now.Month() >= time.October {
		fy++
	}
	id := "goparitymyplantraining"
	if _, err := admin.Exec(ctx, `INSERT INTO activity (created_at, updated_at, id, activity_type, fy, quarter, delivery_type,
  status, evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents, cost_missing,
  environment, source, secondary_focus_interventions, attended_school_ids, ssa_collection_expected, override_reason,
  recommendation_reason, recommendation_source, activity_context_type, planning_source, support_rationale, venue,
  executor_type, driver_reason, primary_driver_id, primary_driver_type, delivery_contact_name, approval_owner_id,
  owner_decision_note, visit_justification, ssa_alignment, ssa_deviation_reason, partner_date_set_by, meeting_kind,
  responsible_staff_id, cluster_id, planned_date, activity_purpose_text)
VALUES (now(), now(), $1, 'cluster_training', $2, 'Q1', 'staff', 'scheduled', 'none', 'none', 'none', 0, 0, false, 'development',
  'goparity', '{}', '{}', false, '', '', '{}', '', '', '', '', 'staff', '', '', '', '', '', '', '', '', '', '', '',
  $3, $4, $5::date, '[Go parity check] My Plan trainings')`,
		id, strconv.Itoa(fy), staffID, clusterID, now.AddDate(0, 0, 3).Format(time.DateOnly)); err != nil {
		t.Fatalf("filing the training: %v", err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM activity WHERE id = $1`, id); err != nil {
			t.Errorf("removing the training: %v", err)
		}
	})
	page, err := pageOf(token, "/my-plan", nil)
	if err != nil {
		t.Fatalf("a page with a group training: %v", err)
	}
	group, reached := 0, 0
	for _, block := range page.GetBlocks() {
		table := block.GetTable()
		switch {
		case strings.HasPrefix(table.GetTitle(), "Group Trainings Planned for "):
			for _, row := range table.GetRows() {
				if row.GetPickId() == id && row.GetCells()[0].GetText() == clusterName &&
					row.GetCells()[0].GetHref() == "/clusters/"+clusterID {
					group++
				}
			}
		case strings.HasPrefix(table.GetTitle(), "Trainings Planned for "):
			for _, row := range table.GetRows() {
				if row.GetPickId() == id && row.GetCells()[4].GetText() == clusterName+" Invited" {
					reached++
				}
			}
		}
	}
	// Every member, or the confirmed ones when any is.
	if group != 1 || reached < 1 || reached > members {
		t.Fatalf("group rows %d (want 1), reached rows %d (of %d members): %v", group, reached, members, page.GetBlocks())
	}
}
