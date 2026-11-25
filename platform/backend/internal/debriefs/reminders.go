package debriefs

// The daily_debrief_reminders job (apps.realtime.jobs.daily_debrief_reminders_job):
// before noon it reminds for yesterday, from noon for today; each submitter
// (by the role their account is in) who had work that day and has not
// submitted its Daily Debrief is told once, keyed to the day.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

// submitterRoles are SUBMITTER_ROLES; partnerRoles are PARTNER_ROLES.
var (
	submitterRoles = []string{"CCEO", "Program Lead", "PartnerAdmin", "PartnerFieldOfficer", "ProjectCoordinator", "Admin"}
	partnerRoles   = []string{"PartnerAdmin", "PartnerFieldOfficer"}
)

// DebriefReminders is the job; it says how many it reminded.
func DebriefReminders(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, roleBridge bool,
	push activities.NoticePush, logger *slog.Logger) (int, error) {
	local := now.In(kampala)
	target := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, kampala)
	when := "today"
	if local.Hour() < 12 {
		target, when = target.AddDate(0, 0, -1), "yesterday"
	}
	day := target.Format(time.DateOnly)
	rows, err := tx.Query(ctx, `SELECT u.id, COALESCE(u.active_role, ''), COALESCE(sp.id, '') FROM "user" u
LEFT JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.active_role = ANY($1) AND u.is_active ORDER BY u.created_at DESC`, submitterRoles)
	if err != nil {
		return 0, fmt.Errorf("debriefs: reading the submitters: %w", err)
	}
	type submitter struct{ id, role, staffID string }
	var people []submitter
	for rows.Next() {
		var s submitter
		if err := rows.Scan(&s.id, &s.role, &s.staffID); err != nil {
			rows.Close()
			return 0, err
		}
		people = append(people, s)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	reminded := 0
	for _, s := range people {
		had, err := hadWork(ctx, tx, s.id, s.role, s.staffID, day, roleBridge)
		if err != nil {
			return reminded, err
		}
		if !had {
			continue
		}
		var done bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM daily_debrief WHERE submitted_by_user_id = $1 AND kind = 'daily'
  AND date = $2 AND deleted_at IS NULL AND status <> 'draft')`, s.id, target).Scan(&done); err != nil {
			return reminded, fmt.Errorf("debriefs: reading the day's debrief: %w", err)
		}
		if done {
			continue
		}
		if _, err := activities.NotifyInTx(ctx, tx, push, logger, now, day, activities.Notice{
			Title: "Daily Debrief due for " + when,
			Body:  "You had scheduled activities but no debrief yet. It takes two to three minutes.",
			Event: "field_debrief.due", Category: "debrief", ContextType: "daily_debrief_due", Priority: "normal",
		}, []activities.NoticeTo{{UserID: s.id, Route: "/dashboard", Label: "View Dashboard"}}); err != nil {
			return reminded, err
		}
		reminded++
	}
	return reminded, nil
}

// hadWork is activities_for being non-empty: the submitter's own work
// planned for the day (a Partner's, its organisation's), not cancelled.
func hadWork(ctx context.Context, tx pgx.Tx, userID, role, staffID, day string, roleBridge bool) (bool, error) {
	dated := `(a.planned_date = $2 OR (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date = $2)
  AND a.deleted_at IS NULL AND a.status <> 'cancelled'`
	var had bool
	if contains(partnerRoles, role) {
		partners, err := partnerIDs(ctx, tx, userID, role, roleBridge)
		if err != nil {
			return false, err
		}
		if len(partners) == 0 {
			partners = []string{"-"}
		}
		err = tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity a WHERE a.assigned_partner_id = ANY($1) AND `+dated+`)`,
			partners, day).Scan(&had)
		if err != nil {
			return false, fmt.Errorf("debriefs: reading the Partner's day: %w", err)
		}
		return had, nil
	}
	ids := []string{userID}
	if staffID != "" {
		ids = append(ids, staffID)
	}
	err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity a WHERE (a.responsible_staff_id = ANY($1)
  OR (a.monitored_by_staff_id = ANY($1) AND a.delivery_type = 'partner')) AND `+dated+`)`, ids, day).Scan(&had)
	if err != nil {
		return false, fmt.Errorf("debriefs: reading the submitter's day: %w", err)
	}
	return had, nil
}

// partnerIDs is resolve_partner_ids: the organisation whose login this is,
// else the one the person is an active member of, else (with the
// development role bridge on) the first active Partner.
func partnerIDs(ctx context.Context, tx pgx.Tx, userID, role string, roleBridge bool) ([]string, error) {
	var id string
	err := tx.QueryRow(ctx, `SELECT id FROM partner WHERE user_id = $1 AND active_status ORDER BY created_at LIMIT 1`, userID).Scan(&id)
	if err == nil {
		return []string{id}, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("debriefs: reading the Partner login: %w", err)
	}
	if contains(partnerRoles, role) {
		err = tx.QueryRow(ctx, `SELECT m.partner_id FROM partner_member m JOIN partner p ON p.id = m.partner_id
WHERE m.user_id = $1 AND m.active AND p.active_status ORDER BY m.id LIMIT 1`, userID).Scan(&id)
		if err == nil {
			return []string{id}, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("debriefs: reading the Partner membership: %w", err)
		}
	}
	if roleBridge {
		err = tx.QueryRow(ctx, `SELECT id FROM partner WHERE active_status ORDER BY created_at LIMIT 1`).Scan(&id)
		if err == nil {
			return []string{id}, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return nil, err
		}
	}
	return nil, nil
}

func contains(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// RoleBridgeFrom is the PARTNER_ROLE_BRIDGE setting as Django reads it.
func RoleBridgeFrom(getenv func(string) string) bool {
	switch strings.ToLower(strings.TrimSpace(getenv("PARTNER_ROLE_BRIDGE"))) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}
