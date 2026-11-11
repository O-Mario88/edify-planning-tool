package acting

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Store reads and writes acting_assignment rows.
type Store struct{ db *pgxpool.Pool }

// NewStore returns a Store over pool.
func NewStore(pool *pgxpool.Pool) *Store { return &Store{db: pool} }

func (s *Store) write(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("acting: opening a transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("acting: committing: %w", err)
	}
	return nil
}

type queryer interface {
	QueryRow(context.Context, string, ...any) pgx.Row
	Query(context.Context, string, ...any) (pgx.Rows, error)
}

// isUniqueViolation is the database's own last word on one standing
// appointment per seat and month, and per person and month.
func isUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}

// seat is a leader's own staff profile: the seat an appointment delegates.
type seat struct {
	StaffID, UserID, Name, Country string
}

const seatSelect = `
SELECT sp.id, sp.user_id, u.name, btrim(COALESCE(sp.country, ''))
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = $1 AND sp.deleted_at IS NULL`

func (s *Store) seat(ctx context.Context, q queryer, staffID string) (*seat, error) {
	if staffID == "" {
		return nil, nil
	}
	var row seat
	err := q.QueryRow(ctx, seatSelect, staffID).Scan(&row.StaffID, &row.UserID, &row.Name, &row.Country)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("acting: reading the seat: %w", err)
	}
	return &row, nil
}

// Candidate is someone a leader may appoint.
type Candidate struct{ StaffID, UserID, Name, Email string }

// eligibleSQL is eligible_appointees: holds the appointee role, a live
// account, not the leader, not an Admin, not already holding the acting
// role, and inside the leader's reach — on their reporting line for a team,
// in their country for a country.
const eligibleSQL = `
SELECT sp.id, sp.user_id, u.name, u.email
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE (u.active_role = $1 OR $1 = ANY(u.roles))
  AND sp.deleted_at IS NULL AND u.deleted_at IS NULL AND u.is_active
  AND sp.id <> $2
  AND NOT ('Admin' = ANY(u.roles))
  AND NOT (u.active_role = $3 OR $3 = ANY(u.roles))
  AND (($4 = 'pl_team' AND sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $2))
    OR ($4 = 'country' AND $5 <> '' AND sp.country = $5))
ORDER BY u.name`

func (s *Store) eligible(ctx context.Context, q queryer, entry Role, leader seat) ([]Candidate, error) {
	rows, err := q.Query(ctx, eligibleSQL, entry.AppointeeRole, leader.StaffID, entry.ActingRole, entry.ScopeType, leader.Country)
	if err != nil {
		return nil, fmt.Errorf("acting: reading who may be appointed: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (Candidate, error) {
		var c Candidate
		err := row.Scan(&c.StaffID, &c.UserID, &c.Name, &c.Email)
		return c, err
	})
}

// seatMembersSQL is _seat_members: the people in the seat on the day.
const seatMembersSQL = `
SELECT sp.id, sp.user_id, u.name
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL
  AND (($1 = 'pl_team' AND sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $2))
    OR ($1 = 'country' AND sp.country = $3 AND (u.active_role = 'Program Lead' OR 'Program Lead' = ANY(u.roles))))
ORDER BY u.name`

func (s *Store) seatMembers(ctx context.Context, q queryer, entry Role, leader seat) ([]any, error) {
	rows, err := q.Query(ctx, seatMembersSQL, entry.ScopeType, leader.StaffID, leader.Country)
	if err != nil {
		return nil, fmt.Errorf("acting: reading the seat's people: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (any, error) {
		var id, userID, name string
		err := row.Scan(&id, &userID, &name)
		return map[string]any{"staff_profile_id": id, "user_id": userID, "name": name}, err
	})
}

// Appointment is one acting_assignment row with the names it shows.
type Appointment struct {
	ID, RoleKey, ActingRole                   string
	AppointeeID, AppointeeName, AppointeeRole string
	AppointedByID, AppointedByName, ByRole    string
	ScopeType, SeatID, SeatName, Country      string
	Start, End                                time.Time
	CancelledAt                               *time.Time
	CancelledByName, CancelReason             string
	Revisions                                 []map[string]any
}

const appointmentSelect = `
SELECT a.id, a.role_key, a.acting_role, a.appointee_id, ap.name, a.appointee_role,
       a.appointed_by_id, ab.name, a.appointed_by_role, a.scope_type, a.seat_id, su.name, a.country,
       a.start_date, a.end_date, a.cancelled_at, COALESCE(cb.name, ''), a.cancel_reason, a.revisions
FROM acting_assignment a
JOIN "user" ap ON ap.id = a.appointee_id
JOIN "user" ab ON ab.id = a.appointed_by_id
JOIN staff_profile sp ON sp.id = a.seat_id
JOIN "user" su ON su.id = sp.user_id
LEFT JOIN "user" cb ON cb.id = a.cancelled_by_id`

func scanAppointment(row pgx.Row) (Appointment, error) {
	var (
		a         Appointment
		revisions []byte
	)
	err := row.Scan(&a.ID, &a.RoleKey, &a.ActingRole, &a.AppointeeID, &a.AppointeeName, &a.AppointeeRole,
		&a.AppointedByID, &a.AppointedByName, &a.ByRole, &a.ScopeType, &a.SeatID, &a.SeatName, &a.Country,
		&a.Start, &a.End, &a.CancelledAt, &a.CancelledByName, &a.CancelReason, &revisions)
	if err != nil {
		return a, err
	}
	if len(revisions) > 0 {
		_ = json.Unmarshal(revisions, &a.Revisions)
	}
	return a, nil
}

// reach is who may read which appointments (visible_to).
type reach struct {
	all             bool
	userID, staffID string
	country         string
	readsTheCountry bool
}

func (r reach) where(first int) (string, []any) {
	if r.all {
		return "true", nil
	}
	if r.staffID == "" {
		return fmt.Sprintf("a.appointee_id = $%d", first), []any{r.userID}
	}
	clause := fmt.Sprintf("(a.appointee_id = $%d OR a.seat_id = $%d OR a.appointed_by_id = $%d", first, first+1, first)
	args := []any{r.userID, r.staffID}
	if r.readsTheCountry && r.country != "" {
		clause += fmt.Sprintf(" OR a.country = $%d", first+2)
		args = append(args, r.country)
	}
	return clause + ")", args
}

func (s *Store) visible(ctx context.Context, r reach) ([]Appointment, error) {
	where, args := r.where(1)
	rows, err := s.db.Query(ctx, appointmentSelect+" WHERE "+where+" ORDER BY a.start_date DESC, a.created_at DESC", args...)
	if err != nil {
		return nil, fmt.Errorf("acting: reading appointments: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (Appointment, error) { return scanAppointment(row) })
}

// oneIn is a single visible appointment; lock takes its row for the change.
func oneIn(ctx context.Context, q queryer, r reach, id string, lock bool) (Appointment, bool, error) {
	where, args := r.where(2)
	query := appointmentSelect + " WHERE a.id = $1 AND " + where
	if lock {
		query += " FOR UPDATE OF a"
	}
	a, err := scanAppointment(q.QueryRow(ctx, query, append([]any{id}, args...)...))
	if errors.Is(err, pgx.ErrNoRows) {
		return a, false, nil
	}
	if err != nil {
		return a, false, fmt.Errorf("acting: reading the appointment: %w", err)
	}
	return a, true, nil
}

// conflictAt is _assert_no_conflict: one standing acting leader per seat and
// month, and one standing appointment per person and month.
func (s *Store) conflictAt(ctx context.Context, q queryer, entry Role, seatID, appointeeID string, start time.Time, ignoreID string) error {
	var name string
	err := q.QueryRow(ctx, `
SELECT u.name FROM acting_assignment a JOIN "user" u ON u.id = a.appointee_id
WHERE a.cancelled_at IS NULL AND a.start_date = $1 AND a.seat_id = $2 AND a.role_key = $3 AND a.id <> $4
LIMIT 1`, start, seatID, entry.Key, ignoreID).Scan(&name)
	if err == nil {
		return conflict(fmt.Sprintf("%s is already %s for %s. Cancel that appointment first.", name, entry.Label, monthLabel(start)))
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return fmt.Errorf("acting: checking the seat's month: %w", err)
	}
	var otherKey string
	err = q.QueryRow(ctx, `
SELECT role_key FROM acting_assignment
WHERE cancelled_at IS NULL AND start_date = $1 AND appointee_id = $2 AND id <> $3
LIMIT 1`, start, appointeeID, ignoreID).Scan(&otherKey)
	if err == nil {
		label := otherKey
		if other, ok := ByKey(otherKey); ok {
			label = other.Label
		}
		return conflict(fmt.Sprintf("This person already holds an acting appointment (%s) for %s.", label, monthLabel(start)))
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return fmt.Errorf("acting: checking the person's month: %w", err)
	}
	return nil
}

// syncHint is sync_hint: User.acting_until is the last day of the person's
// latest standing appointment. The existing application reads no
// appointment for a person whose hint has passed, so this keeps the web in
// step with every appointment made here.
func syncHint(ctx context.Context, tx pgx.Tx, userID string) error {
	_, err := tx.Exec(ctx, `
UPDATE "user" SET acting_until = (
  SELECT max(end_date) FROM acting_assignment WHERE appointee_id = $1 AND cancelled_at IS NULL
) WHERE id = $1`, userID)
	if err != nil {
		return fmt.Errorf("acting: keeping the acting hint: %w", err)
	}
	return nil
}
