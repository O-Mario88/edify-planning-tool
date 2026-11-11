//go:build integration

package integration

import (
	"context"
	"net/http"
	"slices"
	"testing"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1/clustersv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead"
)

func actionsClient() clustersv1connect.ClusterActionServiceClient {
	return clustersv1connect.NewClusterActionServiceClient(http.DefaultClient, baseURL)
}

type staffAccount struct{ userID, staffID string }

func staffByEmail(t *testing.T, email string) staffAccount {
	t.Helper()
	var a staffAccount
	if err := admin.QueryRow(context.Background(), `SELECT u.id, sp.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.email = $1 AND u.deleted_at IS NULL`, email).Scan(&a.userID, &a.staffID); err != nil {
		t.Fatalf("the test database needs %s (demo seed): %v", email, err)
	}
	return a
}

func supervisorOf(t *testing.T, staffID string) staffAccount {
	t.Helper()
	var a staffAccount
	if err := admin.QueryRow(context.Background(), `SELECT sp.user_id, sp.id FROM staff_supervisor_assignment s
JOIN staff_profile sp ON sp.id = s.supervisor_id WHERE s.supervisee_id = $1 ORDER BY s.supervisor_id LIMIT 1`, staffID).Scan(&a.userID, &a.staffID); err != nil {
		t.Fatalf("no supervisor for %s: %v", staffID, err)
	}
	return a
}

// actionSchoolsFixture picks three member schools of the cluster: the first
// stays with its holder, the second moves to another CCEO, the third is held
// by nobody; all is put back afterwards (test database only).
func actionSchoolsFixture(t *testing.T, clusterID string, other staffAccount) (schools []string, holder staffAccount) {
	t.Helper()
	ctx := context.Background()
	rows, err := admin.Query(ctx, `
SELECT s.id, a.staff_id, a.id FROM school s JOIN staff_school_assignment a ON a.school_id = s.id
WHERE s.cluster_id = $1 AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
ORDER BY s.id LIMIT 3`, clusterID)
	if err != nil {
		t.Fatal(err)
	}
	type held struct{ school, staff, assignment string }
	var picked []held
	for rows.Next() {
		var h held
		if err := rows.Scan(&h.school, &h.staff, &h.assignment); err != nil {
			t.Fatal(err)
		}
		picked = append(picked, h)
	}
	rows.Close()
	if len(picked) < 3 {
		t.Fatalf("the cluster needs three held member schools, has %d", len(picked))
	}
	if _, err := admin.Exec(ctx, `UPDATE staff_school_assignment SET staff_id = $2 WHERE id = $1`, picked[1].assignment, other.staffID); err != nil {
		t.Fatal(err)
	}
	if _, err := admin.Exec(ctx, `UPDATE staff_school_assignment SET school_id = school_id || '-x' WHERE id = $1`, picked[2].assignment); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		ctx := context.Background()
		_, _ = admin.Exec(ctx, `UPDATE staff_school_assignment SET staff_id = $2 WHERE id = $1`, picked[1].assignment, picked[1].staff)
		_, _ = admin.Exec(ctx, `UPDATE staff_school_assignment SET school_id = $2 WHERE id = $1`, picked[2].assignment, picked[2].school)
		// Test database only: the gateway itself never deletes these.
		for _, table := range []string{"cluster_action_notice", "cluster_action_escalation", "cluster_action_review",
			"cluster_action_event", "cluster_action_school", "cluster_action"} {
			_, _ = admin.Exec(ctx, `DELETE FROM cluster_leadership.`+table)
		}
	})
	var holderUser string
	if err := admin.QueryRow(ctx, `SELECT user_id FROM staff_profile WHERE id = $1`, picked[0].staff).Scan(&holderUser); err != nil {
		t.Fatal(err)
	}
	return []string{picked[0].school, picked[1].school, picked[2].school}, staffAccount{userID: holderUser, staffID: picked[0].staff}
}

func schoolOf(view *clustersv1.ClusterActionView, schoolID string) *clustersv1.ActionSchool {
	for _, s := range view.GetSchools() {
		if s.GetSchoolId() == schoolID {
			return s
		}
	}
	return nil
}

func TestAClusterActionFromNeedToVerifiedSupport(t *testing.T) {
	ctx := context.Background()
	leaderID := leaderFixture(t)
	activityID, clusterID, _ := upcomingMeetingFixture(t)
	other := staffByEmail(t, "cceo1@edify.org")
	schools, holder := actionSchoolsFixture(t, clusterID, other)
	if holder.staffID == other.staffID {
		t.Skip("the first school is already held by the second CCEO in this seed")
	}
	clusterSupervisor := supervisorOf(t, holder.staffID)
	adminBearer := token(t, adminAccount(t), "Admin", time.Hour)
	leaderBearer := token(t, leaderID, roleClusterLeader, time.Hour)
	holderBearer := token(t, holder.userID, "CCEO", time.Hour)
	otherBearer := token(t, other.userID, "CCEO", time.Hour)
	supervisorBearer := token(t, clusterSupervisor.userID, "Program Lead", time.Hour)
	actions := actionsClient()
	if _, err := clustersClient().AssignLeader(ctx, authed(&clustersv1.AssignLeaderRequest{ClusterId: clusterID, UserId: leaderID}, adminBearer)); err != nil {
		t.Fatalf("assigning the leader: %v", err)
	}

	// 1. The leader sends a need for three schools, raised at the meeting.
	request := &clustersv1.SaveActionRequest{ClusterId: clusterID, SchoolIds: schools, SupportKind: "school_visit",
		Description: "Low literacy in three schools.", TargetOn: time.Now().AddDate(0, 0, 20).Format("2006-01-02"),
		Source: "meeting", SourceActivityId: activityID, Submit: true, IdempotencyKey: "it-key-1"}
	saved, err := actions.SaveAction(ctx, authed(request, leaderBearer))
	if err != nil {
		t.Fatalf("the leader sends the action: %v", err)
	}
	view := saved.Msg.GetAction()
	id := view.GetCard().GetId()
	// A retried submission makes nothing new.
	again, err := actions.SaveAction(ctx, authed(request, leaderBearer))
	if err != nil || !again.Msg.GetReplayed() || again.Msg.GetAction().GetCard().GetId() != id {
		t.Fatalf("a retry made another action: %v %v", again, err)
	}
	var count int
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM cluster_leadership.cluster_action`).Scan(&count)
	if count != 1 {
		t.Fatalf("%d actions after a retry", count)
	}

	// 2. Each school went to the CCEO holding it; the unheld one to the
	// supervisor of the cluster's staff, to assign.
	if s := schoolOf(view, schools[0]); s.GetRoutedTo() != "owner" || s.GetProgress() != "awaiting_review" {
		t.Fatalf("first school: %v", s)
	}
	if s := schoolOf(view, schools[2]); s.GetRoutedTo() != "supervisor" {
		t.Fatalf("an unheld school: %v", s)
	}
	routed := map[string]string{}
	rows, _ := admin.Query(ctx, `SELECT school_id, COALESCE(responsible_staff_id, supervisor_staff_id) FROM cluster_leadership.cluster_action_school`)
	for rows.Next() {
		var school, staff string
		_ = rows.Scan(&school, &staff)
		routed[school] = staff
	}
	rows.Close()
	if routed[schools[0]] != holder.staffID || routed[schools[1]] != other.staffID || routed[schools[2]] != clusterSupervisor.staffID {
		t.Fatalf("routing: %v", routed)
	}
	var notices int
	_ = admin.QueryRow(ctx, `SELECT count(DISTINCT recipient_user_id) FROM cluster_leadership.cluster_action_notice
WHERE event = 'cluster_action_submitted'`).Scan(&notices)
	if notices < 2 {
		t.Fatalf("the routed staff were not told: %d recipients", notices)
	}

	// 3. Each CCEO sees only their own school's request.
	queue := func(bearer, scope string) []string {
		got, err := actions.ListSupportRequests(ctx, authed(&clustersv1.ListSupportRequestsRequest{Scope: scope}, bearer))
		if err != nil {
			t.Fatalf("queue: %v", err)
		}
		var out []string
		for _, r := range got.Msg.GetRows() {
			out = append(out, r.GetSchoolId())
		}
		return out
	}
	if got := queue(otherBearer, "mine"); !slices.Equal(got, []string{schools[1]}) {
		t.Fatalf("the second CCEO's queue: %v", got)
	}
	if got := queue(holderBearer, "mine"); slices.Contains(got, schools[1]) || !slices.Contains(got, schools[0]) {
		t.Fatalf("the holder's queue: %v", got)
	}
	if got := queue(supervisorBearer, "mine"); !slices.Contains(got, schools[2]) {
		t.Fatalf("the supervisor's queue holds the unheld school: %v", got)
	}

	respond := func(bearer, school, response, note, code string) (*clustersv1.ClusterActionView, error) {
		got, err := actions.RespondToRequest(ctx, authed(&clustersv1.RespondToRequestRequest{ActionId: id, SchoolId: school,
			Response: response, Note: note, ReasonCode: code}, bearer))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetAction(), nil
	}
	// 4. Nobody answers for another CCEO's school; nothing is returned silently.
	if _, err := respond(otherBearer, schools[0], "accept", "", ""); connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("another CCEO answered, got %v", err)
	}
	if _, err := respond(otherBearer, schools[1], "return", "", ""); connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a return without a reason, got %v", err)
	}
	if _, err := respond(otherBearer, schools[1], "return", "Already planned this term.", "already_scheduled"); err != nil {
		t.Fatal(err)
	}

	// 5. Clarification goes back to the leader, and their reply comes back.
	if v, err := respond(holderBearer, schools[0], "clarify", "Which classes?", ""); err != nil || v.GetCard().GetStatus() != "needs_reply" {
		t.Fatalf("clarification: %v %v", v, err)
	}
	if _, err := actions.ReplyToAction(ctx, authed(&clustersv1.ReplyToActionRequest{Id: id, SchoolId: schools[0], Note: "P3 and P4."}, leaderBearer)); err != nil {
		t.Fatal(err)
	}
	if _, err := respond(holderBearer, schools[0], "accept", "", ""); err != nil {
		t.Fatal(err)
	}

	// 6. The CCEO links the official activity; its own status is the progress.
	linkable, err := actions.ListLinkableActivities(ctx, authed(&clustersv1.ListLinkableActivitiesRequest{ActionId: id, SchoolId: schools[0]}, holderBearer))
	if err != nil || !slices.ContainsFunc(linkable.Msg.GetActivities(), func(a *clustersv1.LinkedActivity) bool { return a.GetId() == activityID }) {
		t.Fatalf("the cluster's meeting is linkable: %v %v", linkable, err)
	}
	linked, err := actions.LinkActivity(ctx, authed(&clustersv1.LinkActivityRequest{ActionId: id, SchoolId: schools[0], ActivityId: activityID}, holderBearer))
	if err != nil || schoolOf(linked.Msg.GetAction(), schools[0]).GetProgress() != "planned" {
		t.Fatalf("linked: %v %v", linked, err)
	}
	progress := func() *clustersv1.ClusterActionView {
		got, err := actions.GetAction(ctx, authed(&clustersv1.GetActionRequest{Id: id}, leaderBearer))
		if err != nil {
			t.Fatal(err)
		}
		return got.Msg.GetAction()
	}
	if _, err := admin.Exec(ctx, `UPDATE activity SET status = 'evidence_uploaded' WHERE id = $1`, activityID); err != nil {
		t.Fatal(err)
	}
	if p := schoolOf(progress(), schools[0]).GetProgress(); p != "implementation_recorded" {
		t.Fatalf("evidence uploaded is never verified: %s", p)
	}
	if _, err := admin.Exec(ctx, `UPDATE activity SET status = 'completed' WHERE id = $1`, activityID); err != nil {
		t.Fatal(err)
	}
	v := progress()
	if schoolOf(v, schools[0]).GetProgress() != "verified" || v.GetCard().GetProgressSummary() != "1 of 3 schools verified" {
		t.Fatalf("partial completion: %v", v.GetCard())
	}
	if _, err := actions.CloseAction(ctx, authed(&clustersv1.CloseActionRequest{Id: id, Summary: "x"}, leaderBearer)); connect.CodeOf(err) != connect.CodeFailedPrecondition {
		t.Fatalf("closed with a school still waiting, got %v", err)
	}

	// 7. Reviewed at the next meeting without a second action; carried forward.
	if _, err := actions.ReviewAction(ctx, authed(&clustersv1.ReviewActionRequest{Id: id, MeetingActivityId: activityID,
		Progress: "One school trained.", Outcome: "continue"}, leaderBearer)); err != nil {
		t.Fatal(err)
	}
	carried, err := actions.ListCarryForward(ctx, authed(&clustersv1.ListCarryForwardRequest{ClusterId: clusterID}, leaderBearer))
	if err != nil || len(carried.Msg.GetActions()) != 1 {
		t.Fatalf("carried forward: %v %v", carried, err)
	}
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM cluster_leadership.cluster_action`).Scan(&count)
	if count != 1 {
		t.Fatalf("a review made a new action: %d", count)
	}

	// 8. The follow-up reminds about the unanswered school, once a day.
	if _, err := admin.Exec(ctx, `UPDATE cluster_leadership.cluster_action SET submitted_at = now() - interval '5 days'`); err != nil {
		t.Fatal(err)
	}
	store := clusterlead.NewStore(gateway)
	followUp := clusterlead.NewActions(clusterlead.NewOperations(clusterlead.NewService(store, time.Now, nil, nil), store), store,
		clusterlead.ActionConfig{RemindAfterDays: 3})
	if _, err := followUp.FollowUp(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := followUp.FollowUp(ctx); err != nil {
		t.Fatal(err)
	}
	var reminders int
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM cluster_leadership.cluster_action_notice WHERE event = 'cluster_action_reminder'`).Scan(&reminders)
	if reminders != 1 {
		t.Fatalf("%d reminders after two passes on one day", reminders)
	}
	sender := &recordingSender{}
	sent, err := followUp.RelayNotices(ctx, sender)
	if err != nil || sent == 0 || len(sender.sent) != sent {
		t.Fatalf("relayed %d: %v", sent, err)
	}
	if again, _ := followUp.RelayNotices(ctx, sender); again != 0 {
		t.Fatalf("a delivered notice was sent again: %d", again)
	}

	// 9. The last school is declined with a reason; the leader closes it.
	if _, err := respond(supervisorBearer, schools[2], "decline", "No longer operating as a school.", "not_eligible"); err != nil {
		t.Fatal(err)
	}
	closed, err := actions.CloseAction(ctx, authed(&clustersv1.CloseActionRequest{Id: id, Summary: "Literacy support delivered."}, leaderBearer))
	if err != nil || closed.Msg.GetAction().GetCard().GetStatus() != "closed" {
		t.Fatalf("closing: %v %v", closed, err)
	}

	// 10. The school's history and the cluster's summary read the same records.
	history, err := actions.GetSchoolSupportHistory(ctx, authed(&clustersv1.GetSchoolSupportHistoryRequest{SchoolId: schools[0]}, holderBearer))
	if err != nil || len(history.Msg.GetEntries()) != 1 || history.Msg.GetEntries()[0].GetProgress() != "verified" {
		t.Fatalf("school history: %v %v", history, err)
	}
	summary, err := actions.GetClusterActionSummary(ctx, authed(&clustersv1.GetClusterActionSummaryRequest{ClusterId: clusterID}, leaderBearer))
	if err != nil || summary.Msg.GetResolvedSchools() != 1 {
		t.Fatalf("summary: %v %v", summary, err)
	}

	// 11. Staff not routed and not over the cluster never read it.
	outsider := staffByEmail(t, "cceo2@edify.org")
	if _, err := actions.GetAction(ctx, authed(&clustersv1.GetActionRequest{Id: id}, token(t, outsider.userID, "CCEO", time.Hour))); connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("an unrelated CCEO read the action, got %v", err)
	}
}

type recordingSender struct{ sent []string }

func (r *recordingSender) Send(_ context.Context, n clusterlead.NoticeRecord, _ string) error {
	r.sent = append(r.sent, n.ID)
	return nil
}
