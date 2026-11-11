//go:build integration

package integration

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
)

// The seeded accounts' password (the existing application's demo seed).
const seededPassword = "edify"

func signInClient(t *testing.T) identityv1connect.SignInServiceClient {
	t.Helper()
	return signInClientAt(testClient(t))
}

// signInClientAt sends every request from one client address, so rate
// limits apply per test (or per address within a test).
func signInClientAt(address string) identityv1connect.SignInServiceClient {
	return identityv1connect.NewSignInServiceClient(&http.Client{Transport: forwardedFor{address}}, baseURL)
}

type forwardedFor struct{ address string }

func (f forwardedFor) RoundTrip(request *http.Request) (*http.Response, error) {
	request = request.Clone(request.Context())
	request.Header.Set("X-Forwarded-For", f.address)
	request.Header.Set("User-Agent", "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0) Edify/1.0")
	return http.DefaultTransport.RoundTrip(request)
}

// borrowAccount hands a test one seeded account and puts every sign-in
// column of it back afterwards, so tests cannot leak a lock or a password.
func borrowAccount(t *testing.T, email string) string {
	t.Helper()
	ctx := context.Background()
	var id, password string
	if err := admin.QueryRow(ctx, `SELECT id, password FROM "user" WHERE email = $1`, email).Scan(&id, &password); err != nil {
		t.Fatalf("seeded account %s: %v", email, err)
	}
	t.Cleanup(func() {
		_, err := admin.Exec(context.Background(), `
UPDATE "user" SET password = $2, failed_login_count = 0, failed_login_streak_started_at = NULL, locked_until = NULL,
       last_lockout_at = NULL, lockout_cycle_count = 0, lockout_escalated = false, mfa_enabled = false,
       mfa_channel = 'email', password_reset_token_hash = NULL, password_reset_expires = NULL
WHERE id = $1`, id, password)
		if err != nil {
			t.Errorf("restoring %s: %v", email, err)
		}
	})
	return id
}

func signIn(t *testing.T, client identityv1connect.SignInServiceClient, email, password string) (*identityv1.SignInResponse, error) {
	t.Helper()
	response, err := client.SignIn(context.Background(), connect.NewRequest(&identityv1.SignInRequest{Email: email, Password: password}))
	if err != nil {
		return nil, err
	}
	return response.Msg, nil
}

func requireRejected(t *testing.T, err error, want string) {
	t.Helper()
	var connectErr *connect.Error
	if !errors.As(err, &connectErr) || connectErr.Code() != connect.CodeUnauthenticated || connectErr.Message() != want {
		t.Fatalf("got %v, want Unauthenticated %q", err, want)
	}
}

// lastAudit reads the newest audit row of action about subject (an account
// id) or, with subject empty, about the address in its payload.
func lastAudit(t *testing.T, action, subject, email string) (success bool, reason string) {
	t.Helper()
	var reasonPtr *string
	err := admin.QueryRow(context.Background(), `
SELECT success, reason FROM audit_log
WHERE action = $1 AND (($2 <> '' AND subject_id = $2) OR ($2 = '' AND payload->>'email' = $3))
ORDER BY seq DESC NULLS LAST LIMIT 1`, action, subject, email).Scan(&success, &reasonPtr)
	if err != nil {
		t.Fatalf("no %s audit for %s%s: %v", action, subject, email, err)
	}
	if reasonPtr != nil {
		reason = *reasonPtr
	}
	return success, reason
}

func TestASeededAccountSignsInThroughGoAndItsSessionWorksEverywhere(t *testing.T) {
	ctx := context.Background()
	userID := borrowAccount(t, "cceo10@edify.org")
	client := signInClient(t)
	var before int
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM login_event WHERE user_id = $1`, userID).Scan(&before)

	result, err := signIn(t, client, "  CCEO10@edify.org ", seededPassword)
	if err != nil {
		t.Fatal(err)
	}
	session := result.GetSession()
	if session == nil || session.GetAccount().GetUserId() != userID || session.GetAccount().GetActiveRole() != "CCEO" {
		t.Fatalf("session: %+v", result)
	}

	// The access token is the existing one: the gateway's own session check
	// accepts it, as the existing application's would.
	got, err := identityv1connect.NewIdentityServiceClient(http.DefaultClient, baseURL).GetSession(ctx,
		authed(&identityv1.GetSessionRequest{}, session.GetAccessToken()))
	if err != nil || got.Msg.GetSession().GetUserId() != userID {
		t.Fatalf("the new access token was not honoured: %v", err)
	}

	var after int
	var device string
	_ = admin.QueryRow(ctx, `SELECT count(*), coalesce(max(device), '') FROM login_event WHERE user_id = $1`, userID).Scan(&after, &device)
	if after != before+1 || device != "mobile" {
		t.Fatalf("login_event: %d → %d (%q); the Staff Activity Log counts sign-ins", before, after, device)
	}
	var stored string
	_ = admin.QueryRow(ctx, `SELECT token_hash FROM refresh_token WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1`, userID).Scan(&stored)
	if stored != sha256Hex(session.GetRefreshToken()) {
		t.Fatal("the refresh token is not stored as its hash")
	}
}

func TestARefreshTokenIsSpentOnceAndPresentingItAgainEndsTheFamily(t *testing.T) {
	ctx := context.Background()
	userID := borrowAccount(t, "cceo11@edify.org")
	client := signInClient(t)
	result, err := signIn(t, client, "cceo11@edify.org", seededPassword)
	if err != nil {
		t.Fatal(err)
	}
	first := result.GetSession().GetRefreshToken()

	rotated, err := client.RefreshSession(ctx, connect.NewRequest(&identityv1.RefreshSessionRequest{RefreshToken: first}))
	if err != nil || rotated.Msg.GetRefreshToken() == first || rotated.Msg.GetAccessToken() == "" {
		t.Fatalf("rotation: %v", err)
	}
	second := rotated.Msg.GetRefreshToken()

	// The spent token again: theft. Refused, and the live child dies with it.
	_, err = client.RefreshSession(ctx, connect.NewRequest(&identityv1.RefreshSessionRequest{RefreshToken: first}))
	requireRejected(t, err, "Invalid or expired refresh token.")
	_, err = client.RefreshSession(ctx, connect.NewRequest(&identityv1.RefreshSessionRequest{RefreshToken: second}))
	requireRejected(t, err, "Invalid or expired refresh token.")
	if success, _ := lastAudit(t, "auth.refresh_token_reuse_detected", userID, ""); success {
		t.Fatal("the reuse was audited as a success")
	}
}

func TestSigningOutEndsTheSessionOnTheServer(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "cceo12@edify.org")
	client := signInClient(t)
	result, err := signIn(t, client, "cceo12@edify.org", seededPassword)
	if err != nil {
		t.Fatal(err)
	}
	refresh := result.GetSession().GetRefreshToken()
	if _, err := client.SignOut(ctx, connect.NewRequest(&identityv1.SignOutRequest{RefreshToken: refresh})); err != nil {
		t.Fatal(err)
	}
	_, err = client.RefreshSession(ctx, connect.NewRequest(&identityv1.RefreshSessionRequest{RefreshToken: refresh}))
	requireRejected(t, err, "Invalid or expired refresh token.")
}

func TestEveryRefusalReadsTheSameAndTheRealReasonIsAudited(t *testing.T) {
	userID := borrowAccount(t, "cceo13@edify.org")
	client := signInClient(t)

	_, err := signIn(t, client, "nobody-at-all@edify.org", seededPassword)
	requireRejected(t, err, "Invalid email or password.")
	if _, reason := lastAudit(t, "auth.login_failed", "", "nobody-at-all@edify.org"); reason != "unknown_email" {
		t.Fatalf("an unknown address was audited as %q", reason)
	}

	_, err = signIn(t, client, "cceo13@edify.org", "not-the-password")
	requireRejected(t, err, "Invalid email or password.")
	if success, reason := lastAudit(t, "auth.login_failed", userID, ""); success || reason != "invalid_password" {
		t.Fatalf("audited as %v %q", success, reason)
	}
}

func TestTenWrongPasswordsLockTheAccountAgainstTheRightOne(t *testing.T) {
	ctx := context.Background()
	userID := borrowAccount(t, "cceo14@edify.org")
	client := signInClient(t)
	for i := 0; i < 10; i++ {
		_, err := signIn(t, client, "cceo14@edify.org", "wrong-"+strconv.Itoa(i))
		requireRejected(t, err, "Invalid email or password.")
	}
	var lockedUntil *time.Time
	_ = admin.QueryRow(ctx, `SELECT locked_until FROM "user" WHERE id = $1`, userID).Scan(&lockedUntil)
	if lockedUntil == nil || time.Until(*lockedUntil) < 14*time.Minute {
		t.Fatalf("locked until %v; the policy locks for 15 minutes", lockedUntil)
	}
	if _, reason := lastAudit(t, "auth.lockout_started", userID, ""); !strings.Contains(reason, "locked 15 minute") {
		t.Fatalf("lockout audit reason %q", reason)
	}
	// The right password, inside the lock, from another address (this one has
	// spent its ten a minute): the same answer, and why is audited.
	_, err := signIn(t, signInClientAt("10.250.0.14"), "cceo14@edify.org", seededPassword)
	requireRejected(t, err, "Invalid email or password.")
	if _, reason := lastAudit(t, "auth.login_failed", userID, ""); reason != "account_locked" {
		t.Fatalf("a sign-in inside the lock was audited as %q", reason)
	}
}

func TestAnAddressIsHeldToTenAttemptsAMinute(t *testing.T) {
	client := signInClient(t)
	var err error
	for i := 0; i < 11; i++ {
		_, err = signIn(t, client, "nobody-at-all@edify.org", "x")
	}
	var connectErr *connect.Error
	if !errors.As(err, &connectErr) || connectErr.Code() != connect.CodeResourceExhausted {
		t.Fatalf("the eleventh attempt in a minute: %v", err)
	}
}

// codeLine is the line of a sign-in code mail that holds the code.
var codeLine = regexp.MustCompile(`(?m)^    (\d{6})\r?$`)

func newestMail(t *testing.T, address, subject string) string {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		entries, _ := os.ReadDir(mailbox)
		sort.Slice(entries, func(i, j int) bool { return entries[i].Name() > entries[j].Name() })
		for _, entry := range entries {
			raw, err := os.ReadFile(filepath.Join(mailbox, entry.Name()))
			if err == nil && strings.Contains(string(raw), "To: "+address+"\r\n") &&
				strings.Contains(string(raw), "Subject: "+subject+"\r\n") {
				return string(raw)
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("no %q mail to %s", subject, address)
	return ""
}

func TestAnEnrolledAccountEntersTheMailedCodeBeforeItsSession(t *testing.T) {
	ctx := context.Background()
	userID := borrowAccount(t, "cceo15@edify.org")
	if _, err := admin.Exec(ctx, `UPDATE "user" SET mfa_enabled = true, mfa_channel = 'email' WHERE id = $1`, userID); err != nil {
		t.Fatal(err)
	}
	client := signInClient(t)
	result, err := signIn(t, client, "cceo15@edify.org", seededPassword)
	if err != nil {
		t.Fatal(err)
	}
	required := result.GetCodeRequired()
	if required == nil || result.GetSession() != nil {
		t.Fatalf("an enrolled account got a session without its code: %+v", result)
	}
	if required.GetChannel() != "email" || required.GetDestinationHint() != "c•••••@edify.org" ||
		required.GetExpiresInSeconds() != 600 {
		t.Fatalf("challenge: %+v", required)
	}
	match := codeLine.FindStringSubmatch(newestMail(t, "cceo15@edify.org", "Your Edify sign-in code"))
	if match == nil {
		t.Fatal("the mail holds no code")
	}

	wrong := "000000"
	if match[1] == wrong {
		wrong = "111111"
	}
	_, err = client.VerifySignInCode(ctx, connect.NewRequest(&identityv1.VerifySignInCodeRequest{
		ChallengeToken: required.GetChallengeToken(), Code: wrong}))
	requireRejected(t, err, "Invalid or expired verification code")

	verified, err := client.VerifySignInCode(ctx, connect.NewRequest(&identityv1.VerifySignInCodeRequest{
		ChallengeToken: required.GetChallengeToken(), Code: match[1]}))
	if err != nil || verified.Msg.GetSession().GetAccount().GetUserId() != userID {
		t.Fatalf("the right code: %v", err)
	}
	// Spent: the same code does not open a second session.
	_, err = client.VerifySignInCode(ctx, connect.NewRequest(&identityv1.VerifySignInCodeRequest{
		ChallengeToken: required.GetChallengeToken(), Code: match[1]}))
	requireRejected(t, err, "Invalid or expired verification code")
	if success, _ := lastAudit(t, "mfa_verify", userID, ""); !success {
		t.Fatal("the right code was not audited as a success")
	}
}

func TestAResetLinkSetsANewPasswordOnceAndEndsEverySession(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "cceo16@edify.org")
	client := signInClient(t)
	old, err := signIn(t, client, "cceo16@edify.org", seededPassword)
	if err != nil {
		t.Fatal(err)
	}

	if _, err := client.RequestPasswordReset(ctx, connect.NewRequest(&identityv1.RequestPasswordResetRequest{
		Email: "cceo16@edify.org"})); err != nil {
		t.Fatal(err)
	}
	// An unknown address gets the very same answer.
	if _, err := client.RequestPasswordReset(ctx, connect.NewRequest(&identityv1.RequestPasswordResetRequest{
		Email: "nobody-at-all@edify.org"})); err != nil {
		t.Fatal(err)
	}
	link := regexp.MustCompile(`reset-password\?token=([0-9a-f]{64})`).
		FindStringSubmatch(newestMail(t, "cceo16@edify.org", "Reset your Edify Planning password"))
	if link == nil {
		t.Fatal("the mail holds no reset link")
	}

	_, err = client.ResetPassword(ctx, connect.NewRequest(&identityv1.ResetPasswordRequest{
		Token: link[1], Password: "weak", Confirm: "weak"}))
	var policy *connect.Error
	if !errors.As(err, &policy) || policy.Code() != connect.CodeInvalidArgument ||
		!strings.Contains(policy.Message(), "at least 8 characters") {
		t.Fatalf("a weak password: %v", err)
	}
	if _, err := client.ResetPassword(ctx, connect.NewRequest(&identityv1.ResetPasswordRequest{
		Token: link[1], Password: "Kampala#2026", Confirm: "Kampala#2026"})); err != nil {
		t.Fatal(err)
	}
	_, err = client.ResetPassword(ctx, connect.NewRequest(&identityv1.ResetPasswordRequest{
		Token: link[1], Password: "Kampala#2027", Confirm: "Kampala#2027"}))
	if err == nil || !strings.Contains(err.Error(), "invalid or has expired") {
		t.Fatalf("the link worked twice: %v", err)
	}

	_, err = client.RefreshSession(ctx, connect.NewRequest(&identityv1.RefreshSessionRequest{
		RefreshToken: old.GetSession().GetRefreshToken()}))
	requireRejected(t, err, "Invalid or expired refresh token.")
	if _, err := signIn(t, client, "cceo16@edify.org", "Kampala#2026"); err != nil {
		t.Fatalf("the new password: %v", err)
	}
	var stored string
	_ = admin.QueryRow(ctx, `SELECT password FROM "user" WHERE email = 'cceo16@edify.org'`).Scan(&stored)
	if !strings.HasPrefix(stored, "bcrypt$$2") {
		t.Fatalf("the new password is stored as %q…, not the existing application's format", stored[:10])
	}
}

func TestAnInvitationSetsTheFirstPasswordAndIsSpent(t *testing.T) {
	ctx := context.Background()
	const email = "invited.go@edify.test"
	userID, raw := "cgoinvite0000000000000001", "go-invitation-token-0123456789abcdef"
	cleanup := func() {
		for _, statement := range []string{
			`DELETE FROM user_invitation WHERE user_id = $1`, `DELETE FROM refresh_token WHERE user_id = $1`,
			`DELETE FROM login_event WHERE user_id = $1`, `DELETE FROM "user" WHERE id = $1`,
		} {
			_, _ = admin.Exec(context.Background(), statement, userID)
		}
	}
	cleanup()
	t.Cleanup(cleanup)
	_, err := admin.Exec(ctx, `
INSERT INTO "user" (id, email, name, roles, active_role, status, is_active, password, is_superuser, is_staff,
  created_at, updated_at, failed_login_count, mfa_enabled, environment, source, must_change_password,
  lockout_cycle_count, lockout_escalated, mfa_channel, sms_money_alerts, last_seen_path, last_seen_action)
VALUES ($1, $2, 'Invited Go', ARRAY['CCEO'], 'CCEO', 'pending', false, '!unusable', false, false,
  now(), now(), 0, false, 'demo', 'manual', false, 0, false, 'email', false, '', '')`, userID, email)
	if err != nil {
		t.Fatal(err)
	}
	var inviter string
	_ = admin.QueryRow(ctx, `SELECT id FROM "user" WHERE email = 'admin@edify.org'`).Scan(&inviter)
	_, err = admin.Exec(ctx, `
INSERT INTO user_invitation (id, user_id, invited_by_id, token_hash, expires_at, created_at, updated_at)
VALUES ('cgoinvitation00000000001', $1, $2, $3, now() + interval '7 days', now(), now())`,
		userID, inviter, sha256Hex(raw))
	if err != nil {
		t.Fatal(err)
	}
	client := signInClient(t)

	state, err := client.CheckInvitation(ctx, connect.NewRequest(&identityv1.CheckInvitationRequest{Token: raw}))
	if err != nil || !state.Msg.GetValid() || state.Msg.GetEmail() != email {
		t.Fatalf("a fresh invitation: %+v %v", state, err)
	}
	if _, err := client.AcceptInvitation(ctx, connect.NewRequest(&identityv1.AcceptInvitationRequest{
		Token: raw, Password: "Gulu#2026x", Confirm: "Gulu#2026x"})); err != nil {
		t.Fatal(err)
	}
	if _, err := signIn(t, client, email, "Gulu#2026x"); err != nil {
		t.Fatalf("the invited account cannot sign in: %v", err)
	}
	state, err = client.CheckInvitation(ctx, connect.NewRequest(&identityv1.CheckInvitationRequest{Token: raw}))
	if err != nil || state.Msg.GetValid() || state.Msg.GetReason() != "used" {
		t.Fatalf("a spent invitation: %+v %v", state, err)
	}
	if success, _ := lastAudit(t, "auth.invite_accepted", userID, ""); !success {
		t.Fatal("the acceptance was not audited")
	}
}

func TestTheSignInFiguresAreTheExistingCounts(t *testing.T) {
	ctx := context.Background()
	figures, err := signInClient(t).GetSignInFigures(ctx, connect.NewRequest(&identityv1.GetSignInFiguresRequest{}))
	if err != nil {
		t.Fatal(err)
	}
	var portfolio int64
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM school WHERE deleted_at IS NULL AND operational_status IN ('active', 'reopened')`).Scan(&portfolio)
	want := strconv.FormatInt(portfolio, 10)
	if len(want) > 3 {
		want = want[:len(want)-3] + "," + want[len(want)-3:]
	}
	if figures.Msg.GetPortfolio() != want || figures.Msg.GetSchoolsReached() != want {
		t.Fatalf("figures %+v, portfolio %d", figures.Msg, portfolio)
	}
}

// TestEveryRowGoAddedKeepsTheChainVerifiable recomputes, from the database,
// the hash of the newest audit rows with the existing verifier's rule; a row
// Go wrote that the existing verifier would reject fails here.
func TestEveryRowGoAddedKeepsTheChainVerifiable(t *testing.T) {
	ctx := context.Background()
	rows, err := admin.Query(ctx, `
SELECT seq, action, subject_kind, subject_id, actor_id, actor_role, success, reason, ip_address, user_agent,
       correlation_id, payload, prev_hash, hash
FROM audit_log WHERE seq IS NOT NULL ORDER BY seq DESC LIMIT 400`)
	if err != nil {
		t.Fatal(err)
	}
	type row struct {
		seq        int64
		entry      audit.Entry
		prev, hash *string
		payload    []byte
	}
	var all []row
	for rows.Next() {
		var r row
		if err := rows.Scan(&r.seq, &r.entry.Action, &r.entry.SubjectKind, &r.entry.SubjectID, &r.entry.ActorID,
			&r.entry.ActorRole, &r.entry.Success, &r.entry.Reason, &r.entry.IPAddress, &r.entry.UserAgent,
			&r.entry.CorrelationID, &r.payload, &r.prev, &r.hash); err != nil {
			t.Fatal(err)
		}
		all = append(all, r)
	}
	if rows.Err() != nil || len(all) < 2 {
		t.Fatalf("too little chain to check: %v", rows.Err())
	}
	checked := 0
	for i := 0; i < len(all)-1; i++ {
		current, previous := all[i], all[i+1]
		if current.seq != previous.seq+1 || current.prev == nil || previous.hash == nil || *current.prev != *previous.hash {
			t.Fatalf("seq %d does not follow seq %d", current.seq, previous.seq)
		}
		if len(current.payload) > 0 {
			if err := json.Unmarshal(current.payload, &current.entry.Payload); err != nil {
				t.Fatal(err)
			}
		}
		canonical, err := audit.Canonical(current.entry)
		if err != nil {
			continue // a payload Go never writes (a fraction); the existing verifier owns it
		}
		if audit.ChainHash(*current.prev, canonical) != *current.hash {
			t.Fatalf("seq %d (%s) does not hash to its stored hash", current.seq, current.entry.Action)
		}
		checked++
	}
	if checked == 0 {
		t.Fatal("no row was checked")
	}
}

func sha256Hex(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}
