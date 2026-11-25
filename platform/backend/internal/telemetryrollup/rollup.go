// Package telemetryrollup is the interaction_rollup job
// (apps.telemetry.services.rollup_interaction_days): yesterday's request
// events folded into one row a person a day, sessionised as the Staff Time
// Standard defines it, then raw events past their retention pruned. Inside
// the caller's transaction; a rerun rewrites the same rows from the same
// events.
package telemetryrollup

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// The Staff Time Standard's constants (docs/STAFF_TIME_STANDARD.md): an
// amendment to the standard, not a tuning knob.
const (
	idleCapSeconds           = 180
	finalActionCreditSeconds = 30
	rawEventRetentionDays    = 14
)

const (
	planning  = "planning"
	execution = "execution"
	other     = "other"
)

var writeMethods = []string{"POST", "PUT", "PATCH", "DELETE"}

// planningPrefixes and executionPrefixes are the §3a route classification.
var (
	planningPrefixes = []string{"planning", "work-plan", "fund-requests", "budget", "target-distribution",
		"clusters/schedule", "core-schools/schedule", "core-schools/assign-partner"}
	executionPrefixes = []string{"my-plan", "activities", "evidence", "debrief", "actions", "today", "todos", "partner",
		"ssa", "pl/review-queue", "accounts/activities", "accounts/activity-evidence"}
)

// classifyRoute is classify_route: execution wins ties.
func classifyRoute(route string) string {
	trimmed := strings.TrimLeft(route, "/")
	for _, p := range executionPrefixes {
		if strings.HasPrefix(trimmed, p) {
			return execution
		}
	}
	for _, p := range planningPrefixes {
		if strings.HasPrefix(trimmed, p) {
			return planning
		}
	}
	return other
}

type event struct {
	at    time.Time
	route string
}

// byCategory is active_seconds_by_category: each gap inside a session goes
// to the event before it, each session's final-action credit to its last
// event, the totals truncated to whole seconds as int() truncates.
func byCategory(events []event) map[string]int {
	totals := map[string]float64{planning: 0, execution: 0, other: 0}
	if len(events) == 0 {
		return map[string]int{planning: 0, execution: 0, other: 0}
	}
	ordered := slices.Clone(events)
	slices.SortStableFunc(ordered, func(a, b event) int { return a.at.Compare(b.at) })
	for i := 1; i < len(ordered); i++ {
		gap := ordered[i].at.Sub(ordered[i-1].at).Seconds()
		if gap > idleCapSeconds {
			totals[classifyRoute(ordered[i-1].route)] += finalActionCreditSeconds
		} else {
			totals[classifyRoute(ordered[i-1].route)] += gap
		}
	}
	totals[classifyRoute(ordered[len(ordered)-1].route)] += finalActionCreditSeconds
	out := map[string]int{}
	for k, v := range totals {
		out[k] = int(v)
	}
	return out
}

// Rollup is rollup_interaction_days for yesterday in Kampala; it says how
// many person-days it wrote.
func Rollup(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location) (int, error) {
	local := now.In(kampala)
	start := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, kampala).AddDate(0, 0, -1)
	end := start.AddDate(0, 0, 1)
	rows, err := tx.Query(ctx, `SELECT user_id, role, occurred_at, method, route FROM interaction_event
WHERE occurred_at >= $1 AND occurred_at < $2 ORDER BY id`, start, end)
	if err != nil {
		return 0, fmt.Errorf("telemetryrollup: reading the day's events: %w", err)
	}
	type bucket struct {
		role   string
		events []event
		writes int
	}
	buckets := map[string]*bucket{}
	var order []string
	for rows.Next() {
		var user, role, method, route string
		var at time.Time
		if err := rows.Scan(&user, &role, &at, &method, &route); err != nil {
			rows.Close()
			return 0, err
		}
		b, ok := buckets[user]
		if !ok {
			b = &bucket{}
			buckets[user] = b
			order = append(order, user)
		}
		// The most recent role wins for the day.
		b.role = role
		b.events = append(b.events, event{at: at, route: route})
		if slices.Contains(writeMethods, method) {
			b.writes++
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	day := start.Format(time.DateOnly)
	for _, user := range order {
		b := buckets[user]
		c := byCategory(b.events)
		if _, err := tx.Exec(ctx, `INSERT INTO interaction_day (id, user_id, day, role, active_seconds, planning_seconds,
  execution_seconds, request_count, write_count)
VALUES ($9, $1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (user_id, day) DO UPDATE SET role = EXCLUDED.role, active_seconds = EXCLUDED.active_seconds,
  planning_seconds = EXCLUDED.planning_seconds, execution_seconds = EXCLUDED.execution_seconds,
  request_count = EXCLUDED.request_count, write_count = EXCLUDED.write_count`,
			user, day, b.role, c[planning]+c[execution]+c[other], c[planning], c[execution], len(b.events), b.writes,
			cuid.New()); err != nil {
			return 0, fmt.Errorf("telemetryrollup: writing a person-day: %w", err)
		}
	}
	if _, err := tx.Exec(ctx, `SELECT gateway_telemetry.prune_interaction_events($1)`,
		now.AddDate(0, 0, -rawEventRetentionDays)); err != nil {
		return 0, fmt.Errorf("telemetryrollup: pruning the raw events: %w", err)
	}
	return len(order), nil
}
