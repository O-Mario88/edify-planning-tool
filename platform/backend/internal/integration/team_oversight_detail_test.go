//go:build integration

package integration

import (
	"context"
	"net/http"
	"strconv"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// The Team Plan's record drawer is Go's for the team's own work: its risks,
// ownership, planning, cost and workflow; a record outside
// the lens or gone is "Not available"; a role without either oversight page
// is refused; the Regional Programme Lead's region lens is handed on.
func TestTeamOversightDetailIsGos(t *testing.T) {
	ctx := context.Background()
	var staffID string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'cceo@edify.org'`).Scan(&staffID); err != nil {
		t.Fatal(err)
	}
	day := time.Now().AddDate(0, 0, 30)
	fy := day.Year()
	if day.Month() >= time.October {
		fy++
	}
	const id = "gotpodetail1"
	if _, err := admin.Exec(ctx, `INSERT INTO activity (created_at, updated_at, id, activity_type, fy, quarter, delivery_type,
  status, evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents, cost_missing,
  environment, source, secondary_focus_interventions, attended_school_ids, ssa_collection_expected, override_reason,
  recommendation_reason, recommendation_source, activity_context_type, planning_source, support_rationale, venue,
  executor_type, driver_reason, primary_driver_id, primary_driver_type, delivery_contact_name, approval_owner_id,
  owner_decision_note, visit_justification, ssa_alignment, ssa_deviation_reason, partner_date_set_by, meeting_kind,
  responsible_staff_id, planned_date, activity_purpose_text)
VALUES (now(), now(), $1, 'school_visit', $2, '', 'staff', 'scheduled', 'none', 'pending', 'none', 0, 50000, false, 'development',
  'goparity', '{}', '{}', false, '', '', '{}', '', '', '', '', 'staff', '', '', '', '', '', '', '', '', '', '', '',
  $3, $4::date, '[Go parity check] the record drawer')`, id, strconv.Itoa(fy), staffID, day.Format("2006-01-02")); err != nil {
		t.Fatalf("filing the activity: %v", err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM activity WHERE id = $1`, id); err != nil {
			t.Errorf("removing the activity: %v", err)
		}
	})
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	open := func(token, path string) (*screensv1.GetDrawerResponse, error) {
		answer, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, token))
		if err != nil {
			return nil, err
		}
		return answer.Msg, nil
	}
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	answer, err := open(lead, "/team-planning-oversight/detail?activity_id="+id)
	if err != nil {
		t.Fatalf("the record: %v", err)
	}
	d := answer.GetDrawer()
	headings := []string{}
	for _, it := range d.GetItems() {
		if h := it.GetHeading(); h != "" {
			headings = append(headings, h)
		}
	}
	if d.GetTitle() != "School visit" || d.GetSubtitle() != "No context" || len(headings) != 4 || headings[2] != "Cost lineage" {
		t.Fatalf("the record %v", d)
	}
	if answer, err := open(lead, "/team-planning-oversight/detail?activity_id=nowhere"); err != nil || answer.GetDrawer().GetTitle() != "Not available" {
		t.Fatalf("a record that is not there: %v %v", answer, err)
	}
	// Overdue: both read the risk; with no school the Lead has no one to
	// send it to, so no Send form.
	if _, err := admin.Exec(ctx, `UPDATE activity SET planned_date = current_date - 3 WHERE id = $1`, id); err != nil {
		t.Fatalf("moving the activity back: %v", err)
	}
	leadRisk, err := open(lead, "/team-planning-oversight/detail?activity_id="+id)
	if err != nil || leadRisk.GetDrawer().GetItems()[0].GetHeading() != "Needs attention" || leadRisk.GetDrawer().GetCanSubmit() {
		t.Fatalf("the Lead on a risk: %v %v", leadRisk, err)
	}
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	risky, err := open(director, "/team-planning-oversight/detail?activity_id="+id)
	if err != nil {
		t.Fatalf("the Director on a risk: %v", err)
	}
	if items := risky.GetDrawer().GetItems(); len(items) < 2 || items[0].GetHeading() != "Needs attention" ||
		!strings.HasPrefix(items[1].GetText(), "Complete the activity or reschedule it Planned for ") {
		t.Fatalf("the Director's risks %v", risky.GetDrawer())
	}
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	if answer, err := open(cceo, "/team-planning-oversight/detail?activity_id="+id); err != nil ||
		answer.GetRefusal() != "Access Denied: Your active role does not have permission to view Team Planning Oversight." {
		t.Fatalf("a CCEO: %v %v", answer, err)
	}
	borrowAccount(t, "regional-lead@edify.org")
	regional := sessionOf(t, "regional-lead@edify.org", seededPassword).GetAccessToken()
	if _, err := open(regional, "/team-planning-oversight/detail?activity_id="+id); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("the Regional Programme Lead: %v, want handed on", err)
	}
}
