package scheduler

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/outbox"
)

// outboxBudget is drain's time_budget_seconds.
const outboxBudget = 45 * time.Second

// outboxWorker is apps.outbox's drain with the handlers Go has: an event
// type without one stays queued.
func outboxWorker(pool *pgxpool.Pool, writer *notificationcenter.Writer, now func() time.Time, runner string) *outbox.Worker {
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		kampala = time.UTC
	}
	return outbox.New(pool, now, runner, nil).
		Handle("ssa.recommendations.generate", func(ctx context.Context, tx pgx.Tx, payload map[string]any, at time.Time) error {
			id, _ := payload["ssaRecordId"].(string)
			return activities.GenerateSSARecommendations(ctx, tx, id, at, kampala)
		}).
		OnDeadLetter(func(ctx context.Context, id, kind, lastError string) {
			tellDeadLetter(ctx, pool, writer, id, kind, lastError)
		})
}

// tellDeadLetter is _notify_dead_letter: every active Admin is told.
func tellDeadLetter(ctx context.Context, pool *pgxpool.Pool, writer *notificationcenter.Writer, id, kind, lastError string) {
	if writer == nil {
		return
	}
	rows, err := pool.Query(ctx, `SELECT id FROM "user" WHERE is_active AND deleted_at IS NULL AND 'Admin' = ANY(roles)`)
	if err != nil {
		return
	}
	var admins []string
	for rows.Next() {
		var uid string
		if rows.Scan(&uid) == nil {
			admins = append(admins, uid)
		}
	}
	rows.Close()
	if len(lastError) > 200 {
		lastError = lastError[:200]
	}
	for _, uid := range admins {
		_, _ = writer.Deliver(ctx, notificationcenter.Delivery{
			RecipientID: uid, Title: "Outbox event dead-lettered",
			Body:     kind + " exhausted its retries: " + lastError + " — fix the cause, then replay with outbox_requeue.",
			Category: "platform", ContextType: "OutboxEvent", ContextID: id, Priority: "high",
			SourceEventType: "outbox.dead_letter", SourceEventID: id,
		})
	}
}

// DrainOutboxOnce runs the outbox_drain job's drain once (a proof's door).
func DrainOutboxOnce(ctx context.Context, pool *pgxpool.Pool, now func() time.Time) (int, error) {
	return outboxWorker(pool, notificationcenter.NewWriter(pool, now), now, "go-scheduler").Drain(ctx, outboxBudget)
}
