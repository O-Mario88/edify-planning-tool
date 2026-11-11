package signin

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// account is the existing "user" row, as far as signing in needs it.
type account struct {
	ID, Email, Name, Phone string
	Password               string
	Roles                  []string
	ActiveRole, Status     string
	IsActive               bool
	MFAEnabled             bool
	MFAChannel, MFASecret  string
	StaffProfileID         string
	Lockout                Lockout
}

// Store reads and writes sign-in's records. Writes open their own
// read-write transactions: the gateway's database role is read-only unless a
// transaction asks otherwise (deploy/db/roles.sql), and reaches only the
// columns deploy/db/identity_roles.sql grants.
type Store struct {
	db *pgxpool.Pool
}

// NewStore returns a Store on pool.
func NewStore(pool *pgxpool.Pool) *Store { return &Store{db: pool} }

var errNoAccount = errors.New("signin: no such account")

const accountColumns = `
u.id, u.email, u.name, COALESCE(u.phone, ''), COALESCE(u.password, ''), u.roles, u.active_role,
u.status, u.is_active, u.mfa_enabled, u.mfa_channel, COALESCE(u.mfa_secret, ''),
COALESCE((SELECT sp.id FROM staff_profile sp WHERE sp.user_id = u.id AND sp.deleted_at IS NULL LIMIT 1), ''),
u.failed_login_count, u.failed_login_streak_started_at, u.locked_until, u.last_lockout_at,
u.lockout_cycle_count, u.lockout_escalated`

func scanAccount(row pgx.Row) (account, error) {
	var a account
	err := row.Scan(&a.ID, &a.Email, &a.Name, &a.Phone, &a.Password, &a.Roles, &a.ActiveRole,
		&a.Status, &a.IsActive, &a.MFAEnabled, &a.MFAChannel, &a.MFASecret, &a.StaffProfileID,
		&a.Lockout.FailedCount, &a.Lockout.StreakStartedAt, &a.Lockout.LockedUntil, &a.Lockout.LastLockoutAt,
		&a.Lockout.CycleCount, &a.Lockout.Escalated)
	if errors.Is(err, pgx.ErrNoRows) {
		return account{}, errNoAccount
	}
	return a, err
}

// accountByEmail is the existing lookup: the address as typed, lowered and
// trimmed by the caller, on an account that is not soft-deleted.
func (s *Store) accountByEmail(ctx context.Context, email string) (account, error) {
	return scanAccount(s.db.QueryRow(ctx,
		`SELECT `+accountColumns+` FROM "user" u WHERE u.email = $1 AND u.deleted_at IS NULL LIMIT 1`, email))
}

func (s *Store) accountByID(ctx context.Context, id string) (account, error) {
	return scanAccount(s.db.QueryRow(ctx,
		`SELECT `+accountColumns+` FROM "user" u WHERE u.id = $1 AND u.deleted_at IS NULL`, id))
}

// write runs fn in one short read-write transaction.
func (s *Store) write(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("signin: opening a transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("signin: committing: %w", err)
	}
	return nil
}

// appendAudit writes one audit row in its own transaction: an audit failure
// never turns a sign-in answer into an error (the existing audit is best
// effort here too), but it is reported to the caller to log.
func (s *Store) appendAudit(ctx context.Context, entry audit.Entry, now time.Time) error {
	return s.write(ctx, func(tx pgx.Tx) error {
		_, err := audit.Append(ctx, tx, entry, now)
		return err
	})
}

// recordFailure is record_failed_attempt: the row is locked, the policy's
// arithmetic applied, and any lock or escalation audited in the same
// transaction.
func (s *Store) recordFailure(ctx context.Context, userID string, policy Policy, now time.Time) (FailureOutcome, error) {
	var outcome FailureOutcome
	err := s.write(ctx, func(tx pgx.Tx) error {
		var current Lockout
		err := tx.QueryRow(ctx, `
SELECT failed_login_count, failed_login_streak_started_at, locked_until, last_lockout_at,
       lockout_cycle_count, lockout_escalated
FROM "user" WHERE id = $1 FOR UPDATE`, userID).Scan(
			&current.FailedCount, &current.StreakStartedAt, &current.LockedUntil, &current.LastLockoutAt,
			&current.CycleCount, &current.Escalated)
		if err != nil {
			return fmt.Errorf("signin: locking the account: %w", err)
		}
		next, result := policy.AfterFailure(current, now)
		outcome = result
		_, err = tx.Exec(ctx, `
UPDATE "user" SET failed_login_count = $2, failed_login_streak_started_at = $3, locked_until = $4,
       last_lockout_at = $5, lockout_cycle_count = $6, lockout_escalated = $7
WHERE id = $1`, userID, next.FailedCount, next.StreakStartedAt, next.LockedUntil, next.LastLockoutAt,
			next.CycleCount, next.Escalated)
		if err != nil {
			return fmt.Errorf("signin: recording the failure: %w", err)
		}
		if !result.LockStarted && !result.Escalated {
			return nil
		}
		action := "auth.lockout_started"
		if result.Escalated {
			action = "auth.lockout_escalated"
		}
		_, err = audit.Append(ctx, tx, audit.Entry{
			Action: action, SubjectKind: audit.Text("User"), SubjectID: audit.Text(userID),
			ActorID: audit.Text("system"), ActorRole: audit.Text("System"), Success: true,
			Reason: audit.Text(result.Reason),
		}, now)
		return err
	})
	return outcome, err
}

// recordSuccess is record_success. Escalation is never cleared here.
func (s *Store) recordSuccess(ctx context.Context, userID string, now time.Time) error {
	return s.write(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
UPDATE "user" SET failed_login_count = 0, failed_login_streak_started_at = NULL, locked_until = NULL,
       last_login_at = $2
WHERE id = $1`, userID, now)
		return err
	})
}

// Tokens is a session's pair. Only the refresh token's hash is stored.
type Tokens struct {
	AccessToken, RefreshToken string
}

// insertRefreshToken persists a refresh token in a family (a new family for
// a new sign-in; the parent's for a rotation).
func insertRefreshToken(ctx context.Context, tx pgx.Tx, userID, raw, familyID string, parentID *string, expires, now time.Time) error {
	_, err := tx.Exec(ctx, `
INSERT INTO refresh_token (id, user_id, token_hash, family_id, parent_id, expires_at, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $7)`,
		cuid.New(), userID, hashToken(raw), familyID, parentID, expires, now)
	if err != nil {
		return fmt.Errorf("signin: storing the refresh token: %w", err)
	}
	return nil
}

// signInEvent is one successful sign-in, for the Staff Activity Log
// (login_event: "the number of logins per day, per week").
type signInEvent struct {
	UserID, Role, IP, UserAgent string
	// Device is the app's declared form factor; empty reads the browser's.
	Device string
}

// openSession stores a new refresh token and the sign-in's login_event
// together.
func (s *Store) openSession(ctx context.Context, event signInEvent, raw string, expires, now time.Time) error {
	return s.write(ctx, func(tx pgx.Tx) error {
		if err := insertRefreshToken(ctx, tx, event.UserID, raw, cuid.New(), nil, expires, now); err != nil {
			return err
		}
		var ip *string
		if event.IP != "" {
			ip = &event.IP
		}
		device := event.Device
		if device == "" {
			device = deviceCategory(event.UserAgent)
		}
		agent := event.UserAgent
		if len(agent) > 256 {
			agent = agent[:256]
		}
		_, err := tx.Exec(ctx, `
INSERT INTO login_event (id, user_id, at, role, ip, user_agent, device, active_seconds, last_active_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, 0, $3)`,
			cuid.New(), event.UserID, now, event.Role, ip, agent, device)
		if err != nil {
			return fmt.Errorf("signin: recording the sign-in: %w", err)
		}
		return nil
	})
}

// refreshRecord is a stored refresh token with its account's state.
type refreshRecord struct {
	ID, UserID, FamilyID, ActiveRole, Status string
	Usable                                   bool
	Expires                                  time.Time
	Revoked                                  bool
}

// errRefreshRejected covers every refusal: unknown, expired, inactive, reused.
var errRefreshRejected = errors.New("signin: refresh token rejected")

// rotate is refresh(): the token is consumed and its child issued in one
// transaction under the row's lock; a token presented again revokes its whole
// family. reused reports that case, for the caller to audit after the
// revocation has committed.
func (s *Store) rotate(ctx context.Context, raw, nextRaw string, ttl time.Duration, now time.Time) (record refreshRecord, reused bool, err error) {
	err = s.write(ctx, func(tx pgx.Tx) error {
		scanErr := tx.QueryRow(ctx, `
SELECT r.id, r.user_id, r.family_id, r.expires_at, r.revoked_at IS NOT NULL,
       u.active_role, u.status, (u.is_active AND u.deleted_at IS NULL)
FROM refresh_token r JOIN "user" u ON u.id = r.user_id
WHERE r.token_hash = $1
FOR UPDATE OF r`, hashToken(raw)).Scan(&record.ID, &record.UserID, &record.FamilyID, &record.Expires,
			&record.Revoked, &record.ActiveRole, &record.Status, &record.Usable)
		if errors.Is(scanErr, pgx.ErrNoRows) {
			return errRefreshRejected
		}
		if scanErr != nil {
			return fmt.Errorf("signin: reading the refresh token: %w", scanErr)
		}
		if record.Status != "active" || !record.Usable || !record.Expires.After(now) {
			return errRefreshRejected
		}
		if record.Revoked {
			reused = true
			if _, err := tx.Exec(ctx, `UPDATE refresh_token SET reuse_detected_at = $2 WHERE id = $1`, record.ID, now); err != nil {
				return err
			}
			_, err := tx.Exec(ctx,
				`UPDATE refresh_token SET revoked_at = $2 WHERE family_id = $1 AND revoked_at IS NULL`, record.FamilyID, now)
			return err
		}
		if _, err := tx.Exec(ctx,
			`UPDATE refresh_token SET revoked_at = $2, consumed_at = $2 WHERE id = $1`, record.ID, now); err != nil {
			return err
		}
		parent := record.ID
		return insertRefreshToken(ctx, tx, record.UserID, nextRaw, record.FamilyID, &parent, now.Add(ttl), now)
	})
	return record, reused, err
}

// revoke is logout(): the token stops working; the access token expires on
// its own.
func (s *Store) revoke(ctx context.Context, raw string, now time.Time) error {
	return s.write(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`UPDATE refresh_token SET revoked_at = $2 WHERE token_hash = $1 AND revoked_at IS NULL`, hashToken(raw), now)
		return err
	})
}

// deviceCategory is the existing presence.device_category.
func deviceCategory(agent string) string {
	lowered := strings.ToLower(agent)
	switch {
	case lowered == "":
		return ""
	case strings.Contains(lowered, "ipad"), strings.Contains(lowered, "tablet"),
		strings.Contains(lowered, "android") && !strings.Contains(lowered, "mobi"):
		return "tablet"
	case strings.Contains(lowered, "mobi"), strings.Contains(lowered, "iphone"), strings.Contains(lowered, "android"):
		return "mobile"
	}
	return "desktop"
}
