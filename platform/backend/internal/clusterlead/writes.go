package clusterlead

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// The portal's writes. Each opens a read-write transaction on purpose (the
// gateway's role is read-only by default) and can reach only the tables
// edify_cluster_rw was granted: an assignment and its event are written
// together or not at all, and nothing is ever deleted.

// NewAssignment is what a new assignment needs.
type NewAssignment struct {
	ID         string
	ClusterID  string
	UserID     string
	StartsOn   time.Time
	EndsOn     *time.Time
	ActorID    string
	Reason     string
	ReplacesID string
}

// CreateAssignment records a and its "assigned" event.
func (s *Store) CreateAssignment(ctx context.Context, a NewAssignment) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		return insertAssignment(ctx, tx, a)
	})
}

// EndAssignment ends a live assignment on day, keeping it and its history.
func (s *Store) EndAssignment(ctx context.Context, id, actorID, reason string, day time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		return endAssignment(ctx, tx, id, actorID, reason, "ended", day)
	})
}

// ReplaceAssignment ends the assignment id and records next, which names it
// as the one it replaced, in one transaction.
func (s *Store) ReplaceAssignment(ctx context.Context, id string, next NewAssignment, day time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if err := endAssignment(ctx, tx, id, next.ActorID, next.Reason, "replaced", day); err != nil {
			return err
		}
		next.ReplacesID = id
		return insertAssignment(ctx, tx, next)
	})
}

func (s *Store) inWrite(ctx context.Context, work func(pgx.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("clusterlead: beginning a write: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := work(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("clusterlead: committing a write: %w", err)
	}
	return nil
}

func insertAssignment(ctx context.Context, tx pgx.Tx, a NewAssignment) error {
	var replaces any
	if a.ReplacesID != "" {
		replaces = a.ReplacesID
	}
	_, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.leader_assignment
  (id, cluster_id, user_id, starts_on, ends_on, status, assigned_by, assigned_reason, replaces_assignment_id, country_code)
VALUES ($1, $2, $3, $4, $5, 'active', $6, $7, $8, `+registry.ClusterCountryCode("$2")+`)`,
		a.ID, a.ClusterID, a.UserID, a.StartsOn, a.EndsOn, a.ActorID, a.Reason, replaces)
	if isUniqueViolation(err) {
		return ErrAlreadyAssigned
	}
	if err != nil {
		return fmt.Errorf("clusterlead: recording an assignment: %w", err)
	}
	return appendEvent(ctx, tx, a.ID, "assigned", a.ActorID, a.Reason)
}

func endAssignment(ctx context.Context, tx pgx.Tx, id, actorID, reason, event string, day time.Time) error {
	// It ends today; an assignment that had not started yet ends on its start.
	tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.leader_assignment
SET status = 'ended', ended_by = $2, ended_reason = $3, ended_at = now(),
    ends_on = GREATEST(starts_on, LEAST(COALESCE(ends_on, $4::date), $4::date))
WHERE id::text = $1 AND status <> 'ended'`, id, actorID, reason, day)
	if err != nil {
		return fmt.Errorf("clusterlead: ending an assignment: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrNotLive
	}
	return appendEvent(ctx, tx, id, event, actorID, reason)
}

func appendEvent(ctx context.Context, tx pgx.Tx, assignmentID, event, actorID, reason string) error {
	_, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.assignment_event (assignment_id, event, actor_id, reason, country_code)
VALUES ($1, $2, $3, $4, (SELECT a.country_code FROM cluster_leadership.leader_assignment a WHERE a.id = $1))`, assignmentID, event, actorID, reason)
	if err != nil {
		return fmt.Errorf("clusterlead: recording what changed: %w", err)
	}
	return nil
}
