//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"
	"time"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/acting"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

func actingClient() identityv1connect.ActingLeadershipServiceClient {
	return identityv1connect.NewActingLeadershipServiceClient(http.DefaultClient, baseURL)
}

// months are this month and the next two, as the appointment drawer offers
// them ("2026-11").
func months() (this, next, after string) {
	today := acting.Today(time.Now())
	first := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC)
	return first.Format("2006-01"), first.AddDate(0, 1, 0).Format("2006-01"), first.AddDate(0, 2, 0).Format("2006-01")
}

// clearAppointments removes the test's appointments, before and after, and
// puts the people's acting hint back.
func clearAppointments(t *testing.T, userIDs ...string) {
	t.Helper()
	clear := func() {
		ctx := context.Background()
		for _, id := range userIDs {
			_, _ = admin.Exec(ctx, `DELETE FROM acting_assignment WHERE appointee_id = $1 OR appointed_by_id = $1`, id)
			_, _ = admin.Exec(ctx, `UPDATE "user" SET acting_until = NULL WHERE id = $1`, id)
		}
	}
	clear()
	t.Cleanup(clear)
}

func lastActingAudit(t *testing.T, action string) (subject string, success bool, payload map[string]any) {
	t.Helper()
	var raw []byte
	var subjectID *string
	if err := admin.QueryRow(context.Background(), `
SELECT subject_id, success, payload FROM audit_log WHERE action = $1 ORDER BY seq DESC LIMIT 1`, action).
		Scan(&subjectID, &success, &raw); err != nil {
		t.Fatalf("no %s audit row: %v", action, err)
	}
	if subjectID != nil {
		subject = *subjectID
	}
	_ = json.Unmarshal(raw, &payload)
	return subject, success, payload
}

func TestAProgramLeadAppointsAnActingLeadForAMonth(t *testing.T) {
	ctx := context.Background()
	leadUser := borrowAccount(t, "pl1@edify.org")
	_, leadSeat := staffOf(t, "pl1@edify.org")
	_, otherSeat := staffOf(t, "pl2@edify.org")
	cceoUser, cceo := aCCEOOf(t, leadSeat)
	_, outsider := aCCEOOf(t, otherSeat)
	directorUser := borrowAccount(t, "cd@edify.org")
	clearAppointments(t, leadUser, cceoUser, directorUser)
	_, next, after := months()
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()

	options, err := actingClient().GetAppointOptions(ctx, authed(&identityv1.GetAppointOptionsRequest{}, lead))
	if err != nil {
		t.Fatal(err)
	}
	var team int
	_ = admin.QueryRow(ctx, `
SELECT count(*) FROM staff_supervisor_assignment a JOIN staff_profile sp ON sp.id = a.supervisee_id
JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisor_id = $1 AND (u.active_role = 'CCEO' OR 'CCEO' = ANY(u.roles))
  AND NOT (u.active_role = 'Program Lead' OR 'Program Lead' = ANY(u.roles)) AND u.is_active AND u.deleted_at IS NULL`,
		leadSeat).Scan(&team)
	if options.Msg.GetLabel() != "Acting Program Lead" || len(options.Msg.GetCandidates()) != team ||
		len(options.Msg.GetMonths()) != 12 {
		t.Fatalf("a Program Lead may appoint %d of their %d CCEOs over %d months (%s)",
			len(options.Msg.GetCandidates()), team, len(options.Msg.GetMonths()), options.Msg.GetLabel())
	}

	preview, err := actingClient().PreviewAppointment(ctx, authed(&identityv1.PreviewAppointmentRequest{
		AppointeeStaffId: cceo, Month: next}, lead))
	if err != nil || preview.Msg.GetStatement() == "" {
		t.Fatalf("the confirmation step: %v %+v", err, preview)
	}

	made, err := actingClient().Appoint(ctx, authed(&identityv1.AppointRequest{AppointeeStaffId: cceo, Month: next}, lead))
	if err != nil {
		t.Fatal(err)
	}
	appointment := made.Msg.GetAppointment()
	if appointment.GetState() != "upcoming" || appointment.GetMonth() != next || !appointment.GetCanCancel() ||
		!appointment.GetCanChangeMonth() {
		t.Fatalf("the new appointment: %+v", appointment)
	}
	var (
		start, end, until time.Time
		snapshot          []byte
		inCapacity        bool
		seatID            string
	)
	if err := admin.QueryRow(ctx, `
SELECT a.start_date, a.end_date, a.seat_id, a.in_capacity, a.grant_snapshot, u.acting_until
FROM acting_assignment a JOIN "user" u ON u.id = a.appointee_id WHERE a.id = $1`, appointment.GetId()).
		Scan(&start, &end, &seatID, &inCapacity, &snapshot, &until); err != nil {
		t.Fatal(err)
	}
	if start.Day() != 1 || end.AddDate(0, 0, 1).Day() != 1 || seatID != leadSeat || !inCapacity || !until.Equal(end) {
		t.Fatalf("the row: %s–%s seat %s in capacity %v hint %s", start, end, seatID, inCapacity, until)
	}
	var granted map[string]any
	_ = json.Unmarshal(snapshot, &granted)
	if members, _ := granted["seat_members"].([]any); len(members) == 0 || granted["policy"] != "acting_pl" ||
		granted["withheld_permissions"] == nil {
		t.Fatalf("what was granted was not recorded: %s", snapshot)
	}
	if subject, ok, payload := lastActingAudit(t, "acting_assignment.created"); subject != appointment.GetId() || !ok ||
		payload["acting_label"] != "Acting Program Lead" {
		t.Fatalf("the appointment's audit row: %s %v %v", subject, ok, payload)
	}

	// One acting leader per seat and month; nobody outside the lead's team.
	_, err = actingClient().Appoint(ctx, authed(&identityv1.AppointRequest{AppointeeStaffId: cceo, Month: next}, lead))
	requireCode(t, err, connect.CodeAlreadyExists, "")
	_, err = actingClient().Appoint(ctx, authed(&identityv1.AppointRequest{AppointeeStaffId: outsider, Month: after}, lead))
	requireCode(t, err, connect.CodePermissionDenied, apierr.ReasonPermissionDenied)
	if _, ok, payload := lastActingAudit(t, "acting_assignment.refused"); ok || payload["requested_staff_profile_id"] != outsider {
		t.Fatalf("the out-of-reach attempt was not kept: %v", payload)
	}

	moved, err := actingClient().ChangeMonth(ctx, authed(&identityv1.ChangeMonthRequest{
		AppointmentId: appointment.GetId(), Month: after}, lead))
	if err != nil || moved.Msg.GetAppointment().GetMonth() != after || len(moved.Msg.GetAppointment().GetEarlierMonths()) != 1 {
		t.Fatalf("moving the month: %v %+v", err, moved)
	}

	// The country's Director reads it and may cancel it, but not move it.
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	board, err := actingClient().GetActingBoard(ctx, authed(&identityv1.GetActingBoardRequest{}, director))
	if err != nil || len(board.Msg.GetUpcoming()) != 1 || !board.Msg.GetUpcoming()[0].GetCanCancel() ||
		board.Msg.GetUpcoming()[0].GetCanChangeMonth() || board.Msg.GetCanAppointLabel() != "Acting CD" {
		t.Fatalf("the Director's board: %v %+v", err, board)
	}

	cancelled, err := actingClient().CancelAppointment(ctx, authed(&identityv1.CancelAppointmentRequest{
		AppointmentId: appointment.GetId(), Reason: "Back early"}, lead))
	if err != nil || cancelled.Msg.GetAppointment().GetState() != "cancelled" {
		t.Fatalf("cancelling: %v %+v", err, cancelled)
	}
	var hint *time.Time
	_ = admin.QueryRow(ctx, `SELECT acting_until FROM "user" WHERE id = $1`, cceoUser).Scan(&hint)
	if hint != nil {
		t.Fatalf("a cancelled appointment still hints %s", hint)
	}
	_, err = actingClient().CancelAppointment(ctx, authed(&identityv1.CancelAppointmentRequest{AppointmentId: appointment.GetId()}, lead))
	requireCode(t, err, connect.CodeInvalidArgument, "")

	board, err = actingClient().GetActingBoard(ctx, authed(&identityv1.GetActingBoardRequest{}, lead))
	if err != nil || len(board.Msg.GetHistory()) != 1 || board.Msg.GetHistory()[0].GetCancelReason() != "Back early" {
		t.Fatalf("the cancelled appointment is the record: %v %+v", err, board)
	}
}

func TestAnAppointeeWorksInTheActingCapacityAndLeavesIt(t *testing.T) {
	ctx := context.Background()
	leadUser := borrowAccount(t, "pl1@edify.org")
	_, leadSeat := staffOf(t, "pl1@edify.org")
	cceoUser, cceo := aCCEOOf(t, leadSeat)
	var cceoEmail string
	_ = admin.QueryRow(ctx, `SELECT email FROM "user" WHERE id = $1`, cceoUser).Scan(&cceoEmail)
	borrowAccount(t, cceoEmail)
	restoreAccount(t, cceoEmail)
	directorUser := borrowAccount(t, "cd@edify.org")
	clearAppointments(t, leadUser, cceoUser, directorUser)
	this, _, _ := months()
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()

	made, err := actingClient().Appoint(ctx, authed(&identityv1.AppointRequest{AppointeeStaffId: cceo, Month: this}, lead))
	if err != nil || made.Msg.GetAppointment().GetState() != "active" {
		t.Fatalf("appointing for this month: %v %+v", err, made)
	}

	appointee := sessionOf(t, cceoEmail, seededPassword).GetAccessToken()
	session, err := identityClient().GetSession(ctx, authed(&identityv1.GetSessionRequest{}, appointee))
	if err != nil || session.Msg.GetSession().GetActing().GetLabel() != "Acting Program Lead" ||
		!session.Msg.GetSession().GetActing().GetInCapacity() {
		t.Fatalf("the session carries the acting capacity: %v %+v", err, session)
	}
	// Teams has not taken the seat over, so it refuses rather than guess.
	_, err = staffTeams().ListStaff(ctx, authed(&identityv1.ListStaffRequest{}, appointee))
	requireCode(t, err, connect.CodeFailedPrecondition, apierr.ReasonActingNotSupported)
	// Nobody in an acting capacity appoints.
	_, err = actingClient().GetAppointOptions(ctx, authed(&identityv1.GetAppointOptionsRequest{}, appointee))
	requireCode(t, err, connect.CodePermissionDenied, "")

	left, err := actingClient().SetActingCapacity(ctx, authed(&identityv1.SetActingCapacityRequest{Acting: false}, appointee))
	if err != nil || left.Msg.GetCapacity().GetInCapacity() {
		t.Fatalf("leaving the capacity: %v %+v", err, left)
	}
	if _, ok, _ := lastActingAudit(t, "acting_capacity.left"); !ok {
		t.Fatal("leaving was not audited")
	}
	// In their own role, the module answers them as the CCEO they are.
	_, err = staffTeams().ListStaff(ctx, authed(&identityv1.ListStaffRequest{}, appointee))
	requireCode(t, err, connect.CodePermissionDenied, "")

	if _, err := actingClient().SetActingCapacity(ctx, authed(&identityv1.SetActingCapacityRequest{Acting: true}, appointee)); err != nil {
		t.Fatal(err)
	}
	// Work as their own role leaves the capacity, as on the web.
	if _, err := accountClient().SwitchRole(ctx, authed(&identityv1.SwitchRoleRequest{Role: "CCEO"}, appointee)); err != nil {
		t.Fatal(err)
	}
	var inCapacity bool
	_ = admin.QueryRow(ctx, `SELECT in_capacity FROM acting_assignment WHERE id = $1`, made.Msg.GetAppointment().GetId()).Scan(&inCapacity)
	if inCapacity {
		t.Fatal("switching to their own role left the acting capacity on")
	}

	// Someone working in another role they hold enters the capacity: their
	// account goes back to the role it was made from, with a token for it.
	if _, err := admin.Exec(ctx, `UPDATE "user" SET roles = ARRAY['CCEO', 'ProjectCoordinator'] WHERE id = $1`, cceoUser); err != nil {
		t.Fatal(err)
	}
	asCoordinator, err := accountClient().SwitchRole(ctx, authed(&identityv1.SwitchRoleRequest{Role: "ProjectCoordinator"}, appointee))
	if err != nil {
		t.Fatal(err)
	}
	entered, err := actingClient().SetActingCapacity(ctx, authed(&identityv1.SetActingCapacityRequest{Acting: true},
		asCoordinator.Msg.GetAccessToken()))
	if err != nil || entered.Msg.GetAccessToken() == "" {
		t.Fatalf("entering from another role: %v %+v", err, entered)
	}
	_, err = staffTeams().ListStaff(ctx, authed(&identityv1.ListStaffRequest{}, entered.Msg.GetAccessToken()))
	requireCode(t, err, connect.CodeFailedPrecondition, apierr.ReasonActingNotSupported)

	// The country's Director stops it; the next request carries no capacity.
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	if _, err := actingClient().CancelAppointment(ctx, authed(&identityv1.CancelAppointmentRequest{
		AppointmentId: made.Msg.GetAppointment().GetId()}, director)); err != nil {
		t.Fatal(err)
	}
	session, err = identityClient().GetSession(ctx, authed(&identityv1.GetSessionRequest{}, appointee))
	if err != nil || session.Msg.GetSession().GetActing() != nil {
		t.Fatalf("a cancelled appointment still shows: %v %+v", err, session)
	}
	_, err = actingClient().SetActingCapacity(ctx, authed(&identityv1.SetActingCapacityRequest{Acting: true}, appointee))
	requireCode(t, err, connect.CodeInvalidArgument, "")
}

func TestACountryDirectorAppointsAProgramLeadOfTheirCountry(t *testing.T) {
	ctx := context.Background()
	directorUser := borrowAccount(t, "cd@edify.org")
	borrowAccount(t, "pl1@edify.org")
	leadUser, leadSeat := staffOf(t, "pl2@edify.org")
	clearAppointments(t, directorUser, leadUser)
	_, next, _ := months()
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()

	options, err := actingClient().GetAppointOptions(ctx, authed(&identityv1.GetAppointOptionsRequest{}, director))
	if err != nil || options.Msg.GetAppointeeRole() != "Program Lead" {
		t.Fatalf("the Director's options: %v %+v", err, options)
	}
	offered := false
	for _, c := range options.Msg.GetCandidates() {
		offered = offered || c.GetStaffProfileId() == leadSeat
	}
	if !offered {
		t.Fatal("a Program Lead of the Director's country is not offered")
	}
	made, err := actingClient().Appoint(ctx, authed(&identityv1.AppointRequest{AppointeeStaffId: leadSeat, Month: next}, director))
	if err != nil || made.Msg.GetAppointment().GetScopeLabel() != "Uganda" || made.Msg.GetAppointment().GetShortLabel() != "Acting CD" {
		t.Fatalf("appointing an Acting Country Director: %v %+v", err, made)
	}
	// Another Program Lead cannot even see an appointment of the Director's seat.
	other := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	_, err = actingClient().CancelAppointment(ctx, authed(&identityv1.CancelAppointmentRequest{
		AppointmentId: made.Msg.GetAppointment().GetId()}, other))
	requireCode(t, err, connect.CodeNotFound, "")
}
