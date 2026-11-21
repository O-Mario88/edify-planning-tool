package signin

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
)

// Invitation states, the existing validate_invite reasons.
const (
	inviteInvalid = "invalid"
	inviteRevoked = "revoked"
	inviteUsed    = "used"
	inviteExpired = "expired"
)

// errResetLinkInvalid: unknown, used or expired reset token.
var errResetLinkInvalid = errors.New("This reset link is invalid or has expired.")

// storeResetToken is forgot_password's write: the account's reset token is
// replaced by a new one (hashed) that expires after ttl.
func (s *Store) storeResetToken(ctx context.Context, userID, raw string, expires time.Time) error {
	return s.write(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`UPDATE "user" SET password_reset_token_hash = $2, password_reset_expires = $3 WHERE id = $1`,
			userID, hashToken(raw), expires)
		return err
	})
}

// resetPassword is reset_password's write: under the account's row lock the
// token is checked and spent, the password replaced, and every refresh token
// revoked so the old sessions end everywhere.
func (s *Store) resetPassword(ctx context.Context, raw, encoded string, now time.Time) error {
	return s.write(ctx, func(tx pgx.Tx) error {
		var (
			id      string
			expires *time.Time
		)
		err := tx.QueryRow(ctx, `
SELECT id, password_reset_expires FROM "user"
WHERE password_reset_token_hash = $1 AND deleted_at IS NULL
LIMIT 1 FOR UPDATE`, hashToken(raw)).Scan(&id, &expires)
		if errors.Is(err, pgx.ErrNoRows) || (err == nil && (expires == nil || expires.Before(now))) {
			return errResetLinkInvalid
		}
		if err != nil {
			return fmt.Errorf("signin: reading the reset token: %w", err)
		}
		if _, err := tx.Exec(ctx, `
UPDATE "user" SET password = $2, password_reset_token_hash = NULL, password_reset_expires = NULL,
       password_set_at = $3,
       failed_login_count = CASE WHEN COALESCE(lockout_escalated, false) THEN failed_login_count ELSE 0 END,
       failed_login_streak_started_at = CASE WHEN COALESCE(lockout_escalated, false) THEN failed_login_streak_started_at ELSE NULL END,
       locked_until = CASE WHEN COALESCE(lockout_escalated, false) THEN locked_until ELSE NULL END,
       lockout_cycle_count = CASE WHEN COALESCE(lockout_escalated, false) THEN lockout_cycle_count ELSE 0 END
WHERE id = $1`, id, encoded, now); err != nil {
			return fmt.Errorf("signin: setting the password: %w", err)
		}
		_, err = tx.Exec(ctx, `UPDATE refresh_token SET revoked_at = $2 WHERE user_id = $1 AND revoked_at IS NULL`, id, now)
		return err
	})
}

// invitation is a user_invitation row with its account.
type invitation struct {
	ID, UserID, Email, Name, Status, ActiveRole string
	Expires                                     time.Time
	Accepted, Revoked                           bool
}

func (s *Store) invitationByToken(ctx context.Context, q pgx.Row) (invitation, error) {
	var inv invitation
	err := q.Scan(&inv.ID, &inv.UserID, &inv.Email, &inv.Name, &inv.Status, &inv.ActiveRole,
		&inv.Expires, &inv.Accepted, &inv.Revoked)
	return inv, err
}

const invitationQuery = `
SELECT i.id, i.user_id, u.email, u.name, u.status, u.active_role, i.expires_at,
       i.accepted_at IS NOT NULL, i.revoked_at IS NOT NULL
FROM user_invitation i JOIN "user" u ON u.id = i.user_id
WHERE i.token_hash = $1`

// inviteState is validate_invite: the invitation's state without spending it.
func (s *Store) inviteState(ctx context.Context, raw string, now time.Time) (invitation, string, error) {
	inv, err := s.invitationByToken(ctx, s.db.QueryRow(ctx, invitationQuery, hashToken(raw)))
	if errors.Is(err, pgx.ErrNoRows) {
		return invitation{}, inviteInvalid, nil
	}
	if err != nil {
		return invitation{}, "", fmt.Errorf("signin: reading the invitation: %w", err)
	}
	return inv, invitationReason(inv, now), nil
}

func invitationReason(inv invitation, now time.Time) string {
	switch {
	case inv.Revoked:
		return inviteRevoked
	case inv.Accepted:
		return inviteUsed
	case inv.Expires.Before(now):
		return inviteExpired
	}
	return ""
}

// InvitationRefusal is a reason an invitation cannot be accepted, in the
// existing words.
type InvitationRefusal string

func (r InvitationRefusal) Error() string { return string(r) }

var invitationRefusals = map[string]InvitationRefusal{
	inviteInvalid: "This invitation link is invalid.",
	inviteRevoked: "This invitation has been revoked.",
	inviteUsed:    "This invitation has already been used.",
	inviteExpired: "This invitation has expired.",
}

const refusalInactiveAccount InvitationRefusal = "This account is not active. Contact an administrator."

// acceptInvitation is set_password's write: under the invitation's lock the
// password is set, the account activated and the invitation spent. The staff
// profile is activated too, unless an open onboarding plan still gates it.
func (s *Store) acceptInvitation(ctx context.Context, raw, password string, now time.Time) (invitation, error) {
	var inv invitation
	err := s.write(ctx, func(tx pgx.Tx) error {
		found, err := s.invitationByToken(ctx, tx.QueryRow(ctx, invitationQuery+` FOR UPDATE OF i`, hashToken(raw)))
		if errors.Is(err, pgx.ErrNoRows) {
			return invitationRefusals[inviteInvalid]
		}
		if err != nil {
			return fmt.Errorf("signin: reading the invitation: %w", err)
		}
		inv = found
		if reason := invitationReason(inv, now); reason != "" {
			return invitationRefusals[reason]
		}
		if inv.Status == "suspended" || inv.Status == "disabled" {
			return refusalInactiveAccount
		}
		if problems := PasswordProblems(password, inv.Email); len(problems) > 0 {
			return PolicyError(problems)
		}
		encoded, err := EncodePassword(password)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
UPDATE "user" SET password = $2, password_set_at = $3, status = 'active', is_active = true WHERE id = $1`,
			inv.UserID, encoded, now); err != nil {
			return fmt.Errorf("signin: setting the first password: %w", err)
		}
		if _, err := tx.Exec(ctx, `UPDATE user_invitation SET accepted_at = $2 WHERE id = $1`, inv.ID, now); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `
UPDATE staff_profile sp SET onboarding_state = 'active', updated_at = $2
WHERE sp.user_id = $1 AND sp.deleted_at IS NULL AND sp.onboarding_state = 'pending'
  AND NOT EXISTS (SELECT 1 FROM hr_onboarding_plan p WHERE p.staff_id = sp.id AND p.status <> 'closed')`,
			inv.UserID, now)
		if err != nil {
			return fmt.Errorf("signin: activating the staff profile: %w", err)
		}
		_, err = audit.Append(ctx, tx, audit.Entry{
			Action: "auth.invite_accepted", SubjectKind: audit.Text("user"), SubjectID: audit.Text(inv.UserID),
			ActorID: audit.Text(inv.UserID), ActorRole: audit.Text(inv.ActiveRole), Success: true,
			Payload: map[string]any{"email": inv.Email},
		}, now)
		return err
	})
	return inv, err
}

// PolicyError is a new password the policy refuses; its message is the
// existing one (the problems joined by spaces).
type PolicyError []string

func (p PolicyError) Error() string {
	out := ""
	for i, problem := range p {
		if i > 0 {
			out += " "
		}
		out += problem
	}
	return out
}
