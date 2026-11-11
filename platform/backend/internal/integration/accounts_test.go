//go:build integration

package integration

import (
	"context"
	"errors"
	"net/http"
	"regexp"
	"strings"
	"testing"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	schoolsv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1"
)

func accountClient() identityv1connect.AccountServiceClient {
	return identityv1connect.NewAccountServiceClient(http.DefaultClient, baseURL)
}

func adminClient() identityv1connect.AccountAdminServiceClient {
	return identityv1connect.NewAccountAdminServiceClient(http.DefaultClient, baseURL)
}

func identityClient() identityv1connect.IdentityServiceClient {
	return identityv1connect.NewIdentityServiceClient(http.DefaultClient, baseURL)
}

// sessionOf signs an account in through Go and returns its tokens.
func sessionOf(t *testing.T, email, password string) *identityv1.SessionGranted {
	t.Helper()
	result, err := signIn(t, signInClient(t), email, password)
	if err != nil || result.GetSession() == nil {
		t.Fatalf("signing in %s: %v %+v", email, err, result)
	}
	return result.GetSession()
}

// restoreAccount puts an account's roles and lifecycle columns back after a
// test changes them (borrowAccount restores the sign-in columns).
func restoreAccount(t *testing.T, email string) {
	t.Helper()
	var roles []string
	var activeRole, status string
	var isActive, mustChange bool
	if err := admin.QueryRow(context.Background(), `
SELECT roles, active_role, status, is_active, must_change_password FROM "user" WHERE email = $1`, email).
		Scan(&roles, &activeRole, &status, &isActive, &mustChange); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `
UPDATE "user" SET roles = $2, active_role = $3, status = $4, is_active = $5, must_change_password = $6 WHERE email = $1`,
			email, roles, activeRole, status, isActive, mustChange); err != nil {
			t.Errorf("restoring %s: %v", email, err)
		}
	})
}

// removeCreated deletes an account a test creates, with what hangs off it,
// before the test and after it.
func removeCreated(t *testing.T, email string) {
	t.Helper()
	cleanup := func() {
		ctx := context.Background()
		rows, err := admin.Query(ctx, `SELECT id FROM "user" WHERE email = $1 OR name = $2`, email, "Go Test "+email)
		if err != nil {
			return
		}
		var ids []string
		for rows.Next() {
			var id string
			if rows.Scan(&id) == nil {
				ids = append(ids, id)
			}
		}
		rows.Close()
		for _, id := range ids {
			for _, statement := range []string{
				`DELETE FROM staff_geography_assignment WHERE staff_id IN (SELECT id FROM staff_profile WHERE user_id = $1)`,
				`DELETE FROM staff_profile WHERE user_id = $1`, `DELETE FROM user_invitation WHERE user_id = $1`,
				`DELETE FROM refresh_token WHERE user_id = $1`, `DELETE FROM login_event WHERE user_id = $1`,
				`DELETE FROM mfa_challenge WHERE user_id = $1`, `DELETE FROM "user" WHERE id = $1`,
			} {
				_, _ = admin.Exec(ctx, statement, id)
			}
		}
	}
	cleanup()
	t.Cleanup(cleanup)
}

func requireCode(t *testing.T, err error, code connect.Code, reason string) {
	t.Helper()
	var connectErr *connect.Error
	if !errors.As(err, &connectErr) || connectErr.Code() != code {
		t.Fatalf("got %v, want %s", err, code)
	}
	if reason != "" && !hasReason(connectErr, reason) {
		t.Fatalf("got %v, want reason %s", err, reason)
	}
}

func hasReason(err *connect.Error, reason string) bool {
	for _, detail := range err.Details() {
		if strings.Contains(string(detail.Bytes()), reason) {
			return true
		}
	}
	return false
}

func adminSession(t *testing.T) string {
	t.Helper()
	borrowAccount(t, "admin@edify.org")
	return sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
}

func TestAPersonSwitchesToARoleTheyHoldAndNoOther(t *testing.T) {
	ctx := context.Background()
	userID := borrowAccount(t, "cceo17@edify.org")
	restoreAccount(t, "cceo17@edify.org")
	if _, err := admin.Exec(ctx, `UPDATE "user" SET roles = ARRAY['CCEO', 'Program Lead'] WHERE id = $1`, userID); err != nil {
		t.Fatal(err)
	}
	session := sessionOf(t, "cceo17@edify.org", seededPassword)

	switched, err := accountClient().SwitchRole(ctx, authed(&identityv1.SwitchRoleRequest{Role: "Program Lead"}, session.GetAccessToken()))
	if err != nil {
		t.Fatal(err)
	}
	got, err := identityClient().GetSession(ctx, authed(&identityv1.GetSessionRequest{}, switched.Msg.GetAccessToken()))
	if err != nil || got.Msg.GetSession().GetActiveRole() != "Program Lead" {
		t.Fatalf("after the switch: %v %+v", err, got)
	}
	// Saved on the account, so a renewed session stays in the new role.
	rotated, err := signInClient(t).RefreshSession(ctx, connect.NewRequest(&identityv1.RefreshSessionRequest{
		RefreshToken: session.GetRefreshToken()}))
	if err != nil {
		t.Fatal(err)
	}
	got, _ = identityClient().GetSession(ctx, authed(&identityv1.GetSessionRequest{}, rotated.Msg.GetAccessToken()))
	if got.Msg.GetSession().GetActiveRole() != "Program Lead" {
		t.Fatalf("a renewed session fell back to %q", got.Msg.GetSession().GetActiveRole())
	}

	_, err = accountClient().SwitchRole(ctx, authed(&identityv1.SwitchRoleRequest{Role: "Admin"}, switched.Msg.GetAccessToken()))
	requireCode(t, err, connect.CodePermissionDenied, "")
	if success, reason := lastAudit(t, "role_switch", userID, ""); success || !strings.Contains(reason, "Admin") {
		t.Fatalf("the refused switch was audited as %v %q", success, reason)
	}
}

func TestOnlyTheAdminManagesAccounts(t *testing.T) {
	borrowAccount(t, "pl2@edify.org")
	session := sessionOf(t, "pl2@edify.org", seededPassword)
	_, err := adminClient().ListAccounts(context.Background(), authed(&identityv1.ListAccountsRequest{}, session.GetAccessToken()))
	requireCode(t, err, connect.CodePermissionDenied, "")
}

func TestTheAdminInvitesAnAccountThatSetsItsOwnPassword(t *testing.T) {
	ctx := context.Background()
	const email = "go.invited.officer@edify.test"
	removeCreated(t, email)
	token := adminSession(t)

	created, err := adminClient().CreateAccount(ctx, authed(&identityv1.CreateAccountRequest{
		Name: "Go Test " + email, Email: "  GO.Invited.Officer@edify.test ", Role: "CCEO", Department: "Programmes",
	}, token))
	if err != nil {
		t.Fatal(err)
	}
	account := created.Msg.GetAccount()
	if account.GetStatus() != "pending_invited" || account.GetIsActive() || account.GetEmail() != email ||
		account.GetInvitationStatus() != "pending" {
		t.Fatalf("a new invited account: %+v", account)
	}
	var superuser, staff bool
	var title string
	_ = admin.QueryRow(ctx, `
SELECT u.is_superuser, u.is_staff, sp.title FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id WHERE u.id = $1`,
		account.GetUserId()).Scan(&superuser, &staff, &title)
	if superuser || staff || title != "CCEO" {
		t.Fatalf("superuser %v staff %v title %q", superuser, staff, title)
	}
	if success, _ := lastAudit(t, "admin.user_created", account.GetUserId(), ""); !success {
		t.Fatal("the creation was not audited")
	}

	link := regexp.MustCompile(`set-password\?token=([0-9a-f]{64})`).
		FindStringSubmatch(newestMail(t, email, "You have been invited to Edify Planning and Monitoring Tool"))
	if link == nil {
		t.Fatal("the invitation mail holds no link")
	}
	if _, err := signInClient(t).AcceptInvitation(ctx, connect.NewRequest(&identityv1.AcceptInvitationRequest{
		Token: link[1], Password: "Mbarara#2026", Confirm: "Mbarara#2026"})); err != nil {
		t.Fatal(err)
	}
	if _, err := signIn(t, signInClient(t), email, "Mbarara#2026"); err != nil {
		t.Fatalf("the invited person cannot sign in: %v", err)
	}
	_, err = adminClient().CreateAccount(ctx, authed(&identityv1.CreateAccountRequest{
		Name: "Go Test " + email, Email: email, Role: "CCEO"}, token))
	requireCode(t, err, connect.CodeAlreadyExists, "")
}

func TestAFirstPasswordChosenByTheAdminMustBeReplacedFirst(t *testing.T) {
	ctx := context.Background()
	const email = "go.first.password@edify.test"
	removeCreated(t, email)
	token := adminSession(t)
	if _, err := adminClient().CreateAccount(ctx, authed(&identityv1.CreateAccountRequest{
		Name: "Go Test " + email, Email: email, Role: "CCEO", Password: "Temporary#2026"}, token)); err != nil {
		t.Fatal(err)
	}
	newestMail(t, email, "Your account has been created on Edify Planning and Monitoring Tool")

	session := sessionOf(t, email, "Temporary#2026")
	who, err := identityClient().GetSession(ctx, authed(&identityv1.GetSessionRequest{}, session.GetAccessToken()))
	if err != nil || !who.Msg.GetSession().GetMustChangePassword() {
		t.Fatalf("the session does not say a new password is owed: %v", err)
	}
	_, err = schoolsClient().GetMyPortfolioSummary(ctx, authed(&schoolsv1.GetMyPortfolioSummaryRequest{}, session.GetAccessToken()))
	requireCode(t, err, connect.CodeFailedPrecondition, "PASSWORD_CHANGE_REQUIRED")

	_, err = accountClient().SetNewPassword(ctx, authed(&identityv1.SetNewPasswordRequest{Password: "short", Confirm: "short"},
		session.GetAccessToken()))
	requireCode(t, err, connect.CodeInvalidArgument, "")
	if _, err := accountClient().SetNewPassword(ctx, authed(&identityv1.SetNewPasswordRequest{
		Password: "MyOwn#Pass2026", Confirm: "MyOwn#Pass2026"}, session.GetAccessToken())); err != nil {
		t.Fatal(err)
	}
	_, err = schoolsClient().GetMyPortfolioSummary(ctx, authed(&schoolsv1.GetMyPortfolioSummaryRequest{}, session.GetAccessToken()))
	var connectErr *connect.Error
	if errors.As(err, &connectErr) && hasReason(connectErr, "PASSWORD_CHANGE_REQUIRED") {
		t.Fatal("still held at the password change after setting one")
	}
	if _, err := signIn(t, signInClient(t), email, "MyOwn#Pass2026"); err != nil {
		t.Fatalf("the person's own password: %v", err)
	}
}

func TestRolesChangeUnderTheExistingRules(t *testing.T) {
	ctx := context.Background()
	const email = "go.role.change@edify.test"
	removeCreated(t, email)
	token := adminSession(t)
	created, err := adminClient().CreateAccount(ctx, authed(&identityv1.CreateAccountRequest{
		Name: "Go Test " + email, Email: email, Role: "CCEO", Password: "Temporary#2026"}, token))
	if err != nil {
		t.Fatal(err)
	}
	id := created.Msg.GetAccount().GetUserId()

	updated, err := adminClient().UpdateAccount(ctx, authed(&identityv1.UpdateAccountRequest{
		UserId: id, Role: "Program Lead", AdditionalRoles: []string{"CCEO"}}, token))
	if err != nil || updated.Msg.GetAccount().GetActiveRole() != "Program Lead" || len(updated.Msg.GetAccount().GetRoles()) != 2 {
		t.Fatalf("a role change: %v %+v", err, updated)
	}
	var title string
	_ = admin.QueryRow(ctx, `SELECT title FROM staff_profile WHERE user_id = $1`, id).Scan(&title)
	if title != "Program Lead" {
		t.Fatalf("the staff profile's title stayed %q", title)
	}
	_, err = adminClient().UpdateAccount(ctx, authed(&identityv1.UpdateAccountRequest{
		UserId: id, Role: "Admin", AdditionalRoles: []string{"CCEO"}}, token))
	requireCode(t, err, connect.CodeInvalidArgument, "")

	var adminID string
	_ = admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'admin@edify.org'`).Scan(&adminID)
	_, err = adminClient().UpdateAccount(ctx, authed(&identityv1.UpdateAccountRequest{UserId: adminID, Role: "Program Lead"}, token))
	requireCode(t, err, connect.CodeInvalidArgument, "")
}

func TestSuspendingEndsEverySessionAndReactivatingRestoresSignIn(t *testing.T) {
	ctx := context.Background()
	userID := borrowAccount(t, "cceo18@edify.org")
	restoreAccount(t, "cceo18@edify.org")
	victim := sessionOf(t, "cceo18@edify.org", seededPassword)
	token := adminSession(t)

	suspended, err := adminClient().SetAccountStatus(ctx, authed(&identityv1.SetAccountStatusRequest{UserId: userID, Status: "suspended"}, token))
	if err != nil || suspended.Msg.GetAccount().GetIsActive() {
		t.Fatalf("suspending: %v", err)
	}
	_, err = signInClient(t).RefreshSession(ctx, connect.NewRequest(&identityv1.RefreshSessionRequest{RefreshToken: victim.GetRefreshToken()}))
	requireRejected(t, err, "Invalid or expired refresh token.")
	_, err = signIn(t, signInClientAt("10.250.1.18"), "cceo18@edify.org", seededPassword)
	requireRejected(t, err, "Invalid email or password.")

	if _, err := adminClient().SetAccountStatus(ctx, authed(&identityv1.SetAccountStatusRequest{UserId: userID, Status: "active"}, token)); err != nil {
		t.Fatal(err)
	}
	if _, err := signIn(t, signInClientAt("10.250.2.18"), "cceo18@edify.org", seededPassword); err != nil {
		t.Fatalf("after reactivation: %v", err)
	}
}

func TestAnAdministratorLiftsALockAndSetsAPasswordToBeChanged(t *testing.T) {
	ctx := context.Background()
	userID := borrowAccount(t, "cceo19@edify.org")
	restoreAccount(t, "cceo19@edify.org")
	if _, err := admin.Exec(ctx, `UPDATE "user" SET lockout_escalated = true, lockout_cycle_count = 3 WHERE id = $1`, userID); err != nil {
		t.Fatal(err)
	}
	token := adminSession(t)
	shown, err := adminClient().GetAccount(ctx, authed(&identityv1.GetAccountRequest{UserId: userID}, token))
	if err != nil || !shown.Msg.GetAccount().GetLockedUntilAdmin() {
		t.Fatalf("the lock is not shown: %v", err)
	}
	if _, err := adminClient().UnlockAccount(ctx, authed(&identityv1.UnlockAccountRequest{UserId: userID}, token)); err != nil {
		t.Fatal(err)
	}
	if _, err := signIn(t, signInClient(t), "cceo19@edify.org", seededPassword); err != nil {
		t.Fatalf("after the unlock: %v", err)
	}

	if _, err := adminClient().SetTemporaryPassword(ctx, authed(&identityv1.SetTemporaryPasswordRequest{
		UserId: userID, Password: "Handed#Over2026"}, token)); err != nil {
		t.Fatal(err)
	}
	newestMail(t, "cceo19@edify.org", "Your Edify account password has been reset")
	session := sessionOf(t, "cceo19@edify.org", "Handed#Over2026")
	who, _ := identityClient().GetSession(ctx, authed(&identityv1.GetSessionRequest{}, session.GetAccessToken()))
	if !who.Msg.GetSession().GetMustChangePassword() {
		t.Fatal("a password the Admin chose does not have to be changed")
	}
}

func TestRemovingAnAccountFreesItsAddressAndTheLastAdminStays(t *testing.T) {
	ctx := context.Background()
	const email = "go.removed@edify.test"
	removeCreated(t, email)
	token := adminSession(t)
	created, err := adminClient().CreateAccount(ctx, authed(&identityv1.CreateAccountRequest{
		Name: "Go Test " + email, Email: email, Role: "CCEO", Password: "Temporary#2026"}, token))
	if err != nil {
		t.Fatal(err)
	}
	id := created.Msg.GetAccount().GetUserId()
	if _, err := adminClient().DeleteAccount(ctx, authed(&identityv1.DeleteAccountRequest{UserId: id}, token)); err != nil {
		t.Fatal(err)
	}
	var stored string
	var deleted bool
	_ = admin.QueryRow(ctx, `SELECT email, deleted_at IS NOT NULL FROM "user" WHERE id = $1`, id).Scan(&stored, &deleted)
	if !deleted || stored != "deleted-"+id+"@deleted.invalid" {
		t.Fatalf("after removal: %q deleted=%v", stored, deleted)
	}
	_, err = signIn(t, signInClient(t), email, "Temporary#2026")
	requireRejected(t, err, "Invalid email or password.")

	var adminID string
	_ = admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'admin@edify.org'`).Scan(&adminID)
	_, err = adminClient().DeleteAccount(ctx, authed(&identityv1.DeleteAccountRequest{UserId: adminID}, token))
	requireCode(t, err, connect.CodeInvalidArgument, "")
}
