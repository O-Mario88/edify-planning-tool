//go:build integration

package integration

import (
	"context"
	"net/http"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
)

func staffTeams() identityv1connect.StaffTeamServiceClient {
	return identityv1connect.NewStaffTeamServiceClient(http.DefaultClient, baseURL)
}

func partnerTeams() identityv1connect.PartnerTeamServiceClient {
	return identityv1connect.NewPartnerTeamServiceClient(http.DefaultClient, baseURL)
}

// keepReportingLines puts every reporting line back after the test.
func keepReportingLines(t *testing.T) {
	t.Helper()
	type line struct {
		id, supervisee, supervisor string
		created, updated           time.Time
	}
	ctx := context.Background()
	rows, err := admin.Query(ctx, `SELECT id, supervisee_id, supervisor_id, created_at, updated_at FROM staff_supervisor_assignment`)
	if err != nil {
		t.Fatal(err)
	}
	var saved []line
	for rows.Next() {
		var l line
		if err := rows.Scan(&l.id, &l.supervisee, &l.supervisor, &l.created, &l.updated); err != nil {
			t.Fatal(err)
		}
		saved = append(saved, l)
	}
	rows.Close()
	t.Cleanup(func() {
		ctx := context.Background()
		if _, err := admin.Exec(ctx, `DELETE FROM staff_supervisor_assignment`); err != nil {
			t.Errorf("restoring reporting lines: %v", err)
			return
		}
		for _, l := range saved {
			if _, err := admin.Exec(ctx, `
INSERT INTO staff_supervisor_assignment (id, supervisee_id, supervisor_id, created_at, updated_at) VALUES ($1, $2, $3, $4, $5)`,
				l.id, l.supervisee, l.supervisor, l.created, l.updated); err != nil {
				t.Errorf("restoring a reporting line: %v", err)
			}
		}
	})
}

func staffOf(t *testing.T, email string) (userID, staffID string) {
	t.Helper()
	if err := admin.QueryRow(context.Background(), `
SELECT u.id, sp.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id WHERE u.email = $1`, email).
		Scan(&userID, &staffID); err != nil {
		t.Fatalf("staff %s: %v", email, err)
	}
	return userID, staffID
}

// aCCEOOf is one CCEO a Program Lead supervises.
func aCCEOOf(t *testing.T, leadStaffID string) (userID, staffID string) {
	t.Helper()
	if err := admin.QueryRow(context.Background(), `
SELECT u.id, sp.id FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisee_id JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisor_id = $1 AND u.active_role = 'CCEO' ORDER BY u.email LIMIT 1`, leadStaffID).Scan(&userID, &staffID); err != nil {
		t.Fatalf("a CCEO of %s: %v", leadStaffID, err)
	}
	return userID, staffID
}

func TestTheStaffRosterIsScopedToTheReader(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "pl1@edify.org")
	_, lead := staffOf(t, "pl1@edify.org")
	session := sessionOf(t, "pl1@edify.org", seededPassword)
	roster, err := staffTeams().ListStaff(ctx, authed(&identityv1.ListStaffRequest{}, session.GetAccessToken()))
	if err != nil {
		t.Fatal(err)
	}
	var team int
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM staff_supervisor_assignment WHERE supervisor_id = $1`, lead).Scan(&team)
	if len(roster.Msg.GetStaff()) != team+1 {
		t.Fatalf("a Program Lead sees %d people; their team is %d and themselves", len(roster.Msg.GetStaff()), team)
	}
	for _, person := range roster.Msg.GetStaff() {
		if person.GetStaffId() != lead && person.GetSupervisorStaffId() != lead {
			t.Fatalf("%s is not on pl1's team", person.GetName())
		}
	}

	everyone, err := staffTeams().ListStaff(ctx, authed(&identityv1.ListStaffRequest{}, adminSession(t)))
	if err != nil {
		t.Fatal(err)
	}
	var live int
	_ = admin.QueryRow(ctx, `
SELECT count(*) FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL`).Scan(&live)
	if len(everyone.Msg.GetStaff()) != live {
		t.Fatalf("the Admin sees %d of %d staff", len(everyone.Msg.GetStaff()), live)
	}

	borrowAccount(t, "cceo10@edify.org")
	_, err = staffTeams().ListStaff(ctx, authed(&identityv1.ListStaffRequest{}, sessionOf(t, "cceo10@edify.org", seededPassword).GetAccessToken()))
	requireCode(t, err, connect.CodePermissionDenied, "")
}

func TestASupervisorIsReassignedUnderTheLevelRule(t *testing.T) {
	ctx := context.Background()
	keepReportingLines(t)
	_, lead1 := staffOf(t, "pl1@edify.org")
	_, lead2 := staffOf(t, "pl2@edify.org")
	_, director := staffOf(t, "cd@edify.org")
	cceoUser, cceo := aCCEOOf(t, lead1)
	borrowAccount(t, "hr@edify.org")
	hr := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()

	moved, err := staffTeams().AssignSupervisor(ctx, authed(&identityv1.AssignSupervisorRequest{
		UserId: cceoUser, SupervisorStaffId: lead2}, hr))
	if err != nil || moved.Msg.GetOldSupervisorStaffId() != lead1 || moved.Msg.GetNewSupervisorStaffId() != lead2 {
		t.Fatalf("moving a CCEO between leads: %v %+v", err, moved)
	}
	var toLead1, toLead2 int
	_ = admin.QueryRow(ctx, `SELECT count(*) FILTER (WHERE supervisor_id = $2), count(*) FILTER (WHERE supervisor_id = $3)
FROM staff_supervisor_assignment WHERE supervisee_id = $1`, cceo, lead1, lead2).Scan(&toLead1, &toLead2)
	if toLead1 != 0 || toLead2 != 1 {
		t.Fatalf("after the move: %d lines to pl1, %d to pl2", toLead1, toLead2)
	}
	if success, _ := lastAudit(t, "admin.supervisor_reassigned", cceo, ""); !success {
		t.Fatal("the move was not audited")
	}

	_, err = staffTeams().AssignSupervisor(ctx, authed(&identityv1.AssignSupervisorRequest{
		UserId: cceoUser, SupervisorStaffId: director}, hr))
	requireCode(t, err, connect.CodeInvalidArgument, "")
	if _, err := staffTeams().AssignSupervisor(ctx, authed(&identityv1.AssignSupervisorRequest{
		UserId: cceoUser, SupervisorStaffId: director}, adminSession(t))); err != nil {
		t.Fatalf("an Admin may decide otherwise: %v", err)
	}
}

func TestTheAdminConfiguresAProgramLeadsTeamAndACCEOKeepsOneLead(t *testing.T) {
	ctx := context.Background()
	keepReportingLines(t)
	lead1User, lead1 := staffOf(t, "pl1@edify.org")
	_, lead2 := staffOf(t, "pl2@edify.org")
	_, fromLead2 := aCCEOOf(t, lead2)
	token := adminSession(t)

	team, err := staffTeams().GetManagedTeam(ctx, authed(&identityv1.GetManagedTeamRequest{UserId: lead1User}, token))
	if err != nil || team.Msg.GetRole() != "Program Lead" || team.Msg.GetAutomatic() {
		t.Fatalf("pl1's team: %v %+v", err, team)
	}
	var chosen []string
	sawOtherManager := false
	for _, p := range team.Msg.GetPeople() {
		if p.GetAssigned() {
			chosen = append(chosen, p.GetStaffId())
		}
		if p.GetStaffId() == fromLead2 && p.GetOtherManager() != "" {
			sawOtherManager = true
		}
	}
	if !sawOtherManager {
		t.Fatal("a CCEO of another lead is not shown with that lead")
	}
	chosen = append(chosen, fromLead2)
	done, err := staffTeams().ConfigureManagedTeam(ctx, authed(&identityv1.ConfigureManagedTeamRequest{
		UserId: lead1User, StaffIds: chosen}, token))
	if err != nil || done.Msg.GetAddedCount() != 1 {
		t.Fatalf("configuring: %v %+v", err, done)
	}
	var leads int
	_ = admin.QueryRow(ctx, `
SELECT count(*) FROM staff_supervisor_assignment a JOIN staff_profile sp ON sp.id = a.supervisor_id
JOIN "user" u ON u.id = sp.user_id WHERE a.supervisee_id = $1 AND u.active_role = 'Program Lead'`, fromLead2).Scan(&leads)
	var toLead1 bool
	_ = admin.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM staff_supervisor_assignment WHERE supervisee_id = $1 AND supervisor_id = $2)`,
		fromLead2, lead1).Scan(&toLead1)
	if leads != 1 || !toLead1 {
		t.Fatalf("the moved CCEO has %d Program Leads (pl1: %v)", leads, toLead1)
	}

	directorUser, _ := staffOf(t, "cd@edify.org")
	country, err := staffTeams().GetManagedTeam(ctx, authed(&identityv1.GetManagedTeamRequest{UserId: directorUser}, token))
	if err != nil || !country.Msg.GetAutomatic() {
		t.Fatalf("a Country Director's team is automatic: %v %+v", err, country)
	}
	_, err = staffTeams().ConfigureManagedTeam(ctx, authed(&identityv1.ConfigureManagedTeamRequest{UserId: directorUser}, token))
	requireCode(t, err, connect.CodeInvalidArgument, "")
}

// cleanPartnerTeam removes whatever a test adds to a partner's team.
func cleanPartnerTeam(t *testing.T, partnerID string) {
	t.Helper()
	cleanup := func() {
		ctx := context.Background()
		rows, _ := admin.Query(ctx, `SELECT COALESCE(user_id, '') FROM partner_member WHERE partner_id = $1 AND name LIKE 'Go Test %'`, partnerID)
		var users []string
		for rows.Next() {
			var id string
			if rows.Scan(&id) == nil && id != "" {
				users = append(users, id)
			}
		}
		rows.Close()
		_, _ = admin.Exec(ctx, `DELETE FROM partner_school_member WHERE partner_id = $1`, partnerID)
		_, _ = admin.Exec(ctx, `DELETE FROM partner_member WHERE partner_id = $1 AND name LIKE 'Go Test %'`, partnerID)
		_, _ = admin.Exec(ctx, `UPDATE "user" SET email = 'gone-' || id || '@deleted.invalid' WHERE email LIKE 'go.test.%@partner.test'`)
		for _, id := range users {
			for _, statement := range []string{`DELETE FROM user_invitation WHERE user_id = $1`,
				`DELETE FROM refresh_token WHERE user_id = $1`, `DELETE FROM login_event WHERE user_id = $1`,
				`DELETE FROM "user" WHERE id = $1`} {
				_, _ = admin.Exec(ctx, statement, id)
			}
		}
	}
	cleanup()
	t.Cleanup(cleanup)
}

func TestAPartnerAdminRunsTheirOwnTeam(t *testing.T) {
	ctx := context.Background()
	var partnerID, otherPartner string
	_ = admin.QueryRow(ctx, `SELECT id FROM partner WHERE name = 'Demo Partner Administration'`).Scan(&partnerID)
	_ = admin.QueryRow(ctx, `SELECT id FROM partner WHERE name = 'World Reader'`).Scan(&otherPartner)
	cleanPartnerTeam(t, partnerID)
	borrowAccount(t, "partner-admin@edify.org")
	token := sessionOf(t, "partner-admin@edify.org", seededPassword).GetAccessToken()

	team, err := partnerTeams().GetPartnerTeam(ctx, authed(&identityv1.GetPartnerTeamRequest{}, token))
	if err != nil || team.Msg.GetPartnerId() != partnerID || !team.Msg.GetLeadsTeam() || len(team.Msg.GetSchools()) < 2 {
		t.Fatalf("the Partner Admin's own team: %v %+v", err, team)
	}
	schools := team.Msg.GetSchools()
	_, err = partnerTeams().GetPartnerTeam(ctx, authed(&identityv1.GetPartnerTeamRequest{PartnerId: otherPartner}, token))
	requireCode(t, err, connect.CodePermissionDenied, "")

	add := func(name string) string {
		added, err := partnerTeams().AddMember(ctx, authed(&identityv1.AddMemberRequest{
			PartnerId: partnerID, Name: name, Role: "staff",
			Email: strings.ToLower(strings.ReplaceAll(name, " ", ".")) + "@partner.test"}, token))
		if err != nil {
			t.Fatal(err)
		}
		return added.Msg.GetMember().GetMemberId()
	}
	first, second := add("Go Test Amina"), add("Go Test Brian")

	// One open activity at the first school, delivered by nobody yet.
	var activityID, status, name string
	var assigned *string
	if err := admin.QueryRow(ctx, `SELECT id, status, delivery_contact_name, assigned_partner_id FROM activity
WHERE deleted_at IS NULL AND school_id = $1 LIMIT 1`, schools[0].GetSchoolId()).Scan(&activityID, &status, &name, &assigned); err == nil {
		_, _ = admin.Exec(ctx, `UPDATE activity SET status = 'scheduled', delivery_contact_name = '', assigned_partner_id = $2 WHERE id = $1`,
			activityID, partnerID)
		t.Cleanup(func() {
			_, _ = admin.Exec(context.Background(),
				`UPDATE activity SET status = $2, delivery_contact_name = $3, assigned_partner_id = $4 WHERE id = $1`,
				activityID, status, name, assigned)
		})
	}

	given, err := partnerTeams().SetMemberSchools(ctx, authed(&identityv1.SetMemberSchoolsRequest{
		PartnerId: partnerID, MemberId: first, SchoolIds: []string{schools[0].GetSchoolId(), schools[1].GetSchoolId()}}, token))
	if err != nil || given.Msg.GetGiven() != 2 {
		t.Fatalf("giving two schools: %v %+v", err, given)
	}
	if activityID != "" {
		var named string
		_ = admin.QueryRow(ctx, `SELECT delivery_contact_name FROM activity WHERE id = $1`, activityID).Scan(&named)
		if named != "Go Test Amina" || given.Msg.GetActivitiesNamed() != 1 {
			t.Fatalf("the school's open work names %q (%d named)", named, given.Msg.GetActivitiesNamed())
		}
	}
	moved, err := partnerTeams().SetMemberSchools(ctx, authed(&identityv1.SetMemberSchoolsRequest{
		PartnerId: partnerID, MemberId: second, SchoolIds: []string{schools[0].GetSchoolId()}}, token))
	if err != nil || moved.Msg.GetMoved() != 1 {
		t.Fatalf("moving a school to another member: %v %+v", err, moved)
	}
	if activityID != "" {
		var named string
		_ = admin.QueryRow(ctx, `SELECT delivery_contact_name FROM activity WHERE id = $1`, activityID).Scan(&named)
		if named != "Go Test Brian" {
			t.Fatalf("the open work did not move with its school: %q", named)
		}
	}
	_, err = partnerTeams().SetMemberSchools(ctx, authed(&identityv1.SetMemberSchoolsRequest{
		PartnerId: partnerID, MemberId: second, SchoolIds: []string{"not-a-held-school"}}, token))
	requireCode(t, err, connect.CodeInvalidArgument, "")

	login, err := partnerTeams().CreateMemberLogin(ctx, authed(&identityv1.CreateMemberLoginRequest{
		PartnerId: partnerID, MemberId: first, Password: "Partner#2026x"}, token))
	if err != nil || login.Msg.GetInvited() {
		t.Fatalf("a member's own login: %v %+v", err, login)
	}
	member := sessionOf(t, "go.test.amina@partner.test", "Partner#2026x")
	// Removing a member anonymises the account and keeps it; the test's own
	// account goes once the test is done, or every run would leave another
	// "Go Test Amina" on the Users page.
	t.Cleanup(func() {
		id := member.GetAccount().GetUserId()
		for _, sql := range []string{`DELETE FROM refresh_token WHERE user_id = $1`, `DELETE FROM login_event WHERE user_id = $1`,
			`DELETE FROM "user" WHERE id = $1`} {
			if _, err := admin.Exec(context.Background(), sql, id); err != nil {
				t.Errorf("removing the test member's account: %v", err)
			}
		}
	})
	if member.GetAccount().GetActiveRole() != "PartnerFieldOfficer" {
		t.Fatalf("the member's login works as %q", member.GetAccount().GetActiveRole())
	}
	var staffProfiles int
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM staff_profile WHERE user_id = $1`, member.GetAccount().GetUserId()).Scan(&staffProfiles)
	if staffProfiles != 0 {
		t.Fatal("a partner member was given an Edify staff profile")
	}
	if success, _ := lastAudit(t, "partner.member_login_created", partnerID, ""); !success {
		t.Fatal("the login was not audited")
	}
	// The member's own Field Officer login does not run the team.
	_, err = partnerTeams().GetPartnerTeam(ctx, authed(&identityv1.GetPartnerTeamRequest{}, member.GetAccessToken()))
	requireCode(t, err, connect.CodeFailedPrecondition, "PASSWORD_CHANGE_REQUIRED")

	if _, err := partnerTeams().RemoveMember(ctx, authed(&identityv1.RemoveMemberRequest{PartnerId: partnerID, MemberId: first}, token)); err != nil {
		t.Fatal(err)
	}
	var active bool
	_ = admin.QueryRow(ctx, `SELECT is_active FROM "user" WHERE id = $1`, member.GetAccount().GetUserId()).Scan(&active)
	var left int
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM partner_school_member WHERE member_id = $1`, first).Scan(&left)
	if active || left != 0 {
		t.Fatalf("after removal: login active %v, %d school links left", active, left)
	}
}
