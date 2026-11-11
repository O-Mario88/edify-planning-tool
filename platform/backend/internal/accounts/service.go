package accounts

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"net/mail"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accountmail"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/signin"
)

// Refused is a request the rules do not allow, in words for the person.
type Refused struct {
	Message  string
	Conflict bool
}

func (r *Refused) Error() string { return r.Message }

func refuse(message string) error { return &Refused{Message: message} }

// Mailer sends one email; a nil error means the provider accepted it.
type Mailer interface {
	SendMail(ctx context.Context, to, subject, text string) error
}

// Event is a change other parts of the existing application must follow.
type Event struct {
	Kind   string // "roles_changed" or "account_deleted"
	UserID string
}

// EventRelay tells the existing application, which still owns what follows
// an account change: re-pricing the person's planned days at their new post
// (apps/admin_users/services.py _reprice_planned_days), and on removal the
// organisation login it unlinks and the web sessions it ends.
type EventRelay interface {
	Report(ctx context.Context, event Event) error
}

// Deps are the service's collaborators; Mail and Relay may be nil.
type Deps struct {
	Store          *Store
	JWTSecret      []byte
	AccessTokenTTL time.Duration
	ResetTTL       time.Duration
	Mail           Mailer
	Relay          EventRelay
	AppBaseURL     string
	Logger         *slog.Logger
	Now            func() time.Time
}

// Service is accounts.
type Service struct{ deps Deps }

// NewService returns the accounts service.
func NewService(deps Deps) *Service {
	if deps.Now == nil {
		deps.Now = time.Now
	}
	if deps.Logger == nil {
		deps.Logger = slog.Default()
	}
	if deps.AccessTokenTTL == 0 {
		deps.AccessTokenTTL = signin.DefaultPolicy().AccessTokenTTL
	}
	if deps.ResetTTL == 0 {
		deps.ResetTTL = signin.DefaultPolicy().PasswordResetTTL
	}
	deps.AppBaseURL = strings.TrimRight(deps.AppBaseURL, "/")
	return &Service{deps: deps}
}

func actorOf(principal auth.Principal) Actor {
	return Actor{ID: principal.UserID, Role: principal.ActiveRole}
}

// ── The signed-in person's own account ─────────────────────────────────────

// SwitchRole is switch_role_view: only a role the account holds; the
// account's active role is saved, the switch audited, and an access token in
// the new role returned.
func (s *Service) SwitchRole(ctx context.Context, principal auth.Principal, role string) (string, error) {
	now := s.deps.Now()
	if !slices.Contains(principal.Roles, role) {
		s.audit(ctx, audit.Entry{
			Action: "role_switch", SubjectKind: audit.Text("User"), SubjectID: audit.Text(principal.UserID),
			ActorID: audit.Text(principal.UserID), ActorRole: audit.Text(principal.ActiveRole), Success: false,
			Reason:  audit.Text("User attempted to switch to invalid/unassigned role: " + role),
			Payload: map[string]any{"requested_role": role},
		}, now)
		return "", refuse("Access restricted: Invalid role request.")
	}
	err := s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		var old string
		if err := tx.QueryRow(ctx, `SELECT active_role FROM "user" WHERE id = $1 FOR UPDATE`, principal.UserID).Scan(&old); err != nil {
			return fmt.Errorf("accounts: reading the active role: %w", err)
		}
		if _, err := tx.Exec(ctx, `UPDATE "user" SET active_role = $2, updated_at = $3 WHERE id = $1`,
			principal.UserID, role, now); err != nil {
			return fmt.Errorf("accounts: switching role: %w", err)
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action: "role_switch", SubjectKind: audit.Text("User"), SubjectID: audit.Text(principal.UserID),
			ActorID: audit.Text(principal.UserID), ActorRole: audit.Text(role), Success: true,
			Payload: map[string]any{"old_role": old, "new_role": role},
		}, now)
		return err
	})
	if err != nil {
		return "", err
	}
	return signin.IssueAccessToken(s.deps.JWTSecret, principal.UserID, role, now, s.deps.AccessTokenTTL)
}

// SetNewPassword is force_change_password_view: an administrator-chosen
// password is replaced by the person's own, under the policy.
func (s *Service) SetNewPassword(ctx context.Context, principal auth.Principal, password, confirm string) error {
	if !principal.MustChangePassword {
		return refuse("Your password does not need changing here.")
	}
	if password != confirm {
		return refuse("Passwords do not match.")
	}
	if problems := signin.PasswordProblems(password, principal.Email); len(problems) > 0 {
		return refuse(strings.Join(problems, " "))
	}
	encoded, err := signin.EncodePassword(password)
	if err != nil {
		return err
	}
	return s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
UPDATE "user" SET password = $2, must_change_password = false, password_set_at = $3 WHERE id = $1`,
			principal.UserID, encoded, s.deps.Now())
		return err
	})
}

// ── Account administration ────────────────────────────────────────────────

// List is list_users, a page at a time.
func (s *Service) List(ctx context.Context, search, status string, page, pageSize int) ([]Account, int64, error) {
	return s.deps.Store.list(ctx, strings.TrimSpace(search), status, pageSize, (page-1)*pageSize)
}

// Get is one account.
func (s *Service) Get(ctx context.Context, id string) (Account, error) {
	account, err := s.deps.Store.get(ctx, id)
	if errors.Is(err, errNotFound) {
		return Account{}, refuse(msgNotFound)
	}
	return account, err
}

// NewAccount is what the Admin enters.
type NewAccount struct {
	Name, Email, Phone, Role, Password string
	AdditionalRoles                    []string
	PrimaryDistrictID                  string
	AdditionalDistrictIDs              []string
	Country, Department                string
}

// Created is a new account, and its invitation link when no mail provider
// can reach the person.
type Created struct {
	Account        Account
	InvitationLink string
}

// Create is create(): the account, its staff profile and districts, and an
// invitation or a first password that must be changed.
func (s *Service) Create(ctx context.Context, principal auth.Principal, in NewAccount) (Created, error) {
	now := s.deps.Now()
	email := normalEmail(in.Email)
	name := strings.TrimSpace(in.Name)
	if name == "" {
		return Created{}, refuse("name is required.")
	}
	if _, err := mail.ParseAddress(email); err != nil || !strings.Contains(email, "@") {
		return Created{}, refuse("Enter a valid email address.")
	}
	if in.Role == "" {
		return Created{}, refuse(msgRoleRequired)
	}
	roles := rolesOf(in.Role, in.AdditionalRoles)
	if bad := unknownRole(roles); bad != "" {
		return Created{}, refuse(fmt.Sprintf("%q is not a role.", bad))
	}
	if reason := mayAdminister(principal, nil, roles); reason != "" {
		return Created{}, refuse(reason)
	}
	if rbac.AdminIsAlsoCCEO(roles) {
		return Created{}, refuse(msgAdminNotCCEO)
	}
	if in.Password != "" {
		if problems := signin.PasswordProblems(in.Password, email); len(problems) > 0 {
			return Created{}, refuse(strings.Join(problems, " "))
		}
	}
	password, err := storedPassword(in.Password)
	if err != nil {
		return Created{}, err
	}
	country := strings.TrimSpace(in.Country)
	if country == "" {
		country = "Uganda"
	}
	districts := rolesOf(strings.TrimSpace(in.PrimaryDistrictID), in.AdditionalDistrictIDs)

	userID := cuid.New()
	var invitation string
	err = s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		if taken, err := emailTaken(ctx, tx, email, ""); err != nil || taken {
			if err != nil {
				return err
			}
			return &Refused{Message: msgEmailTaken, Conflict: true}
		}
		if missing, err := missingDistrict(ctx, tx, districts); err != nil || missing != "" {
			if err != nil {
				return err
			}
			return refuse(fmt.Sprintf("District %q was not found.", missing))
		}
		status, isActive := statusPending, false
		var passwordSetAt *time.Time
		if in.Password != "" {
			status, isActive, passwordSetAt = statusActive, true, &now
		}
		_, err := tx.Exec(ctx, `
INSERT INTO "user" (id, email, name, phone, password, roles, active_role, status, is_active, password_set_at,
  must_change_password, is_superuser, is_staff, created_at, updated_at, failed_login_count, lockout_cycle_count,
  lockout_escalated, mfa_enabled, mfa_channel, sms_money_alerts, last_seen_path, last_seen_action,
  environment, source)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, false, false, $12, $12, 0, 0, false, false, 'email', true,
  '', '', 'production', 'manual_upload')`,
			userID, email, name, nullable(strings.TrimSpace(in.Phone)), password, roles, in.Role, status, isActive,
			passwordSetAt, in.Password != "", now)
		if isUniqueViolation(err) {
			return &Refused{Message: msgEmailTaken, Conflict: true}
		}
		if err != nil {
			return fmt.Errorf("accounts: creating the account: %w", err)
		}
		staffID := cuid.New()
		_, err = tx.Exec(ctx, `
INSERT INTO staff_profile (id, user_id, title, country, department, primary_district_id, onboarding_state,
  environment, source, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, 'pending', 'production', 'manual_upload', $7, $7)`,
			staffID, userID, in.Role, country, nullable(strings.TrimSpace(in.Department)),
			nullable(strings.TrimSpace(in.PrimaryDistrictID)), now)
		if err != nil {
			return fmt.Errorf("accounts: creating the staff profile: %w", err)
		}
		for _, district := range districts {
			if _, err := tx.Exec(ctx, `
INSERT INTO staff_geography_assignment (id, staff_id, district_id, created_at, updated_at) VALUES ($1, $2, $3, $4, $4)`,
				cuid.New(), staffID, district, now); err != nil {
				return fmt.Errorf("accounts: assigning a district: %w", err)
			}
		}
		if in.Password == "" {
			if invitation, err = newInvitation(ctx, tx, userID, principal.UserID, now); err != nil {
				return err
			}
		}
		_, err = audit.Append(ctx, tx, audit.Entry{
			Action: "admin.user_created", SubjectKind: audit.Text("user"), SubjectID: audit.Text(userID),
			ActorID: audit.Text(principal.UserID), ActorRole: audit.Text(principal.ActiveRole), Success: true,
			Payload: map[string]any{"email": email, "roles": toAny(roles), "invited": in.Password == ""},
		}, now)
		return err
	})
	if err != nil {
		return Created{}, err
	}

	// Sent after the account is committed: a link to an account whose
	// creation rolled back would be a link that cannot work.
	var message accountmail.Message
	if in.Password != "" {
		message = accountmail.AccountCreated(name, principal.Name, s.deps.AppBaseURL+"/login")
	} else {
		message = accountmail.Invitation(name, principal.Name, s.invitationLink(invitation))
	}
	s.send(email, message)

	account, err := s.Get(ctx, userID)
	if err != nil {
		return Created{}, err
	}
	created := Created{Account: account}
	if in.Password == "" && s.deps.Mail == nil {
		created.InvitationLink = s.invitationLink(invitation)
	}
	return created, nil
}

// Changes is what the Admin edits; empty strings are left alone.
type Changes struct {
	Name, Email     string
	Phone           *string
	Role            string
	AdditionalRoles []string
}

// Update is update_user.
func (s *Service) Update(ctx context.Context, principal auth.Principal, id string, in Changes) (Account, error) {
	now := s.deps.Now()
	if in.Role == "" && len(in.AdditionalRoles) > 0 {
		return Account{}, refuse(msgRoleRequired)
	}
	rolesChanged := false
	err := s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		var roles []string
		var email, activeRole string
		err := tx.QueryRow(ctx, `SELECT roles, email, active_role FROM "user" WHERE id = $1 AND deleted_at IS NULL FOR UPDATE`, id).
			Scan(&roles, &email, &activeRole)
		if errors.Is(err, pgx.ErrNoRows) {
			return refuse(msgNotFound)
		}
		if err != nil {
			return err
		}
		if reason := mayAdminister(principal, roles, nil); reason != "" {
			return refuse(reason)
		}
		requested := rolesOf(in.Role, in.AdditionalRoles)
		if in.Role != "" && (in.Role != activeRole || !sameSet(requested, roles)) {
			if id == principal.UserID {
				return refuse(msgOwnRole)
			}
			if bad := unknownRole(requested); bad != "" {
				return refuse(fmt.Sprintf("%q is not a role.", bad))
			}
			if reason := mayAdminister(principal, roles, requested); reason != "" {
				return refuse(reason)
			}
			if rbac.AdminIsAlsoCCEO(requested) {
				return refuse(msgAdminNotCCEO)
			}
			rolesChanged, roles, activeRole = true, requested, in.Role
		}
		if next := normalEmail(in.Email); next != "" && next != email {
			if _, err := mail.ParseAddress(next); err != nil {
				return refuse("Enter a valid email address.")
			}
			taken, err := emailTaken(ctx, tx, next, id)
			if err != nil {
				return err
			}
			if taken {
				return &Refused{Message: msgEmailTaken, Conflict: true}
			}
			email = next
		}
		_, err = tx.Exec(ctx, `
UPDATE "user" SET email = $2, name = COALESCE(NULLIF($3, ''), name), phone = COALESCE($4, phone),
       roles = $5, active_role = $6, updated_at = $7
WHERE id = $1`, id, email, strings.TrimSpace(in.Name), trimmed(in.Phone), roles, activeRole, now)
		if isUniqueViolation(err) {
			return &Refused{Message: msgEmailTaken, Conflict: true}
		}
		if err != nil {
			return fmt.Errorf("accounts: updating: %w", err)
		}
		if rolesChanged {
			// The staff profile's title follows the role, as before.
			if _, err := tx.Exec(ctx, `UPDATE staff_profile SET title = $2, updated_at = $3 WHERE user_id = $1`,
				id, activeRole, now); err != nil {
				return err
			}
		}
		_, err = audit.Append(ctx, tx, audit.Entry{
			Action: "admin.user_updated", SubjectKind: audit.Text("user"), SubjectID: audit.Text(id),
			ActorID: audit.Text(principal.UserID), ActorRole: audit.Text(principal.ActiveRole), Success: true,
			Payload: map[string]any{"email": email, "roles": toAny(roles)},
		}, now)
		return err
	})
	if err != nil {
		return Account{}, err
	}
	if rolesChanged {
		// The post decides a night's rate and whether a district is home
		// (owner, 2026-10-05 and 2026-10-15): open planned days are re-priced.
		s.relay(Event{Kind: "roles_changed", UserID: id})
	}
	return s.Get(ctx, id)
}

// ResendInvitation is resend_invite, for an account still waiting on its
// first password. (The existing code would also re-open an active account
// as invited; that path is not offered here.)
func (s *Service) ResendInvitation(ctx context.Context, principal auth.Principal, id string) (string, error) {
	now := s.deps.Now()
	var raw, email, name string
	err := s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		roles, address, person, err := lockAccount(ctx, tx, id)
		if errors.Is(err, errNotFound) {
			return refuse(msgNotFound)
		}
		if err != nil {
			return err
		}
		email, name = address, person
		if reason := mayAdminister(principal, roles, nil); reason != "" {
			return refuse(reason)
		}
		var status string
		if err := tx.QueryRow(ctx, `SELECT status FROM "user" WHERE id = $1`, id).Scan(&status); err != nil {
			return err
		}
		if status != statusPending {
			return refuse("This account has already been set up. Send a password reset instead.")
		}
		if raw, err = newInvitation(ctx, tx, id, principal.UserID, now); err != nil {
			return err
		}
		_, err = audit.Append(ctx, tx, lifecycle("admin.invite_resent", id, email, actorOf(principal)), now)
		return err
	})
	if err != nil {
		return "", err
	}
	s.send(email, accountmail.Invitation(name, principal.Name, s.invitationLink(raw)))
	if s.deps.Mail == nil {
		return s.invitationLink(raw), nil
	}
	return "", nil
}

// RevokeInvitation is revoke_invite.
func (s *Service) RevokeInvitation(ctx context.Context, principal auth.Principal, id string) error {
	now := s.deps.Now()
	return s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		roles, email, _, err := lockAccount(ctx, tx, id)
		if errors.Is(err, errNotFound) {
			return refuse(msgNotFound)
		}
		if err != nil {
			return err
		}
		if reason := mayAdminister(principal, roles, nil); reason != "" {
			return refuse(reason)
		}
		if _, err := tx.Exec(ctx, `UPDATE user_invitation SET revoked_at = $2 WHERE user_id = $1 AND revoked_at IS NULL`,
			id, now); err != nil {
			return err
		}
		_, err = audit.Append(ctx, tx, lifecycle("admin.invite_revoked", id, email, actorOf(principal)), now)
		return err
	})
}

// SetStatus is suspend / disable / reactivate (_set_status).
func (s *Service) SetStatus(ctx context.Context, principal auth.Principal, id, status string) (Account, error) {
	if status != statusActive && status != statusSuspended && status != statusDisabled {
		return Account{}, refuse("Status must be active, suspended or disabled.")
	}
	now := s.deps.Now()
	active := status == statusActive
	err := s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		roles, email, _, err := lockAccount(ctx, tx, id)
		if errors.Is(err, errNotFound) {
			return refuse(msgNotFound)
		}
		if err != nil {
			return err
		}
		if reason := mayAdminister(principal, roles, nil); reason != "" {
			return refuse(reason)
		}
		if !active {
			// A live invitation is a second way back into a closed account.
			if err := revokeOpenInvitations(ctx, tx, id, now); err != nil {
				return err
			}
		}
		if _, err := tx.Exec(ctx, `UPDATE "user" SET status = $2, is_active = $3 WHERE id = $1`, id, status, active); err != nil {
			return err
		}
		if !active {
			if err := revokeSessions(ctx, tx, id, now); err != nil {
				return err
			}
		}
		_, err = audit.Append(ctx, tx, lifecycle("admin.user_"+status, id, email, actorOf(principal)), now)
		return err
	})
	if err != nil {
		return Account{}, err
	}
	return s.Get(ctx, id)
}

// SendPasswordReset is force_password_reset: a single-use link mailed, and
// every session ended now — the moment a credential may be compromised.
func (s *Service) SendPasswordReset(ctx context.Context, principal auth.Principal, id string) error {
	now := s.deps.Now()
	raw, err := signin.NewToken()
	if err != nil {
		return err
	}
	var email, name string
	err = s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		roles, address, person, err := lockAccount(ctx, tx, id)
		if errors.Is(err, errNotFound) {
			return refuse(msgNotFound)
		}
		if err != nil {
			return err
		}
		email, name = address, person
		if reason := mayAdminister(principal, roles, nil); reason != "" {
			return refuse(reason)
		}
		if _, err := tx.Exec(ctx, `
UPDATE "user" SET password_reset_token_hash = $2, password_reset_expires = $3 WHERE id = $1`,
			id, signin.HashToken(raw), now.Add(s.deps.ResetTTL)); err != nil {
			return err
		}
		if err := revokeSessions(ctx, tx, id, now); err != nil {
			return err
		}
		_, err = audit.Append(ctx, tx, lifecycle("admin.password_reset_forced", id, email, actorOf(principal)), now)
		return err
	})
	if err != nil {
		return err
	}
	s.send(email, accountmail.PasswordReset(name, s.deps.AppBaseURL+"/reset-password?token="+raw, int(s.deps.ResetTTL.Minutes())))
	return nil
}

// SetTemporaryPassword is set_temporary_password: a password the person
// must change, every session ended, any lockout lifted.
func (s *Service) SetTemporaryPassword(ctx context.Context, principal auth.Principal, id, password string) error {
	now := s.deps.Now()
	var email, name string
	err := s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		roles, address, person, err := lockAccount(ctx, tx, id)
		if errors.Is(err, errNotFound) {
			return refuse(msgNotFound)
		}
		if err != nil {
			return err
		}
		email, name = address, person
		if reason := mayAdminister(principal, roles, nil); reason != "" {
			return refuse(reason)
		}
		if problems := signin.PasswordProblems(password, email); len(problems) > 0 {
			return refuse(strings.Join(problems, " "))
		}
		encoded, err := signin.EncodePassword(password)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
UPDATE "user" SET password = $2, must_change_password = true, password_set_at = $3, status = 'active', is_active = true
WHERE id = $1`, id, encoded, now); err != nil {
			return err
		}
		if err := revokeSessions(ctx, tx, id, now); err != nil {
			return err
		}
		if err := unlock(ctx, tx, id, actorOf(principal), now); err != nil {
			return err
		}
		_, err = audit.Append(ctx, tx, lifecycle("admin.password_reset_direct", id, email, actorOf(principal)), now)
		return err
	})
	if err != nil {
		return err
	}
	s.send(email, accountmail.PasswordSetByAdmin(name, principal.Name, s.deps.AppBaseURL+"/login"))
	return nil
}

// Unlock is admin_unlock.
func (s *Service) Unlock(ctx context.Context, principal auth.Principal, id string) error {
	now := s.deps.Now()
	return s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		roles, _, _, err := lockAccount(ctx, tx, id)
		if errors.Is(err, errNotFound) {
			return refuse(msgNotFound)
		}
		if err != nil {
			return err
		}
		if reason := mayAdminister(principal, roles, nil); reason != "" {
			return refuse(reason)
		}
		return unlock(ctx, tx, id, actorOf(principal), now)
	})
}

// Delete is delete_user: the account is soft-deleted and disabled, its
// address freed, its staff profile tombstoned and its sessions ended.
func (s *Service) Delete(ctx context.Context, principal auth.Principal, id string) error {
	now := s.deps.Now()
	if principal.ActiveRole != rbac.Admin {
		return refuse("Only an Admin can delete users.")
	}
	if id == principal.UserID {
		return refuse(msgOwnDelete)
	}
	err := s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		roles, email, name, err := lockAccount(ctx, tx, id)
		if errors.Is(err, errNotFound) {
			return refuse(msgNotFound)
		}
		if err != nil {
			return err
		}
		if slices.Contains(roles, rbac.Admin) {
			var others bool
			if err := tx.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM "user" WHERE deleted_at IS NULL AND is_active AND roles @> ARRAY['Admin']::varchar[] AND id <> $1)`,
				id).Scan(&others); err != nil {
				return err
			}
			if !others {
				return refuse(msgLastAdmin)
			}
		}
		// The email column is unique across tombstones, so the address is
		// freed; the original stays in the audit row.
		if _, err := tx.Exec(ctx, `
UPDATE "user" SET deleted_at = $2, status = 'disabled', is_active = false, email = $3, updated_at = $2 WHERE id = $1`,
			id, now, "deleted-"+id+"@deleted.invalid"); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
UPDATE staff_profile SET deleted_at = $2, updated_at = $2 WHERE user_id = $1 AND deleted_at IS NULL`, id, now); err != nil {
			return err
		}
		if err := revokeSessions(ctx, tx, id, now); err != nil {
			return err
		}
		_, err = audit.Append(ctx, tx, audit.Entry{
			Action: "admin.user_deleted", SubjectKind: audit.Text("user"), SubjectID: audit.Text(id),
			ActorID: audit.Text(principal.UserID), ActorRole: audit.Text(principal.ActiveRole), Success: true,
			Payload: map[string]any{"email": email, "name": name, "roles": toAny(roles)},
		}, now)
		return err
	})
	if err != nil {
		return err
	}
	// The organisation login it was, and the web sessions it holds, are the
	// existing application's to release.
	s.relay(Event{Kind: "account_deleted", UserID: id})
	return nil
}

// ── helpers ───────────────────────────────────────────────────────────────

func (s *Service) invitationLink(raw string) string {
	return s.deps.AppBaseURL + "/set-password?token=" + raw
}

const backgroundTimeout = 30 * time.Second

// send mails after the change has committed; a failed send is logged, and
// the Admin can resend.
func (s *Service) send(to string, message accountmail.Message) {
	if s.deps.Mail == nil || s.deps.AppBaseURL == "" {
		s.deps.Logger.Error("accounts: no mail provider or link address; the email was not sent", "subject", message.Subject)
		return
	}
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), backgroundTimeout)
		defer cancel()
		if err := s.deps.Mail.SendMail(ctx, to, message.Subject, message.Text); err != nil {
			s.deps.Logger.Error("accounts: an email was not sent", "subject", message.Subject, "error", err)
		}
	}()
}

func (s *Service) relay(event Event) {
	if s.deps.Relay == nil {
		s.deps.Logger.Error("accounts: no relay configured; the existing application was not told", "kind", event.Kind)
		return
	}
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), backgroundTimeout)
		defer cancel()
		if err := s.deps.Relay.Report(ctx, event); err != nil {
			s.deps.Logger.Error("accounts: the existing application was not told", "kind", event.Kind, "error", err)
		}
	}()
}

func (s *Service) audit(ctx context.Context, entry audit.Entry, now time.Time) {
	err := s.deps.Store.write(ctx, func(tx pgx.Tx) error {
		_, err := audit.Append(ctx, tx, entry, now)
		return err
	})
	if err != nil {
		s.deps.Logger.Error("accounts: an audit row was not written", "action", entry.Action, "error", err)
	}
}

// storedPassword is the password column for a new account: the chosen
// password, or an unusable one until the invitation is accepted.
func storedPassword(raw string) (string, error) {
	if raw != "" {
		return signin.EncodePassword(raw)
	}
	random := make([]byte, 20)
	if _, err := rand.Read(random); err != nil {
		return "", err
	}
	return "!" + hex.EncodeToString(random), nil
}

func missingDistrict(ctx context.Context, tx pgx.Tx, ids []string) (string, error) {
	for _, id := range ids {
		var found bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM district WHERE id = $1)`, id).Scan(&found); err != nil {
			return "", err
		}
		if !found {
			return id, nil
		}
	}
	return "", nil
}

func sameSet(a, b []string) bool {
	return len(a) == len(b) && !slices.ContainsFunc(a, func(x string) bool { return !slices.Contains(b, x) })
}

func nullable(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func trimmed(s *string) *string {
	if s == nil {
		return nil
	}
	value := strings.TrimSpace(*s)
	return &value
}

func toAny(items []string) []any {
	out := make([]any, len(items))
	for i, item := range items {
		out[i] = item
	}
	return out
}
