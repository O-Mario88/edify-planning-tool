// Package identity reads accounts from the existing `user` and
// `staff_profile` tables and serves IdentityService.
package identity

import (
	"context"
	"errors"
	"fmt"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Querier is the read the store needs; *pgxpool.Pool satisfies it.
type Querier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Store loads accounts. It never writes.
type Store struct {
	db Querier
}

// NewStore returns a Store reading through db.
func NewStore(db Querier) *Store {
	return &Store{db: db}
}

// The account must be active and not soft-deleted, exactly as the existing
// JWT authentication requires. A soft-deleted staff profile is treated as no
// profile. An acting appointment counts from the day before it starts to the
// day after it ends, so a time-zone difference can only widen the window.
const loadAccountSQL = `
SELECT u.id,
       u.email,
       u.name,
       u.roles,
       u.active_role,
       u.status,
       u.must_change_password,
       COALESCE(sp.id, ''),
       EXISTS (
         SELECT 1 FROM acting_assignment a
         WHERE a.appointee_id = u.id
           AND a.cancelled_at IS NULL
           AND a.expired_at IS NULL
           AND a.start_date <= CURRENT_DATE + 1
           AND a.end_date >= CURRENT_DATE - 1
       )
FROM "user" u
LEFT JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
WHERE u.id = $1
  AND u.is_active
  AND u.deleted_at IS NULL`

// LoadAccount implements auth.AccountLoader.
func (s *Store) LoadAccount(ctx context.Context, userID string) (auth.Account, error) {
	var account auth.Account
	err := s.db.QueryRow(ctx, loadAccountSQL, userID).Scan(
		&account.UserID,
		&account.Email,
		&account.Name,
		&account.Roles,
		&account.ActiveRole,
		&account.Status,
		&account.MustChangePassword,
		&account.StaffProfileID,
		&account.InActingAppointment,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return auth.Account{}, auth.ErrAccountNotFound
	}
	if err != nil {
		return auth.Account{}, fmt.Errorf("identity: loading account: %w", err)
	}
	return account, nil
}

// Service implements edify.identity.v1.IdentityService.
type Service struct{}

// NewService returns the identity service.
func NewService() *Service {
	return &Service{}
}

// GetSession returns the authenticated caller.
func (s *Service) GetSession(
	ctx context.Context, _ *connect.Request[identityv1.GetSessionRequest],
) (*connect.Response[identityv1.GetSessionResponse], error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "Sign in to continue.")
	}
	return connect.NewResponse(&identityv1.GetSessionResponse{
		Session: &identityv1.Session{
			UserId:             principal.UserID,
			Email:              principal.Email,
			Name:               principal.Name,
			Roles:              principal.Roles,
			ActiveRole:         principal.ActiveRole,
			StaffProfileId:     principal.StaffProfileID,
			MustChangePassword: principal.MustChangePassword,
		},
	}), nil
}
