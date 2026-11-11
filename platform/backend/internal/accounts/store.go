package accounts

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/signin"
)

// Account is an account as the Admin sees it.
type Account struct {
	ID, Name, Email, Phone string
	Roles                  []string
	ActiveRole, Status     string
	IsActive               bool
	LastSignInAt           *time.Time
	PasswordSet            bool
	MustChangePassword     bool
	InvitationStatus       string
	InvitationExpiresAt    *time.Time
	LockedUntil            *time.Time
	LockedUntilAdmin       bool
}

// Locked says whether the account cannot sign in now because of a lockout.
func (a Account) Locked(now time.Time) bool {
	return a.LockedUntilAdmin || (a.LockedUntil != nil && a.LockedUntil.After(now))
}

// Store reads and writes accounts. Writes open their own read-write
// transactions and reach only what deploy/db/identity_roles.sql grants.
type Store struct {
	db *pgxpool.Pool
}

// NewStore returns a Store on pool.
func NewStore(pool *pgxpool.Pool) *Store { return &Store{db: pool} }

var errNotFound = errors.New("accounts: no such account")

// The latest invitation's state, as list_users words it.
const accountSelect = `
SELECT u.id, u.name, u.email, COALESCE(u.phone, ''), u.roles, u.active_role, u.status, u.is_active,
       u.last_login_at, u.password_set_at IS NOT NULL, u.must_change_password,
       CASE WHEN i.id IS NULL THEN ''
            WHEN i.accepted_at IS NOT NULL THEN 'accepted'
            WHEN i.revoked_at IS NOT NULL THEN 'revoked'
            WHEN i.expires_at < now() THEN 'expired'
            ELSE 'pending' END,
       i.expires_at, u.locked_until, u.lockout_escalated
FROM "user" u
LEFT JOIN LATERAL (
  SELECT id, accepted_at, revoked_at, expires_at FROM user_invitation
  WHERE user_id = u.id ORDER BY created_at DESC LIMIT 1
) i ON true`

func scanAccount(row pgx.Row) (Account, error) {
	var a Account
	err := row.Scan(&a.ID, &a.Name, &a.Email, &a.Phone, &a.Roles, &a.ActiveRole, &a.Status, &a.IsActive,
		&a.LastSignInAt, &a.PasswordSet, &a.MustChangePassword, &a.InvitationStatus, &a.InvitationExpiresAt,
		&a.LockedUntil, &a.LockedUntilAdmin)
	if errors.Is(err, pgx.ErrNoRows) {
		return Account{}, errNotFound
	}
	return a, err
}

// list is list_users, paged and searchable, newest first.
func (s *Store) list(ctx context.Context, search, status string, limit, offset int) ([]Account, int64, error) {
	where := `WHERE u.deleted_at IS NULL
  AND ($1 = '' OR u.name ILIKE '%' || $1 || '%' OR u.email ILIKE '%' || $1 || '%')
  AND ($2 = '' OR u.status = $2)`
	var total int64
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM "user" u `+where, search, status).Scan(&total); err != nil {
		return nil, 0, fmt.Errorf("accounts: counting: %w", err)
	}
	rows, err := s.db.Query(ctx, accountSelect+` `+where+` ORDER BY u.created_at DESC, u.id LIMIT $3 OFFSET $4`,
		search, status, limit, offset)
	if err != nil {
		return nil, 0, fmt.Errorf("accounts: listing: %w", err)
	}
	defer rows.Close()
	var out []Account
	for rows.Next() {
		account, err := scanAccount(rows)
		if err != nil {
			return nil, 0, err
		}
		out = append(out, account)
	}
	return out, total, rows.Err()
}

func (s *Store) get(ctx context.Context, id string) (Account, error) {
	return scanAccount(s.db.QueryRow(ctx, accountSelect+` WHERE u.id = $1 AND u.deleted_at IS NULL`, id))
}

func (s *Store) write(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("accounts: opening a transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("accounts: committing: %w", err)
	}
	return nil
}

// lockAccount reads an account's roles and email under its row lock.
func lockAccount(ctx context.Context, tx pgx.Tx, id string) (roles []string, email, name string, err error) {
	err = tx.QueryRow(ctx, `SELECT roles, email, name FROM "user" WHERE id = $1 AND deleted_at IS NULL FOR UPDATE`, id).
		Scan(&roles, &email, &name)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, "", "", errNotFound
	}
	return roles, email, name, err
}

// Actor is who an audit row says did it.
type Actor struct {
	ID, Role string
}

// lifecycle is _audit_lifecycle: subject the account, payload its email.
func lifecycle(action, userID, email string, actor Actor) audit.Entry {
	return audit.Entry{
		Action: action, SubjectKind: audit.Text("user"), SubjectID: audit.Text(userID),
		ActorID: audit.Text(actor.ID), ActorRole: audit.Text(actor.Role), Success: true,
		Payload: map[string]any{"email": email},
	}
}

// emailTaken reports whether another live account holds email.
func emailTaken(ctx context.Context, tx pgx.Tx, email, except string) (bool, error) {
	var taken bool
	err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM "user" WHERE email = $1 AND deleted_at IS NULL AND id <> $2)`,
		email, except).Scan(&taken)
	return taken, err
}

// isUniqueViolation is the email key refusing a second account.
func isUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}

// newInvitation stores a fresh invitation (7 days) and returns its raw token.
func newInvitation(ctx context.Context, tx pgx.Tx, userID, invitedBy string, now time.Time) (string, error) {
	raw, err := signin.NewToken()
	if err != nil {
		return "", err
	}
	_, err = tx.Exec(ctx, `
INSERT INTO user_invitation (id, user_id, invited_by_id, token_hash, expires_at, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $6)`, cuid.New(), userID, invitedBy, signin.HashToken(raw), now.Add(invitationTTL), now)
	if err != nil {
		return "", fmt.Errorf("accounts: storing the invitation: %w", err)
	}
	return raw, nil
}

const invitationTTL = 7 * 24 * time.Hour

func revokeSessions(ctx context.Context, tx pgx.Tx, userID string, now time.Time) error {
	_, err := tx.Exec(ctx, `UPDATE refresh_token SET revoked_at = $2 WHERE user_id = $1 AND revoked_at IS NULL`, userID, now)
	return err
}

func revokeOpenInvitations(ctx context.Context, tx pgx.Tx, userID string, now time.Time) error {
	_, err := tx.Exec(ctx, `
UPDATE user_invitation SET revoked_at = $2 WHERE user_id = $1 AND accepted_at IS NULL AND revoked_at IS NULL`, userID, now)
	return err
}

// unlock is admin_unlock: every lockout column cleared, and audited.
func unlock(ctx context.Context, tx pgx.Tx, userID string, actor Actor, now time.Time) error {
	if _, err := tx.Exec(ctx, `
UPDATE "user" SET failed_login_count = 0, failed_login_streak_started_at = NULL, locked_until = NULL,
       lockout_cycle_count = 0, lockout_escalated = false
WHERE id = $1`, userID); err != nil {
		return fmt.Errorf("accounts: unlocking: %w", err)
	}
	_, err := audit.Append(ctx, tx, audit.Entry{
		Action: "auth.admin_unlock", SubjectKind: audit.Text("User"), SubjectID: audit.Text(userID),
		ActorID: audit.Text(orSystem(actor.ID)), ActorRole: audit.Text(orSystemRole(actor.Role)), Success: true,
		Reason: audit.Text("Administrator manually unlocked the account."),
	}, now)
	return err
}

func orSystem(id string) string {
	if id == "" {
		return "system"
	}
	return id
}

func orSystemRole(role string) string {
	if role == "" {
		return "System"
	}
	return role
}

// normalEmail is the existing normalisation: trimmed and lower-cased.
func normalEmail(email string) string { return strings.ToLower(strings.TrimSpace(email)) }
