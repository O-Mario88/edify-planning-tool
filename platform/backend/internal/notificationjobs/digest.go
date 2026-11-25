// Package notificationjobs is the scheduler's notification jobs ported from
// apps.realtime.jobs, each writing its notices through the existing trigger
// (activities.NotifyInTx). Inside the caller's transaction.
package notificationjobs

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pyhash"
)

// Notices is how a job tells people: a phone copy per notice, and a logger
// for one that is not queued. Both may be nil.
type Notices struct {
	Push   activities.NoticePush
	Logger *slog.Logger
}

// DailyDigest is _do_daily_digest: each person with unread notices gets one
// "You have N unread notifications" a day, keyed by the day and a short hash
// of who they are. The people are read as the existing job reads them,
// newest notice first, a person appearing once per notice and passed over
// after their first digest.
func DailyDigest(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, n Notices) (int, error) {
	local := now.In(kampala)
	today := local.Format(time.DateOnly)
	rows, err := tx.Query(ctx, `SELECT DISTINCT recipient_id, created_at FROM notification WHERE status = 'unread'
ORDER BY created_at DESC`)
	if err != nil {
		return 0, fmt.Errorf("notificationjobs: reading who has unread notices: %w", err)
	}
	var people []string
	for rows.Next() {
		var id string
		var at time.Time
		if err := rows.Scan(&id, &at); err != nil {
			rows.Close()
			return 0, err
		}
		people = append(people, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	created := 0
	for _, recipient := range people {
		var unread int
		if err := tx.QueryRow(ctx, `SELECT count(*)::int FROM notification WHERE recipient_id = $1 AND status = 'unread'`,
			recipient).Scan(&unread); err != nil {
			return created, fmt.Errorf("notificationjobs: counting unread notices: %w", err)
		}
		if unread == 0 {
			continue
		}
		digestID := "dg-" + today + "-" + pyhash.Blake2sHex([]byte(recipient), 8)
		var already bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE recipient_id = $1 AND source_event_id = $2)`,
			recipient, digestID).Scan(&already); err != nil {
			return created, fmt.Errorf("notificationjobs: reading today's digest: %w", err)
		}
		if already {
			continue
		}
		if _, err := activities.NotifyInTx(ctx, tx, n.Push, n.Logger, now, digestID, activities.Notice{
			Title: fmt.Sprintf("You have %d unread notifications", unread), Body: "Your daily digest.",
			Event: "daily_digest", Category: "general", Priority: "normal",
		}, []activities.NoticeTo{{UserID: recipient, Route: "/dashboard", Label: "View Dashboard"}}); err != nil {
			return created, err
		}
		created++
	}
	return created, nil
}
