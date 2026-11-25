package notificationjobs

// _do_activity_reminders: "Starts tomorrow" for each activity planned for
// tomorrow, to the person responsible (their account, or the id the activity
// holds when it is not a People record) or, for Partner-delivered work, the
// Partner's login; one a person an activity a day, multi-day work reminded on
// the eve of its start only.

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pyhash"
)

// ActivityReminders is the job for tomorrow in Kampala; it says how many it sent.
func ActivityReminders(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, n Notices) (int, error) {
	local := now.In(kampala)
	tomorrow := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC).AddDate(0, 0, 1)
	rows, err := tx.Query(ctx, `
SELECT a.id, a.activity_type, COALESCE(a.activity_name_snapshot, ''), a.end_date,
  CASE WHEN COALESCE(a.responsible_staff_id, '') <> ''
       THEN COALESCE(NULLIF((SELECT sp.user_id FROM staff_profile sp WHERE sp.id = a.responsible_staff_id AND sp.deleted_at IS NULL), ''),
                     a.responsible_staff_id) END,
  CASE WHEN COALESCE(a.assigned_partner_id, '') <> '' THEN (SELECT p.user_id FROM partner p WHERE p.id = a.assigned_partner_id) END
FROM activity a
WHERE a.deleted_at IS NULL AND a.planned_date = $1
  AND NOT (a.status = ANY($2))
  AND ((a.responsible_staff_id IS NOT NULL AND a.responsible_staff_id <> '')
       OR (a.delivery_type = 'partner' AND a.assigned_partner_id IS NOT NULL))
ORDER BY a.created_at DESC`, tomorrow.Format(time.DateOnly), []string{"cancelled", "rejected", "deferred", "not_planned"})
	if err != nil {
		return 0, fmt.Errorf("notificationjobs: reading tomorrow's activities: %w", err)
	}
	type upcoming struct {
		id, kind, name string
		end            *time.Time
		owner, partner *string
	}
	var list []upcoming
	for rows.Next() {
		var u upcoming
		if err := rows.Scan(&u.id, &u.kind, &u.name, &u.end, &u.owner, &u.partner); err != nil {
			rows.Close()
			return 0, err
		}
		list = append(list, u)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	created := 0
	for _, u := range list {
		recipient := ""
		switch {
		case u.owner != nil && *u.owner != "":
			recipient = *u.owner
		case u.partner != nil && *u.partner != "":
			recipient = *u.partner
		}
		if recipient == "" {
			continue
		}
		reminder := "act-" + tomorrow.Format(time.DateOnly) + "-" + pyhash.Blake2sHex([]byte(u.id), 6)
		var already bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE recipient_id = $1 AND source_event_id = $2)`,
			recipient, reminder).Scan(&already); err != nil {
			return created, fmt.Errorf("notificationjobs: reading whether the reminder was sent: %w", err)
		}
		if already {
			continue
		}
		name := u.name
		if name == "" {
			name = myplan.TypeLabel(u.kind)
		}
		span := ""
		if u.end != nil && !dayOnly(*u.end).Equal(tomorrow) {
			span = fmt.Sprintf(" (%s–%s)", tomorrow.Format("2 Jan"), dayOnly(*u.end).Format("2 Jan"))
		}
		if _, err := activities.NotifyInTx(ctx, tx, n.Push, n.Logger, now, reminder, activities.Notice{
			Title: "Starts tomorrow: " + name + span,
			Body:  "Review the plan, funding and evidence requirements before you start.",
			Event: "activity_reminder", Category: "activity", ContextType: "Activity", Priority: "normal",
		}, []activities.NoticeTo{{UserID: recipient, Route: "/my-plan/" + reminder, Label: "Open Activity"}}); err != nil {
			return created, err
		}
		created++
	}
	return created, nil
}

func dayOnly(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}
