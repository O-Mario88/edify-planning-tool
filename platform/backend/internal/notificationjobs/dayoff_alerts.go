package notificationjobs

// The day_off_alerts job (apps.activities.day_off.send_day_off_alerts): each
// person is told which of their coming activities (the next 120 days) sit on
// a public holiday or on a day they are on approved leave, one notice a
// person a day off, keyed to that day. A re-run says nothing twice, a day
// whose list changed is said again with the new list (the live notice
// updated in place), and a day with nothing left on it has its notice
// closed. Inside the caller's transaction.

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	dayOffEvent   = "activity_on_day_off"
	dayOffNamed   = 3 // _NAMED
	dayOffHorizon = 120
)

// comingWork is one activity the sweep reads.
type comingWork struct {
	id, status, staffID, partnerID, kind, label string
	planned, scheduled, end                     *time.Time
}

func day(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

func shortDay(t time.Time) string { return t.Format("Mon 2 Jan") }

func inList(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// SendDayOffAlerts is the job for today in Kampala; it says how many
// notices it sent.
func SendDayOffAlerts(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location,
	push activities.NoticePush, logger *slog.Logger) (int, error) {
	local := now.In(kampala)
	today := day(local.Year(), local.Month(), local.Day())
	until := today.AddDate(0, 0, dayOffHorizon)
	rows, err := tx.Query(ctx, `
SELECT a.id, a.status, COALESCE(a.responsible_staff_id, ''), COALESCE(a.assigned_partner_id, ''), a.planned_date,
  a.scheduled_date, a.end_date, a.activity_type, COALESCE(a.activity_name_snapshot, ''),
  COALESCE(a.school_id, '') <> '', COALESCE(s.name, ''), COALESCE(a.cluster_id, '') <> '', COALESCE(c.name, ''),
  COALESCE(a.venue, '')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.status = ANY($1)
  AND (a.planned_date <= $2 OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date <= $2))
  AND (a.end_date >= $3 OR a.planned_date >= $3
       OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date >= $3))
ORDER BY a.planned_date, a.created_at`, calendarpage.AwaitingDelivery(), until.Format(time.DateOnly), today.Format(time.DateOnly))
	if err != nil {
		return 0, fmt.Errorf("calendarpage: reading the coming work: %w", err)
	}
	var coming []*comingWork
	for rows.Next() {
		w := &comingWork{}
		var hasSchool, hasCluster bool
		var school, cluster, venue, name string
		if err := rows.Scan(&w.id, &w.status, &w.staffID, &w.partnerID, &w.planned, &w.scheduled, &w.end, &w.kind, &name,
			&hasSchool, &school, &hasCluster, &cluster, &venue); err != nil {
			rows.Close()
			return 0, err
		}
		place := venue
		switch {
		case hasSchool:
			place = school
		case hasCluster:
			place = cluster
		}
		w.label = name
		if w.label == "" {
			w.label = calendarpage.ActivityTypeLabel(w.kind)
		}
		if place != "" {
			w.label += " at " + place
		}
		coming = append(coming, w)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	work := make([]calendarpage.DayOffWork, 0, len(coming))
	for _, w := range coming {
		start := w.planned
		if start == nil && w.scheduled != nil {
			d := w.scheduled.In(kampala)
			s := day(d.Year(), d.Month(), d.Day())
			start = &s
		}
		if start == nil {
			continue
		}
		s := day(start.Year(), start.Month(), start.Day())
		e := s
		if w.end != nil {
			if end := day(w.end.Year(), w.end.Month(), w.end.Day()); end.After(s) {
				e = end
			}
		}
		work = append(work, calendarpage.DayOffWork{ID: w.id, Status: w.status, StaffID: w.staffID, Start: s, End: e})
	}
	marks, err := calendarpage.DayOffDays(ctx, tx, work)
	if err != nil {
		return 0, err
	}
	owners, err := dayOffOwners(ctx, tx, coming, marks)
	if err != nil {
		return 0, err
	}
	type entry struct {
		owner string
		day   time.Time
		work  []*comingWork
		why   []string
	}
	var todo []*entry
	index := map[string]*entry{}
	for _, w := range coming {
		days, ok := marks[w.id]
		if !ok {
			continue
		}
		owner := owners[w.id]
		if owner == "" {
			continue
		}
		for _, d := range days {
			if d.Day.Before(today) {
				continue
			}
			k := owner + "|" + d.Day.Format(time.DateOnly)
			e, ok := index[k]
			if !ok {
				e = &entry{owner: owner, day: d.Day}
				index[k] = e
				todo = append(todo, e)
			}
			if !containsWork(e.work, w) {
				e.work = append(e.work, w)
			}
			reason := "a day you are on leave"
			if d.Holiday {
				reason = "a public holiday (" + d.Name + ")"
			}
			if !inList(e.why, reason) {
				e.why = append(e.why, reason)
			}
		}
	}
	live, err := liveDayOffNotices(ctx, tx)
	if err != nil {
		return 0, err
	}
	sent := 0
	for _, e := range todo {
		key := "dayoff-" + e.day.Format(time.DateOnly)
		labels := make([]string, 0, dayOffNamed)
		for i, w := range e.work {
			if i == dayOffNamed {
				break
			}
			labels = append(labels, w.label)
		}
		body := e.day.Format("Monday 2 January") + " is " + strings.Join(e.why, " and ") + ". Move: " + strings.Join(labels, "; ")
		if more := len(e.work) - dayOffNamed; more > 0 {
			body += fmt.Sprintf("; and %d more.", more)
		} else {
			body += "."
		}
		lk := e.owner + "|" + key
		notice, isLive := live[lk]
		delete(live, lk)
		if isLive && notice.body == body {
			continue
		}
		if !isLive {
			var told bool
			if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE recipient_id = $1 AND source_event_type = $2
  AND context_id = $3 AND body = $4)`, e.owner, dayOffEvent, key, body).Scan(&told); err != nil {
				return sent, fmt.Errorf("calendarpage: reading the day-off notices: %w", err)
			}
			if told {
				continue // told exactly this already, and they put it away
			}
		}
		noun := "activities"
		if len(e.work) == 1 {
			noun = "activity"
		}
		route := fmt.Sprintf("/my-plan?fy=%s&month=%d", schooldirectory.OperationalFY(e.day), int(e.day.Month()))
		if _, err := activities.NotifyInTx(ctx, tx, push, logger, now, key, activities.Notice{
			Title: fmt.Sprintf("Reschedule %d %s planned for %s", len(e.work), noun, shortDay(e.day)), Body: body,
			Event: dayOffEvent, Category: "activity", ContextType: "day_off", Priority: "normal",
		}, []activities.NoticeTo{{UserID: e.owner, Route: route, Label: "Reschedule in My Plan"}}); err != nil {
			return sent, err
		}
		sent++
	}
	if len(live) > 0 {
		ids := make([]string, 0, len(live))
		for _, n := range live {
			ids = append(ids, n.id)
		}
		if _, err := tx.Exec(ctx, `SELECT gateway_notifications.close_notices($1, $2)`, ids, now); err != nil {
			return sent, fmt.Errorf("calendarpage: closing the day-off notices with nothing left: %w", err)
		}
	}
	return sent, nil
}

func containsWork(list []*comingWork, w *comingWork) bool {
	for _, x := range list {
		if x == w {
			return true
		}
	}
	return false
}

// dayOffOwners is _owner_user_ids: the responsible staff member's login (a
// legacy row's id as it is), else the Partner's login for its work.
func dayOffOwners(ctx context.Context, tx pgx.Tx, coming []*comingWork, marks map[string][]calendarpage.DayOffDay) (map[string]string, error) {
	var staff, partners []string
	for _, w := range coming {
		if _, ok := marks[w.id]; !ok {
			continue
		}
		if w.staffID != "" {
			staff = append(staff, w.staffID)
		} else if w.partnerID != "" {
			partners = append(partners, w.partnerID)
		}
	}
	read := func(sql string, ids []string) (map[string]string, error) {
		into := map[string]string{}
		if len(ids) == 0 {
			return into, nil
		}
		rows, err := tx.Query(ctx, sql, ids)
		if err != nil {
			return nil, fmt.Errorf("calendarpage: reading the work's owners: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var id string
			var user *string
			if err := rows.Scan(&id, &user); err != nil {
				return nil, err
			}
			if user != nil {
				into[id] = *user
			}
		}
		return into, rows.Err()
	}
	staffUser, err := read(`SELECT id, user_id FROM staff_profile WHERE id = ANY($1)`, staff)
	if err != nil {
		return nil, err
	}
	partnerUser, err := read(`SELECT id, user_id FROM partner WHERE id = ANY($1)`, partners)
	if err != nil {
		return nil, err
	}
	out := map[string]string{}
	for _, w := range coming {
		if _, ok := marks[w.id]; !ok {
			continue
		}
		owner := ""
		if w.staffID != "" {
			owner = w.staffID
			if u, ok := staffUser[w.staffID]; ok && u != "" {
				owner = u
			}
		} else {
			owner = partnerUser[w.partnerID]
		}
		if owner != "" {
			out[w.id] = owner
		}
	}
	return out, nil
}

type liveNotice struct{ id, body string }

// liveDayOffNotices are the open day-off notices by recipient and day, the
// oldest standing for a pair as the existing dict keeps the last read.
func liveDayOffNotices(ctx context.Context, tx pgx.Tx) (map[string]liveNotice, error) {
	rows, err := tx.Query(ctx, `SELECT id, recipient_id, COALESCE(context_id, ''), COALESCE(body, '') FROM notification
WHERE source_event_type = $1 AND resolved_at IS NULL AND status <> 'archived' ORDER BY created_at DESC`, dayOffEvent)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the open day-off notices: %w", err)
	}
	defer rows.Close()
	out := map[string]liveNotice{}
	for rows.Next() {
		var n liveNotice
		var recipient, ctxID string
		if err := rows.Scan(&n.id, &recipient, &ctxID, &n.body); err != nil {
			return nil, err
		}
		out[recipient+"|"+ctxID] = n
	}
	return out, rows.Err()
}
