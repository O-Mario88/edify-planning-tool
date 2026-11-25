package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cexIntegrity is dataset._integrity: what was due in the window when it
// began, and what changed since (from the schedule trail).
type cexIntegrity struct {
	tracked                                             bool
	trackingSince, cutoff                               *time.Time
	original, added, movedIn, movedOut, cancelled, live int
	movedRows                                           []cexRow
}

// cexTrackingSince is schedule_trail.tracking_since: when the trail's
// migration was applied, or nil.
func cexTrackingSince(ctx context.Context, db schooldirectory.Querier) (*time.Time, error) {
	var applied *time.Time
	err := db.QueryRow(ctx, `SELECT applied FROM django_migrations WHERE app = 'activities' AND name = $1 ORDER BY id LIMIT 1`,
		rules.CountryExecution.TrailMigration).Scan(&applied)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: when the schedule trail began: %w", err)
	}
	return applied, nil
}

func cexIntegrityOf(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, w cpoWindow,
	rows []cexRow) (cexIntegrity, error) {
	st := rules.CountryExecution.Stages
	out := cexIntegrity{}
	since, err := cexTrackingSince(ctx, db)
	if err != nil {
		return out, err
	}
	cutoff := time.Date(w.start.Year(), w.start.Month(), w.start.Day(), 0, 0, 0, 0, cpoLocation)
	out.trackingSince, out.cutoff = since, &cutoff
	for _, r := range rows {
		if !slices.Contains(st.OffPlan, r.status) {
			out.live++
		}
	}
	if since == nil || since.After(cutoff) {
		return out, nil
	}
	out.tracked = true
	type was struct {
		day    *time.Time
		status string
	}
	firstAfter, order := map[string]was{}, []string{}
	q, err := db.Query(ctx, `SELECT activity_id, from_day, COALESCE(from_status, '') FROM activity_schedule_change
		WHERE changed_at >= $1 AND ((from_day >= $2::date AND from_day < $3::date) OR (to_day >= $2::date AND to_day < $3::date))
		ORDER BY activity_id, changed_at`, cutoff, w.start, w.end)
	if err != nil {
		return out, fmt.Errorf("planningmonitor: the schedule trail: %w", err)
	}
	for q.Next() {
		var id, status string
		var day *time.Time
		if err := q.Scan(&id, &day, &status); err != nil {
			q.Close()
			return out, err
		}
		if _, seen := firstAfter[id]; !seen {
			firstAfter[id] = was{day, status}
			order = append(order, id)
		}
	}
	q.Close()
	if err := q.Err(); err != nil {
		return out, err
	}
	now := map[string]cexRow{}
	created := map[string]*time.Time{}
	for _, r := range rows {
		now[r.id] = r
		created[r.id] = r.created
	}
	missing := []string{}
	for _, id := range order {
		if _, ok := created[id]; !ok {
			missing = append(missing, id)
		}
	}
	if len(missing) > 0 {
		q, err := db.Query(ctx, `SELECT id, created_at FROM activity WHERE id = ANY($1)`, missing)
		if err != nil {
			return out, fmt.Errorf("planningmonitor: the moved work's creation: %w", err)
		}
		for q.Next() {
			var id string
			var at *time.Time
			if err := q.Scan(&id, &at); err != nil {
				q.Close()
				return out, err
			}
			created[id] = at
		}
		q.Close()
		if err := q.Err(); err != nil {
			return out, err
		}
	}
	inWindow := func(d *time.Time) bool { return d != nil && !d.Before(w.start) && d.Before(w.end) }
	all := slices.Clone(order)
	for _, r := range rows {
		if _, ok := firstAfter[r.id]; !ok {
			all = append(all, r.id)
		}
	}
	movedOut := []string{}
	for _, id := range all {
		made := created[id]
		existed := made != nil && made.Before(cutoff)
		var wasDay *time.Time
		wasLive := true
		if f, ok := firstAfter[id]; ok {
			wasDay = f.day
			wasLive = !slices.Contains(st.OffPlan, f.status) && !slices.Contains(st.NotAPlan, f.status)
		} else {
			wasDay = now[id].due
		}
		row, has := now[id]
		nowIn := has && !slices.Contains(st.OffPlan, row.status)
		wasIn := existed && wasLive && inWindow(wasDay)
		switch {
		case wasIn:
			out.original++
			if has && slices.Contains(st.OffPlan, row.status) {
				out.cancelled++
			} else if !nowIn {
				out.movedOut++
				movedOut = append(movedOut, id)
			}
		case nowIn:
			if existed {
				out.movedIn++
			} else {
				out.added++
			}
		case has && !existed && slices.Contains(st.OffPlan, row.status):
			out.cancelled++
		}
	}
	if len(movedOut) == 0 {
		return out, nil
	}
	b := &sql{}
	scopeQ := cexScope(b, scope)
	if scopeQ == "" {
		return out, nil
	}
	day := "COALESCE(a.planned_date, (a.scheduled_date AT TIME ZONE '" + cpoZone + "')::date)"
	where := `a.id = ANY(` + b.arg(movedOut) + `) AND a.deleted_at IS NULL AND ` + day + ` >= ` + b.arg(w.end) + `::date AND (` + scopeQ + `)`
	out.movedRows, err = scanCexRows(ctx, db, `SELECT `+cexColumns+cexJoins+` WHERE `+where, b.args...)
	return out, err
}
