package signin

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
)

// The public answers. An unknown address, a wrong password, a locked or
// inactive account must be indistinguishable (SEC-02); the audit chain is
// where the real reason goes.
var (
	ErrRejected       = errors.New("Invalid email or password.")
	ErrCodeRejected   = errors.New("Invalid or expired verification code")
	ErrSessionExpired = errors.New("Invalid or expired refresh token.")
	ErrResetLink      = errResetLinkInvalid
)

// Mailer and Texter deliver sign-in codes and reset links. A nil error
// means the provider accepted the message.
type Mailer interface {
	SendMail(ctx context.Context, to, subject, text string) error
}

// Texter sends an SMS.
type Texter interface {
	SendText(ctx context.Context, to, text string) error
}

// SecurityEvent is a sign-in event an administrator must hear about.
type SecurityEvent struct {
	Kind   string // "failed_login_threshold" or "lockout_escalated"
	UserID string
	Streak int
	Locked bool
}

// SecurityRelay tells the administrators: it raises the Admin security
// incident and notifies them, through the existing notifications until those
// move to Go.
type SecurityRelay interface {
	Report(ctx context.Context, event SecurityEvent) error
}

// Deps are the service's collaborators; the senders and relay may be nil.
type Deps struct {
	Store      *Store
	Policy     Policy
	JWTSecret  []byte
	FieldKey   FieldKey
	Mail       Mailer
	SMS        Texter
	Relay      SecurityRelay
	AppBaseURL string
	Logger     *slog.Logger
	Now        func() time.Time
}

// Service is sign-in.
type Service struct {
	deps    Deps
	figures figuresCache
}

// NewService returns the sign-in service.
func NewService(deps Deps) *Service {
	if deps.Now == nil {
		deps.Now = time.Now
	}
	if deps.Logger == nil {
		deps.Logger = slog.Default()
	}
	deps.AppBaseURL = strings.TrimRight(deps.AppBaseURL, "/")
	return &Service{deps: deps}
}

// Caller is where a request came from, for the sign-in record. Device is
// the form factor the native app declared, or "".
type Caller struct {
	IP, UserAgent, Device string
}

// Account is who a session belongs to.
type Account struct {
	UserID, Email, Name string
	Roles               []string
	ActiveRole          string
	StaffProfileID      string
}

// Outcome is a sign-in's answer: a session, or a code to enter first.
type Outcome struct {
	Session   *Session
	Challenge *Challenge
}

// Session is an open session.
type Session struct {
	Tokens  Tokens
	Account Account
}

// SignIn is login(): lockout before the password, the lifecycle gate, the
// password, then the second factor or a session.
func (s *Service) SignIn(ctx context.Context, email, password, requestedRole string, caller Caller) (Outcome, error) {
	now := s.deps.Now()
	email = strings.ToLower(strings.TrimSpace(email))
	found, err := s.deps.Store.accountByEmail(ctx, email)
	if errors.Is(err, errNoAccount) {
		BurnPasswordCheck(password)
		s.rejected(ctx, email, nil, "unknown_email", caller, now)
		return Outcome{}, ErrRejected
	}
	if err != nil {
		return Outcome{}, err
	}

	if locked, escalated := found.Lockout.Locked(now); locked {
		// The password is still checked, and ignored, so a locked account
		// answers as slowly as any other.
		BurnPasswordCheck(password)
		reason := "account_locked"
		if escalated {
			reason = "account_locked_escalated"
		}
		s.rejected(ctx, email, &found, reason, caller, now)
		return Outcome{}, ErrRejected
	}
	if found.Status != "active" {
		// A lifecycle problem, not a guess: it does not count as a failure.
		BurnPasswordCheck(password)
		s.rejected(ctx, email, &found, "invalid_password", caller, now)
		return Outcome{}, ErrRejected
	}
	if !PasswordMatches(found.Password, password) || !found.IsActive {
		s.failed(ctx, found, now)
		s.rejected(ctx, email, &found, "invalid_password", caller, now)
		return Outcome{}, ErrRejected
	}
	if err := s.deps.Store.recordSuccess(ctx, found.ID, now); err != nil {
		return Outcome{}, err
	}

	if s.deps.Policy.RequiresSecondFactor(found.MFAEnabled, found.Roles, found.ActiveRole) {
		challenge, err := s.deps.Store.startChallenge(ctx, found, s.deps.SMS != nil, now)
		if errors.Is(err, errChallengeLimit) {
			s.rejected(ctx, email, &found, "mfa_challenge_rate_limited", caller, now)
			return Outcome{}, ErrRejected
		}
		if err != nil {
			return Outcome{}, err
		}
		s.deliverCode(ctx, found, challenge)
		return Outcome{Challenge: &challenge}, nil
	}
	session, err := s.open(ctx, found, requestedRole, caller, now)
	if err != nil {
		return Outcome{}, err
	}
	return Outcome{Session: &session}, nil
}

// VerifyCode is verify_mfa: the code a stopped sign-in waits on.
func (s *Service) VerifyCode(ctx context.Context, clientToken, code, requestedRole string, caller Caller) (Session, error) {
	now := s.deps.Now()
	if clientToken == "" {
		return Session{}, ErrCodeRejected
	}
	result, err := s.deps.Store.checkChallenge(ctx, clientToken, code, now, s.deps.FieldKey.Open)
	if errors.Is(err, errNoChallenge) {
		return Session{}, ErrCodeRejected
	}
	if err != nil {
		return Session{}, err
	}
	found, err := s.deps.Store.accountByID(ctx, result.UserID)
	if err != nil {
		return Session{}, fmt.Errorf("signin: reading the account: %w", err)
	}
	s.audit(ctx, audit.Entry{
		Action: "mfa_verify", SubjectKind: audit.Text("User"), SubjectID: audit.Text(found.ID),
		ActorID: audit.Text(found.ID), ActorRole: audit.Text(found.ActiveRole), Success: result.OK,
		Reason: reasonText(result), Payload: map[string]any{"channel": result.Channel, "surface": "api"},
		IPAddress: audit.Text(caller.IP), UserAgent: audit.Text(caller.UserAgent),
	}, now)
	if !result.OK || found.Status != "active" || !found.IsActive {
		return Session{}, ErrCodeRejected
	}
	return s.open(ctx, found, requestedRole, caller, now)
}

// reasonText is the existing row's reason: "" (not null) for a right code.
func reasonText(result checked) *string {
	reason := result.Reason
	if result.OK {
		reason = ""
	}
	return &reason
}

// Refresh is refresh(): the refresh token is spent and a new pair issued in
// the same family; a token presented twice ends the whole family.
func (s *Service) Refresh(ctx context.Context, refreshToken string) (Tokens, error) {
	now := s.deps.Now()
	if refreshToken == "" {
		return Tokens{}, ErrSessionExpired
	}
	next, err := newRawToken()
	if err != nil {
		return Tokens{}, err
	}
	record, reused, err := s.deps.Store.rotate(ctx, refreshToken, next, s.deps.Policy.RefreshTokenTTL, now)
	if errors.Is(err, errRefreshRejected) {
		return Tokens{}, ErrSessionExpired
	}
	if err != nil {
		return Tokens{}, err
	}
	if reused {
		s.audit(ctx, audit.Entry{
			Action: "auth.refresh_token_reuse_detected", SubjectKind: audit.Text("User"),
			SubjectID: audit.Text(record.UserID), ActorID: audit.Text(record.UserID),
			ActorRole: audit.Text(orUnknown(record.ActiveRole)), Success: false,
			Reason: audit.Text("A refresh token that was already consumed or revoked was presented again — " +
				"the entire token family has been revoked."),
			Payload: map[string]any{"family_id": record.FamilyID, "token_id": record.ID},
		}, now)
		return Tokens{}, ErrSessionExpired
	}
	access, err := issueAccessToken(s.deps.JWTSecret, record.UserID, record.ActiveRole, now, s.deps.Policy.AccessTokenTTL)
	if err != nil {
		return Tokens{}, err
	}
	return Tokens{AccessToken: access, RefreshToken: next}, nil
}

// SignOut is logout(): the refresh token stops working.
func (s *Service) SignOut(ctx context.Context, refreshToken string) error {
	if refreshToken == "" {
		return nil
	}
	return s.deps.Store.revoke(ctx, refreshToken, s.deps.Now())
}

// RequestPasswordReset is forgot_password: a single-use link is mailed when
// the address has an account. The answer is the same either way, and the
// send happens after it, so its time says nothing either.
func (s *Service) RequestPasswordReset(ctx context.Context, email string) error {
	now := s.deps.Now()
	found, err := s.deps.Store.accountByEmail(ctx, strings.ToLower(strings.TrimSpace(email)))
	if errors.Is(err, errNoAccount) {
		return nil
	}
	if err != nil {
		return err
	}
	raw, err := newRawToken()
	if err != nil {
		return err
	}
	if err := s.deps.Store.storeResetToken(ctx, found.ID, raw, now.Add(s.deps.Policy.PasswordResetTTL)); err != nil {
		return err
	}
	if s.deps.Mail == nil || s.deps.AppBaseURL == "" {
		s.deps.Logger.Error("signin: a password reset was requested but no mail provider or link address is configured")
		return nil
	}
	link := s.deps.AppBaseURL + "/reset-password?token=" + raw
	minutes := int(s.deps.Policy.PasswordResetTTL.Minutes())
	// The existing email, word for word (apps/core/email.py send_password_reset).
	text := strings.Join([]string{
		"Hello " + found.Name + ",", "",
		"We received a request to reset your password. You can set a new one here:",
		link, "",
		fmt.Sprintf("This link expires in %d minutes and can only be used once.", minutes), "",
		"If you did not request a password reset, you can safely ignore this email.", "",
		"— Edify Planning and Monitoring Tool",
	}, "\n")
	s.background(func(bg context.Context) {
		if err := s.deps.Mail.SendMail(bg, found.Email, "Reset your Edify Planning password", text); err != nil {
			s.deps.Logger.Error("signin: the password reset email was not sent", "error", err)
		}
	})
	return nil
}

// ResetPassword is reset_password: the policy, the single-use token, and
// every session ended.
func (s *Service) ResetPassword(ctx context.Context, token, password, confirm string) error {
	if password != confirm {
		return PolicyError{"Passwords do not match."}
	}
	if problems := PasswordProblems(password, ""); len(problems) > 0 {
		return PolicyError(problems)
	}
	encoded, err := EncodePassword(password)
	if err != nil {
		return err
	}
	return s.deps.Store.resetPassword(ctx, token, encoded, s.deps.Now())
}

// InvitationState is validate_invite.
type InvitationState struct {
	Valid       bool
	Reason      string
	Email, Name string
}

// CheckInvitation reports an invitation's state without spending it.
func (s *Service) CheckInvitation(ctx context.Context, token string) (InvitationState, error) {
	inv, reason, err := s.deps.Store.inviteState(ctx, token, s.deps.Now())
	if err != nil {
		return InvitationState{}, err
	}
	if reason != "" {
		return InvitationState{Reason: reason}, nil
	}
	return InvitationState{Valid: true, Email: inv.Email, Name: inv.Name}, nil
}

// AcceptInvitation is set_password: a first password from an invitation.
func (s *Service) AcceptInvitation(ctx context.Context, token, password, confirm string) error {
	if password != confirm {
		return PolicyError{"Passwords do not match."}
	}
	_, err := s.deps.Store.acceptInvitation(ctx, token, password, s.deps.Now())
	return err
}

// SignInFigures are the four public figures.
func (s *Service) SignInFigures(ctx context.Context) (Figures, error) {
	return s.deps.Store.figures(ctx, &s.figures, s.deps.Now())
}

// open issues a session: the requested role when the account holds it,
// otherwise its own; a new refresh token family; the sign-in recorded.
func (s *Service) open(ctx context.Context, a account, requestedRole string, caller Caller, now time.Time) (Session, error) {
	role := a.ActiveRole
	for _, held := range a.Roles {
		if requestedRole != "" && held == requestedRole {
			role = requestedRole
		}
	}
	access, err := issueAccessToken(s.deps.JWTSecret, a.ID, role, now, s.deps.Policy.AccessTokenTTL)
	if err != nil {
		return Session{}, err
	}
	refresh, err := newRawToken()
	if err != nil {
		return Session{}, err
	}
	event := signInEvent{UserID: a.ID, Role: role, IP: caller.IP, UserAgent: caller.UserAgent, Device: caller.Device}
	if err := s.deps.Store.openSession(ctx, event, refresh, now.Add(s.deps.Policy.RefreshTokenTTL), now); err != nil {
		return Session{}, err
	}
	return Session{
		Tokens: Tokens{AccessToken: access, RefreshToken: refresh},
		Account: Account{UserID: a.ID, Email: a.Email, Name: a.Name, Roles: a.Roles, ActiveRole: role,
			StaffProfileID: a.StaffProfileID},
	}, nil
}

// failed records a wrong password and tells the administrators what the
// policy says they must hear.
func (s *Service) failed(ctx context.Context, a account, now time.Time) {
	outcome, err := s.deps.Store.recordFailure(ctx, a.ID, s.deps.Policy, now)
	if err != nil {
		s.deps.Logger.Error("signin: a failed sign-in was not recorded", "error", err)
		return
	}
	var events []SecurityEvent
	if outcome.AlertStreak == s.deps.Policy.AlertThreshold {
		events = append(events, SecurityEvent{Kind: "failed_login_threshold", UserID: a.ID,
			Streak: outcome.AlertStreak, Locked: outcome.LockStarted || outcome.Escalated})
	}
	if outcome.Escalated {
		events = append(events, SecurityEvent{Kind: "lockout_escalated", UserID: a.ID})
	}
	if len(events) == 0 {
		return
	}
	if s.deps.Relay == nil {
		s.deps.Logger.Error("signin: a security event has no relay configured", "events", len(events))
		return
	}
	s.background(func(bg context.Context) {
		for _, event := range events {
			if err := s.deps.Relay.Report(bg, event); err != nil {
				s.deps.Logger.Error("signin: a security event was not delivered", "kind", event.Kind, "error", err)
			}
		}
	})
}

// rejected audits a refused sign-in with its real reason.
func (s *Service) rejected(ctx context.Context, email string, a *account, reason string, caller Caller, now time.Time) {
	entry := audit.Entry{
		Action: "auth.login_failed", SubjectKind: audit.Text("User"), ActorID: audit.Text("anonymous"),
		ActorRole: audit.Text("Unknown"), Success: false, Reason: audit.Text(reason),
		Payload: map[string]any{"email": email}, IPAddress: audit.Text(caller.IP), UserAgent: audit.Text(caller.UserAgent),
	}
	if a != nil {
		entry.SubjectID, entry.ActorID, entry.ActorRole = audit.Text(a.ID), audit.Text(a.ID), audit.Text(orUnknown(a.ActiveRole))
	}
	s.audit(ctx, entry, now)
}

func (s *Service) audit(ctx context.Context, entry audit.Entry, now time.Time) {
	if err := s.deps.Store.appendAudit(ctx, entry, now); err != nil {
		s.deps.Logger.Error("signin: an audit row was not written", "action", entry.Action, "error", err)
	}
}

// deliverCode sends a sign-in code; an authenticator app needs nothing.
func (s *Service) deliverCode(ctx context.Context, a account, c Challenge) {
	minutes := int(codeTTL.Minutes())
	var err error
	switch c.Channel {
	case channelApp:
		return
	case channelSMS:
		err = s.deps.SMS.SendText(ctx, c.destination, fmt.Sprintf(
			"%s is your Edify sign-in code. It expires in %d minutes. If this was not you, change your password.",
			c.code, minutes))
	default:
		if s.deps.Mail == nil {
			err = errors.New("no mail provider is configured")
			break
		}
		err = s.deps.Mail.SendMail(ctx, c.destination, "Your Edify sign-in code", strings.Join([]string{
			"Hello " + a.Name + ",", "", "Your sign-in code is:", "", "    " + c.code, "",
			fmt.Sprintf("It expires in %d minutes and can be used once.", minutes), "",
			"If you did not try to sign in, someone else may know your password — change it as soon as you can.",
			"", "— Edify Planning and Monitoring Tool",
		}, "\n"))
	}
	if err != nil {
		s.deps.Logger.Error("signin: a sign-in code could not be sent", "channel", c.Channel, "error", err)
	}
}

// backgroundTimeout bounds work that outlives the request (a send).
const backgroundTimeout = 30 * time.Second

func (s *Service) background(fn func(context.Context)) {
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), backgroundTimeout)
		defer cancel()
		fn(ctx)
	}()
}

func orUnknown(role string) string {
	if role == "" {
		return "Unknown"
	}
	return role
}
