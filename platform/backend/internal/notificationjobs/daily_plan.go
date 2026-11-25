package notificationjobs

// _do_daily_plan_notifications: each CCEO with open work on their own My
// Plan today gets one "Your plan today" notice, and each Programme Lead with
// anything to act on gets one "Monitor your team's plans today"; a re-run the
// same day sends nothing twice, and yesterday's live notices are closed.

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myteam"
)

const (
	dailyPlanEvent = "daily_plan_today"
	teamDailyEvent = "pl_team_daily_monitor"
	// dailyPlanNamed is _DAILY_PLAN_NAMED.
	dailyPlanNamed = 3
)

var (
	// partnerOnlyStatuses are PARTNER_ONLY_STATUSES.
	partnerOnlyStatuses = []string{"assigned_to_partner", "partner_scheduled"}
	// openWorkExcluded are _open_work's exclusions: ACTIVE_MY_PLAN_EXCLUDED_STATUSES,
	// COMPLETED_WORK_STATUSES and TERMINAL_OR_COMPLETED_STATUSES.
	openWorkExcluded = []string{"closed", "cancelled", "rejected", "awaiting_owner_approval", "deferred", "not_planned",
		"ia_verified", "accountant_confirmed", "completed", "submitted_to_pl", "awaiting_ia_verification"}
	// terminalOrCompleted are TERMINAL_OR_COMPLETED_STATUSES.
	terminalOrCompleted = []string{"ia_verified", "closed", "accountant_confirmed", "completed", "cancelled",
		"submitted_to_pl", "awaiting_ia_verification"}
)

// myPlanToday is staff_my_plan_q with _today_q and _open_work: work the ids
// own and deliver, dated today (a planned day, else the planned time's
// Kampala day), not released and not already delivered.
const myPlanToday = `a.deleted_at IS NULL AND a.responsible_staff_id = ANY($1)
  AND a.delivery_type IS DISTINCT FROM 'partner' AND NOT (a.status = ANY($2))
  AND (a.planned_date = $3 OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date = $3))
  AND NOT (a.status = ANY($4))`

// DailyPlan is the day's plan notices for today in Kampala; it says how many
// it sent.
func DailyPlan(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, n Notices) (int, error) {
	local := now.In(kampala)
	today := local.Format(time.DateOnly)
	key := "dp-" + today
	if _, err := tx.Exec(ctx, `SELECT gateway_notifications.close_stale_daily_notices($1, $2, $3)`,
		[]string{dailyPlanEvent, teamDailyEvent}, key, now); err != nil {
		return 0, fmt.Errorf("notificationjobs: closing yesterday's plan notices: %w", err)
	}
	sent, err := officersPlans(ctx, tx, now, today, key, n)
	if err != nil {
		return sent, err
	}
	leads, err := leadsTeams(ctx, tx, now, today, key, n)
	return sent + leads, err
}

// holder is one account holding a role, with their People record.
type holder struct{ userID, staffID string }

// holders is role_recipients: active accounts holding the role, newest first.
func holders(ctx context.Context, tx pgx.Tx, role string) ([]holder, error) {
	rows, err := tx.Query(ctx, `SELECT u.id, COALESCE(sp.id, '') FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id
WHERE $1 = ANY(u.roles) AND u.is_active AND u.deleted_at IS NULL ORDER BY u.created_at DESC`, role)
	if err != nil {
		return nil, fmt.Errorf("notificationjobs: reading who holds %s: %w", role, err)
	}
	defer rows.Close()
	var out []holder
	for rows.Next() {
		var h holder
		if err := rows.Scan(&h.userID, &h.staffID); err != nil {
			return nil, err
		}
		out = append(out, h)
	}
	return out, rows.Err()
}

// alreadyTold is _already_told: a notice for this person, event and day
// exists, even one they archived.
func alreadyTold(ctx context.Context, tx pgx.Tx, userID, event, key string) (bool, error) {
	var told bool
	err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE recipient_id = $1 AND source_event_type = $2
  AND context_id = $3)`, userID, event, key).Scan(&told)
	if err != nil {
		return false, fmt.Errorf("notificationjobs: reading whether today's notice was sent: %w", err)
	}
	return told, nil
}

func ownerIDs(h holder) []string {
	ids := []string{h.userID}
	if h.staffID != "" {
		ids = append(ids, h.staffID)
	}
	return ids
}

// officersPlans is the CCEOs' "Your plan today".
func officersPlans(ctx context.Context, tx pgx.Tx, now time.Time, today, key string, n Notices) (int, error) {
	officers, err := holders(ctx, tx, "CCEO")
	if err != nil {
		return 0, err
	}
	sent := 0
	for _, o := range officers {
		told, err := alreadyTold(ctx, tx, o.userID, dailyPlanEvent, key)
		if err != nil || told {
			if err != nil {
				return sent, err
			}
			continue
		}
		places, err := todaysWork(ctx, tx, ownerIDs(o), today)
		if err != nil {
			return sent, err
		}
		if len(places) == 0 {
			continue
		}
		named := places
		if len(named) > dailyPlanNamed {
			named = named[:dailyPlanNamed]
		}
		body := strings.Join(named, "; ") + "."
		if more := len(places) - dailyPlanNamed; more > 0 {
			body = strings.Join(named, "; ") + fmt.Sprintf("; and %d more.", more)
		}
		noun := "activities"
		if len(places) == 1 {
			noun = "activity"
		}
		if _, err := activities.NotifyInTx(ctx, tx, n.Push, n.Logger, now, key, activities.Notice{
			Title: fmt.Sprintf("Your plan today: %d %s", len(places), noun), Body: body,
			Event: dailyPlanEvent, Category: "activity", ContextType: "daily_plan", Priority: "normal",
		}, []activities.NoticeTo{{UserID: o.userID, Route: "/dashboard?view=today", Label: "Open Today"}}); err != nil {
			return sent, err
		}
		sent++
	}
	return sent, nil
}

// todaysWork is each of today's open activities as _where_label names it,
// in the plan's order.
func todaysWork(ctx context.Context, tx pgx.Tx, ids []string, today string) ([]string, error) {
	rows, err := tx.Query(ctx, `SELECT a.activity_type, a.school_id IS NOT NULL AND a.school_id <> '', COALESCE(s.name, ''),
  a.cluster_id IS NOT NULL AND a.cluster_id <> '', COALESCE(c.name, ''), COALESCE(a.venue, '')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE `+myPlanToday+`
ORDER BY a.planned_date, a.created_at`, ids, partnerOnlyStatuses, today, openWorkExcluded)
	if err != nil {
		return nil, fmt.Errorf("notificationjobs: reading today's plan: %w", err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var kind, school, cluster, venue string
		var hasSchool, hasCluster bool
		if err := rows.Scan(&kind, &hasSchool, &school, &hasCluster, &cluster, &venue); err != nil {
			return nil, err
		}
		place := venue
		switch {
		case hasSchool:
			place = school
		case hasCluster:
			place = cluster
		}
		label := myplan.TypeLabel(kind)
		if place != "" {
			label += " at " + place
		}
		out = append(out, label)
	}
	return out, rows.Err()
}

// leadsTeams is the Programme Leads' "Monitor your team's plans today".
func leadsTeams(ctx context.Context, tx pgx.Tx, now time.Time, today, key string, n Notices) (int, error) {
	leads, err := holders(ctx, tx, "Program Lead")
	if err != nil {
		return 0, err
	}
	sent := 0
	for _, lead := range leads {
		told, err := alreadyTold(ctx, tx, lead.userID, teamDailyEvent, key)
		if err != nil {
			return sent, err
		}
		if told || lead.staffID == "" {
			continue
		}
		members, err := myteam.TeamMembers(ctx, tx, lead.staffID, now)
		if err != nil {
			return sent, err
		}
		var teamIDs []string
		personOf := map[string]string{}
		for _, m := range members {
			for _, id := range []string{m.StaffID, m.UserID} {
				if id != "" {
					teamIDs = append(teamIDs, id)
					personOf[id] = m.StaffID
				}
			}
		}
		if len(teamIDs) == 0 {
			continue
		}
		body, ok, err := teamToday(ctx, tx, teamIDs, personOf, today)
		if err != nil {
			return sent, err
		}
		if !ok {
			continue
		}
		if _, err := activities.NotifyInTx(ctx, tx, n.Push, n.Logger, now, key, activities.Notice{
			Title: "Monitor your team's plans today", Body: body,
			Event: teamDailyEvent, Category: "team", ContextType: "team_daily", Priority: "normal",
		}, []activities.NoticeTo{{UserID: lead.userID, Route: "/team-planning-oversight/", Label: "Monitor Team Plans"}}); err != nil {
			return sent, err
		}
		sent++
	}
	return sent, nil
}

// teamToday is the lead's line: today's open work and how many officers
// carry it, the team's past-due work, and completions waiting on the lead.
func teamToday(ctx context.Context, tx pgx.Tx, teamIDs []string, personOf map[string]string, today string) (string, bool, error) {
	rows, err := tx.Query(ctx, `SELECT COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, '') FROM activity a
WHERE `+myPlanToday, teamIDs, partnerOnlyStatuses, today, openWorkExcluded)
	if err != nil {
		return "", false, fmt.Errorf("notificationjobs: reading the team's plan today: %w", err)
	}
	planned := 0
	officers := map[string]bool{}
	for rows.Next() {
		var responsible, monitor string
		if err := rows.Scan(&responsible, &monitor); err != nil {
			rows.Close()
			return "", false, err
		}
		planned++
		who := responsible
		if who == "" {
			who = monitor
		}
		if who == "" {
			continue
		}
		if p, ok := personOf[who]; ok {
			who = p
		}
		officers[who] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return "", false, err
	}
	var pastDue, waiting int
	err = tx.QueryRow(ctx, `SELECT
  (SELECT count(*)::int FROM activity a WHERE a.deleted_at IS NULL AND NOT (a.status = ANY($4))
     AND (a.planned_date < $3 OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date < $3))
     AND a.responsible_staff_id = ANY($1) AND a.delivery_type IS DISTINCT FROM 'partner' AND NOT (a.status = ANY($2))),
  (SELECT count(*)::int FROM activity a WHERE a.deleted_at IS NULL AND a.status = 'submitted_to_pl'
     AND a.responsible_staff_id = ANY($1))`, teamIDs, partnerOnlyStatuses, today, terminalOrCompleted).Scan(&pastDue, &waiting)
	if errors.Is(err, pgx.ErrNoRows) {
		err = nil
	}
	if err != nil {
		return "", false, fmt.Errorf("notificationjobs: reading the team's past-due and waiting work: %w", err)
	}
	if planned == 0 && pastDue == 0 && waiting == 0 {
		return "", false, nil
	}
	noun := "activities"
	if planned == 1 {
		noun = "activity"
	}
	people := "officers"
	if len(officers) == 1 {
		people = "officer"
	}
	parts := []string{fmt.Sprintf("%d %s planned today by %d %s", planned, noun, len(officers), people)}
	if pastDue > 0 {
		parts = append(parts, fmt.Sprintf("%d past due", pastDue))
	}
	if waiting > 0 {
		word := "completions"
		if waiting == 1 {
			word = "completion"
		}
		parts = append(parts, fmt.Sprintf("%d %s waiting on you", waiting, word))
	}
	return strings.Join(parts, "; ") + ".", true, nil
}
