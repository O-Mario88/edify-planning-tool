// Package identity reads accounts from the existing `user` and
// `staff_profile` tables and serves IdentityService.
package identity

import (
	"context"
	"errors"
	"fmt"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/acting"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Querier is the read the store needs; *pgxpool.Pool satisfies it.
type Querier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Store loads accounts. It never writes.
type Store struct {
	db  Querier
	now func() time.Time
}

// NewStore returns a Store reading through db.
func NewStore(db Querier) *Store {
	return &Store{db: db, now: time.Now}
}

// The account must be active and not soft-deleted, exactly as the existing
// JWT authentication requires. A soft-deleted staff profile is treated as no
// profile.
//
// The acting appointment is the one active today ($2, the platform's day)
// that still stands on the people it names (apps.acting.services
// .still_valid): the appointee holds the role it was made from and is not an
// Admin; the seat and its leader are live and the leader still holds the
// appointing role; a country seat has a country. Its labels come from the
// policy (acting.ByKey), so an entry the policy no longer has grants nothing.
const loadAccountSQL = `
SELECT u.id,
       u.email,
       u.name,
       u.roles,
       u.active_role,
       u.status,
       u.must_change_password,
       COALESCE(sp.id, ''),
       COALESCE(a.id, ''),
       COALESCE(a.role_key, ''),
       COALESCE(a.start_date, DATE '0001-01-01'),
       COALESCE(a.seat_id, ''),
       COALESCE(a.seat_name, ''),
       COALESCE(a.country, ''),
       COALESCE(a.in_capacity, false)
FROM "user" u
LEFT JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
LEFT JOIN LATERAL (
  SELECT x.id, x.role_key, x.start_date, x.seat_id, x.in_capacity,
         lu.name AS seat_name, btrim(seat.country) AS country
  FROM acting_assignment x
  JOIN staff_profile seat ON seat.id = x.seat_id AND seat.deleted_at IS NULL
  JOIN "user" lu ON lu.id = seat.user_id AND lu.deleted_at IS NULL AND lu.is_active
  WHERE x.appointee_id = u.id
    AND x.cancelled_at IS NULL
    AND x.start_date <= $2::date
    AND x.end_date >= $2::date
    AND x.appointee_role = ANY(u.roles)
    AND NOT ('Admin' = ANY(u.roles))
    AND (lu.active_role = x.appointed_by_role OR x.appointed_by_role = ANY(lu.roles))
    AND (x.scope_type <> 'country' OR btrim(seat.country) <> '')
  ORDER BY x.start_date DESC
  LIMIT 1
) a ON true
WHERE u.id = $1
  AND u.is_active
  AND u.deleted_at IS NULL`

// LoadAccount implements auth.AccountLoader.
func (s *Store) LoadAccount(ctx context.Context, userID string) (auth.Account, error) {
	var (
		account auth.Account
		row     struct {
			id, key, seatID, seatName, country string
			start                              time.Time
			inCapacity                         bool
		}
	)
	today := acting.Today(s.now()).Format("2006-01-02")
	err := s.db.QueryRow(ctx, loadAccountSQL, userID, today).Scan(
		&account.UserID,
		&account.Email,
		&account.Name,
		&account.Roles,
		&account.ActiveRole,
		&account.Status,
		&account.MustChangePassword,
		&account.StaffProfileID,
		&row.id, &row.key, &row.start, &row.seatID, &row.seatName, &row.country, &row.inCapacity,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return auth.Account{}, auth.ErrAccountNotFound
	}
	if err != nil {
		return auth.Account{}, fmt.Errorf("identity: loading account: %w", err)
	}
	if entry, ok := acting.ByKey(row.key); ok && row.id != "" {
		account.Acting = &auth.ActingAppointment{
			AppointmentID: row.id, RoleKey: entry.Key, ActingRole: entry.ActingRole, AppointeeRole: entry.AppointeeRole,
			Label: entry.Label, ShortLabel: entry.ShortLabel, MonthLabel: row.start.Format("January 2006"),
			SeatStaffID: row.seatID, SeatName: row.seatName, ScopeType: entry.ScopeType, Country: row.country,
			InCapacity: row.inCapacity,
		}
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
			Acting:             acting.CapacityOf(principal.Acting),
		},
	}), nil
}
