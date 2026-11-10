//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1/clustersv1connect"
)

func operationsClient() clustersv1connect.ClusterMobilizationServiceClient {
	return clustersv1connect.NewClusterMobilizationServiceClient(http.DefaultClient, baseURL)
}

// upcomingMeetingFixture makes one seeded cluster meeting a scheduled one in
// days days, and puts it back afterwards (test database only).
func upcomingMeetingFixture(t *testing.T) (activityID, clusterID string, setDays func(int)) {
	t.Helper()
	ctx := context.Background()
	var status string
	var scheduled *time.Time
	var kind string
	err := admin.QueryRow(ctx, `
SELECT a.id, a.cluster_id, a.status, a.scheduled_date, COALESCE(a.meeting_kind, '')
FROM activity a JOIN school s ON s.cluster_id = a.cluster_id
  AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
WHERE a.activity_type = 'cluster_meeting' AND a.deleted_at IS NULL
GROUP BY a.id HAVING count(s.id) >= 2 ORDER BY a.id LIMIT 1`).Scan(&activityID, &clusterID, &status, &scheduled, &kind)
	if err != nil {
		t.Fatalf("the test database needs a cluster meeting of a cluster with 2+ schools (demo seed): %v", err)
	}
	setDays = func(days int) {
		if _, err := admin.Exec(ctx, `UPDATE activity SET status = 'scheduled', meeting_kind = 'only_meeting',
  scheduled_date = now() + make_interval(days => $2) WHERE id = $1`, activityID, days); err != nil {
			t.Fatal(err)
		}
	}
	setDays(5)
	t.Cleanup(func() {
		ctx := context.Background()
		_, _ = admin.Exec(ctx, `UPDATE activity SET status = $2, scheduled_date = $3, meeting_kind = $4 WHERE id = $1`,
			activityID, status, scheduled, kind)
		for _, table := range []string{"invitation_event", "plan_event", "action_item_event"} {
			_, _ = admin.Exec(ctx, `DELETE FROM cluster_leadership.`+table)
		}
		for _, table := range []string{"invitation", "attendance_record", "meeting_minutes", "meeting_plan", "action_item", "leader_request"} {
			_, _ = admin.Exec(ctx, `DELETE FROM cluster_leadership.`+table)
		}
	})
	return activityID, clusterID, setDays
}

func TestAClusterOperationsJourney(t *testing.T) {
	ctx := context.Background()
	leaderID := leaderFixture(t)
	activityID, clusterID, setDays := upcomingMeetingFixture(t)
	adminBearer := token(t, adminAccount(t), "Admin", time.Hour)
	leaderBearer := token(t, leaderID, roleClusterLeader, time.Hour)
	leads, ops := clustersClient(), operationsClient()

	if _, err := leads.AssignLeader(ctx, authed(&clustersv1.AssignLeaderRequest{ClusterId: clusterID, UserId: leaderID}, adminBearer)); err != nil {
		t.Fatalf("assigning the leader: %v", err)
	}

	// Plan → review → link to the official activity (its id is kept).
	plan, err := ops.SavePlan(ctx, authed(&clustersv1.SavePlanRequest{
		ClusterId: clusterID, Category: "only_meeting", Title: "Term planning",
		PlannedOn: time.Now().AddDate(0, 0, 5).Format("2006-01-02"), Submit: true,
	}, leaderBearer))
	if err != nil {
		t.Fatalf("the leader submits a plan: %v", err)
	}
	id := plan.Msg.GetPlan().GetId()
	if _, err := ops.ReviewPlan(ctx, authed(&clustersv1.ReviewPlanRequest{Id: id, Approve: true}, leaderBearer)); connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("a leader cannot approve their own plan, got %v", err)
	}
	if _, err := ops.ReviewPlan(ctx, authed(&clustersv1.ReviewPlanRequest{Id: id, Approve: true}, adminBearer)); err != nil {
		t.Fatalf("staff approve: %v", err)
	}
	linked, err := ops.LinkPlan(ctx, authed(&clustersv1.LinkPlanRequest{Id: id, ActivityId: activityID}, adminBearer))
	if err != nil || linked.Msg.GetPlan().GetActivityId() != activityID || linked.Msg.GetPlan().GetStatus() != "scheduled" {
		t.Fatalf("the plan links to the official activity: %v %v", linked, err)
	}

	// Mobilise two member schools; a second call invites nobody twice.
	board, err := ops.GetMobilization(ctx, authed(&clustersv1.GetMobilizationRequest{ActivityId: activityID}, leaderBearer))
	if err != nil {
		t.Fatal(err)
	}
	schools := board.Msg.GetSchools()
	pick := []string{schools[0].GetSchoolId(), schools[1].GetSchoolId()}
	invited, err := ops.InviteSchools(ctx, authed(&clustersv1.InviteSchoolsRequest{ActivityId: activityID, SchoolIds: pick, Channel: "phone"}, leaderBearer))
	if err != nil || invited.Msg.GetInvited() != 2 {
		t.Fatalf("two invitations: %v %v", invited, err)
	}
	again, err := ops.InviteSchools(ctx, authed(&clustersv1.InviteSchoolsRequest{ActivityId: activityID, SchoolIds: pick, Channel: "phone"}, leaderBearer))
	if err != nil || again.Msg.GetInvited() != 0 || again.Msg.GetAlreadyInvited() != 2 {
		t.Fatalf("nobody is invited twice: %v %v", again, err)
	}
	board, _ = ops.GetMobilization(ctx, authed(&clustersv1.GetMobilizationRequest{ActivityId: activityID}, leaderBearer))
	invitationOf := map[string]string{}
	for _, s := range board.Msg.GetSchools() {
		invitationOf[s.GetSchoolId()] = s.GetInvitationId()
	}
	if _, err := ops.RecordResponse(ctx, authed(&clustersv1.RecordResponseRequest{InvitationId: invitationOf[pick[0]], Status: "confirmed"}, leaderBearer)); err != nil {
		t.Fatal(err)
	}

	home, err := leads.GetClusterHome(ctx, authed(&clustersv1.GetClusterHomeRequest{ClusterId: clusterID}, leaderBearer))
	if err != nil {
		t.Fatal(err)
	}
	counts := map[string]int32{}
	for _, c := range home.Msg.GetOverview() {
		counts[c.GetKey()] = c.GetValue()
	}
	if counts["outstanding_responses"] != 1 || counts["to_mobilise"] != int32(len(schools)-2) {
		t.Fatalf("the Home counts the mobilisation: %v", counts)
	}
	for _, a := range home.Msg.GetUpcoming() {
		if a.GetId() == activityID && a.GetConfirmedSchools() != 1 {
			t.Fatalf("one confirmed school: %v", a)
		}
	}

	// The day passes: attendance is the leader's record, never the answer.
	setDays(-1)
	if _, err := ops.RecordAttendance(ctx, authed(&clustersv1.RecordAttendanceRequest{ActivityId: activityID,
		Entries: []*clustersv1.AttendanceEntry{{SchoolId: pick[0], Attended: true, Participants: 4}}}, leaderBearer)); err != nil {
		t.Fatalf("attendance: %v", err)
	}
	board, _ = ops.GetMobilization(ctx, authed(&clustersv1.GetMobilizationRequest{ActivityId: activityID}, leaderBearer))
	state := map[string]string{}
	for _, s := range board.Msg.GetSchools() {
		state[s.GetSchoolId()] = s.GetState()
	}
	if state[pick[0]] != "attended" || state[pick[1]] != "no_response" {
		t.Fatalf("attended comes from attendance, no answer from the invitation: %v", state)
	}

	if _, err := ops.SaveMinutes(ctx, authed(&clustersv1.SaveMinutesRequest{ActivityId: activityID, Discussion: "Term plan agreed.", Submit: true}, leaderBearer)); err != nil {
		t.Fatal(err)
	}
	if _, err := ops.SaveMinutes(ctx, authed(&clustersv1.SaveMinutesRequest{ActivityId: activityID, Discussion: "Changed."}, leaderBearer)); connect.CodeOf(err) != connect.CodeFailedPrecondition {
		t.Fatalf("submitted minutes are kept as they are, got %v", err)
	}

	item, err := ops.SaveActionItem(ctx, authed(&clustersv1.SaveActionItemRequest{ClusterId: clusterID, ActivityId: activityID,
		Title: "Share the term plan", OwnerSchoolId: pick[0], DueOn: time.Now().AddDate(0, 0, 7).Format("2006-01-02")}, leaderBearer))
	if err != nil {
		t.Fatal(err)
	}
	closed, err := ops.CloseActionItem(ctx, authed(&clustersv1.CloseActionItemRequest{Id: item.Msg.GetItem().GetId(), Status: "done"}, leaderBearer))
	if err != nil || closed.Msg.GetItem().GetStatus() != "done" || len(closed.Msg.GetItem().GetHistory()) != 2 {
		t.Fatalf("an item closes and keeps its history: %v %v", closed, err)
	}

	report, err := ops.GetClusterReport(ctx, authed(&clustersv1.GetClusterReportRequest{ClusterId: clusterID}, leaderBearer))
	if err != nil {
		t.Fatal(err)
	}
	figures := map[string]string{}
	for _, f := range report.Msg.GetFigures() {
		figures[f.GetKey()] = f.GetValue()
	}
	if figures["schools_invited"] != "2" || figures["schools_participating"] != "1" || figures["participation_rate"] != "50%" {
		t.Fatalf("the report counts invitations and attendance apart: %v", figures)
	}

	asked, err := ops.SubmitRequest(ctx, authed(&clustersv1.SubmitRequestRequest{ClusterId: clusterID, Subject: "Training venue", Body: "Can the CCEO confirm the venue?"}, leaderBearer))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ops.AnswerRequest(ctx, authed(&clustersv1.AnswerRequestRequest{Id: asked.Msg.GetRequest().GetId(), Answer: "Yes."}, leaderBearer)); connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("a leader does not answer their own request, got %v", err)
	}
	if _, err := ops.AnswerRequest(ctx, authed(&clustersv1.AnswerRequestRequest{Id: asked.Msg.GetRequest().GetId(), Answer: "Kasawo P/S, 9am."}, adminBearer)); err != nil {
		t.Fatalf("staff answer: %v", err)
	}
}
