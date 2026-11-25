package scheduler

import (
	"context"
	"os"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btcases"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/integrationsync"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notifymail"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/outbox"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectimpact"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pushdelivery"
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
	// A notice's phone copy, queued as the existing trigger queues it.
	push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
	return outbox.New(pool, now, runner, nil).
		Handle("ssa.recommendations.generate", func(ctx context.Context, tx pgx.Tx, payload map[string]any, at time.Time) error {
			id, _ := payload["ssaRecordId"].(string)
			return activities.GenerateSSARecommendations(ctx, tx, id, at, kampala)
		}).
		Handle("bt.ssa.confirmed", func(ctx context.Context, tx pgx.Tx, payload map[string]any, at time.Time) error {
			id, _ := payload["ssaRecordId"].(string)
			return btcases.EnsureCaseFromVerifiedSSA(ctx, tx, id, at, btcases.Notices{Push: push})
		}).
		Handle("bt.activity.state_changed", func(ctx context.Context, tx pgx.Tx, payload map[string]any, at time.Time) error {
			id, _ := payload["activityId"].(string)
			return btcases.ProjectActivityState(ctx, tx, id, at)
		}).
		Handle("projects.impact.refresh", func(ctx context.Context, tx pgx.Tx, payload map[string]any, at time.Time) error {
			id, _ := payload["schoolId"].(string)
			_, err := projectimpact.RefreshSchoolImpact(ctx, tx, id, kampala, at)
			return err
		}).
		Handle("projects.baselines.capture", func(ctx context.Context, tx pgx.Tx, payload map[string]any, at time.Time) error {
			id, _ := payload["schoolId"].(string)
			_, err := projectimpact.CaptureBaselines(ctx, tx, id, kampala, at)
			return err
		}).
		Handle("integrations.salesforce.activity", func(ctx context.Context, tx pgx.Tx, payload map[string]any, at time.Time) error {
			id, _ := payload["activityId"].(string)
			return integrationsync.SalesforceActivity(ctx, tx, id, at)
		}).
		Handle("integrations.salesforce.school_loan", func(ctx context.Context, tx pgx.Tx, payload map[string]any, _ time.Time) error {
			id, _ := payload["loanId"].(string)
			return integrationsync.SalesforceSchoolLoan(ctx, tx, id)
		}).
		Handle("integrations.netsuite.facility_tranche", func(ctx context.Context, tx pgx.Tx, payload map[string]any, _ time.Time) error {
			id, _ := payload["trancheId"].(string)
			return integrationsync.NetSuiteFacilityTranche(ctx, tx, id)
		}).
		Handle("integrations.netsuite.advance", func(ctx context.Context, tx pgx.Tx, payload map[string]any, at time.Time) error {
			id, _ := payload["advanceId"].(string)
			return integrationsync.NetSuiteAdvance(ctx, tx, id, at)
		}).
		HandleOutside("notification.email", notifymail.Handler{
			Mailer: notifymail.ResendFrom(os.Getenv), BaseURL: notifymail.BaseURLFrom(os.Getenv), Kampala: kampala,
		}.Handle).
		HandleOutside("notification.push", pushdelivery.Handler{Senders: pushdelivery.SendersFromEnv()}.Handle).
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
