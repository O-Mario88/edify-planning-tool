// Package outbox drains Django's outbox (apps.outbox.services.drain) for the
// event types Go has a handler for, with the existing application absent.
// Each handler runs in a transaction of its own, so one poisoned event fails,
// backs off and dead-letters alone. An event type Go has no handler for is
// never claimed: it waits for one rather than being marked done.
package outbox

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	claimSeconds = 300 // CLAIM_SECONDS
	batchSize    = 50
)

// Handler runs one event's payload inside the transaction it is given.
type Handler func(ctx context.Context, tx pgx.Tx, payload map[string]any, now time.Time) error

// DeadLetter is told of an event that used up its attempts.
type DeadLetter func(ctx context.Context, eventID, eventType, lastError string)

// Worker drains the handled event types.
type Worker struct {
	pool     *pgxpool.Pool
	handlers map[string]Handler
	now      func() time.Time
	worker   string
	dead     DeadLetter
	logger   *slog.Logger
}

// New is a worker with no handlers yet.
func New(pool *pgxpool.Pool, now func() time.Time, workerID string, logger *slog.Logger) *Worker {
	return &Worker{pool: pool, handlers: map[string]Handler{}, now: now, worker: workerID, logger: logger}
}

// Handle registers the handler for an event type.
func (w *Worker) Handle(eventType string, h Handler) *Worker {
	w.handlers[eventType] = h
	return w
}

// OnDeadLetter sets who is told of a dead letter.
func (w *Worker) OnDeadLetter(d DeadLetter) *Worker {
	w.dead = d
	return w
}

// Types are the event types the worker handles, sorted.
func (w *Worker) Types() []string {
	types := make([]string, 0, len(w.handlers))
	for t := range w.handlers {
		types = append(types, t)
	}
	sort.Strings(types)
	return types
}

type claimed struct {
	id, kind string
	payload  []byte
	dead     bool
}

// Drain processes due events until none are left or the budget is spent,
// and answers how many it processed.
func (w *Worker) Drain(ctx context.Context, budget time.Duration) (int, error) {
	types := w.Types()
	if len(types) == 0 {
		return 0, nil
	}
	started := time.Now()
	processed := 0
	for time.Since(started) < budget {
		batch, err := w.claim(ctx, types)
		if err != nil {
			return processed, err
		}
		if len(batch) == 0 {
			break
		}
		for _, e := range batch {
			if e.dead {
				w.tellDead(ctx, e.id, e.kind, "Reclaimed after a worker died mid-handler.")
				continue
			}
			processed++
			w.run(ctx, e)
		}
	}
	return processed, nil
}

func (w *Worker) claim(ctx context.Context, types []string) ([]claimed, error) {
	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return nil, fmt.Errorf("outbox: opening the claim: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	rows, err := tx.Query(ctx, `SELECT id, event_type, payload, dead FROM gateway_outbox.claim($1, $2, $3, $4, $5)`,
		types, w.worker, w.now(), claimSeconds, batchSize)
	if err != nil {
		return nil, fmt.Errorf("outbox: claiming events: %w", err)
	}
	var out []claimed
	for rows.Next() {
		var e claimed
		if err := rows.Scan(&e.id, &e.kind, &e.payload, &e.dead); err != nil {
			rows.Close()
			return nil, fmt.Errorf("outbox: reading a claimed event: %w", err)
		}
		out = append(out, e)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("outbox: committing the claim: %w", err)
	}
	return out, nil
}

// finish is _finish in a small transaction of its own.
func (w *Worker) finish(ctx context.Context, id string, failure *string) (string, error) {
	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var status string
	if err := tx.QueryRow(ctx, `SELECT gateway_outbox.finish($1, $2, $3)`, id, failure, w.now()).Scan(&status); err != nil {
		return "", err
	}
	return status, tx.Commit(ctx)
}

// run is run_handler then _finish.
func (w *Worker) run(ctx context.Context, e claimed) {
	var failure *string
	if err := w.handle(ctx, e); err != nil {
		text := err.Error()
		failure = &text
		if w.logger != nil {
			w.logger.Warn("outbox: a handler failed", "event", e.id, "type", e.kind, "err", err)
		}
	}
	status, err := w.finish(ctx, e.id, failure)
	if err != nil {
		if w.logger != nil {
			w.logger.Error("outbox: an attempt was not recorded", "event", e.id, "err", err)
		}
		return
	}
	if status == "dead" && failure != nil {
		w.tellDead(ctx, e.id, e.kind, *failure)
	}
}

func (w *Worker) handle(ctx context.Context, e claimed) (err error) {
	h := w.handlers[e.kind]
	var payload map[string]any
	if err := json.Unmarshal(e.payload, &payload); err != nil {
		return fmt.Errorf("ValueError: the payload is not an object: %w", err)
	}
	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := h(ctx, tx, payload, w.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (w *Worker) tellDead(ctx context.Context, id, kind, lastError string) {
	if w.dead != nil {
		w.dead(ctx, id, kind, lastError)
	}
}
