package scheduler

// The scheduler_watchdog job (apps.realtime.jobs._do_scheduler_watchdog
// over SchedulerHealthService.job_health): every registry job's health from
// its recorded runs (never run once due, failed last time, or overdue past
// the registry's max_interval_minutes), one notice per unhealthy job to every
// active Admin, and the notice of a job healthy again closed.

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

//go:embed registry_health.json
var registryHealthJSON []byte

const (
	jobUnhealthyEvent = "scheduler.job_unhealthy"
	watchdogJob       = "scheduler_watchdog"
)

// registryJob is one registry entry, in the registry's order: its name and
// how long it may go without a successful run.
type registryJob struct {
	name        string
	maxInterval time.Duration
}

func registryJobs() ([]registryJob, error) {
	var raw [][2]json.RawMessage
	if err := json.Unmarshal(registryHealthJSON, &raw); err != nil {
		return nil, fmt.Errorf("scheduler: reading the registry's intervals: %w", err)
	}
	out := make([]registryJob, 0, len(raw))
	for _, r := range raw {
		var j registryJob
		var minutes int
		if err := json.Unmarshal(r[0], &j.name); err != nil {
			return nil, err
		}
		if err := json.Unmarshal(r[1], &minutes); err != nil {
			return nil, err
		}
		j.maxInterval = time.Duration(minutes) * time.Minute
		out = append(out, j)
	}
	return out, nil
}

// jobHealth is job_health's reading of one job.
type jobHealth struct {
	status, severity string
	lastSuccess      *time.Time
	failures         int
	lastError        string
}

// healthOf is job_health's rule over what the runs table says.
func healthOf(job registryJob, latestStatus *string, latestError *string, lastSuccess *time.Time, failures int,
	firstDue *time.Time, now time.Time) jobHealth {
	h := jobHealth{lastSuccess: lastSuccess, failures: failures}
	neverRun := latestStatus == nil
	notDueYet := neverRun && firstDue != nil && firstDue.After(now)
	overdue := false
	switch {
	case lastSuccess != nil:
		overdue = now.Sub(*lastSuccess) > job.maxInterval
	case neverRun && !notDueYet:
		overdue = true
	}
	failed := latestStatus != nil && *latestStatus == "failed"
	switch {
	case neverRun && notDueYet:
		h.status, h.severity = "scheduled", "ok"
	case neverRun:
		h.status, h.severity = "never_run", "critical"
	case failed:
		h.status, h.severity = "failed", "critical"
	case overdue:
		h.status, h.severity = "overdue", "high"
	default:
		h.status, h.severity = "healthy", "ok"
	}
	if failed && latestError != nil {
		h.lastError = *latestError
	}
	return h
}

// readJobHealth reads one job's runs. Django records its own run as running
// before the body starts, so job_health sees the watchdog's run in flight:
// it is that job's latest run, and the scheduler started no later than it.
func readJobHealth(ctx context.Context, tx pgx.Tx, job registryJob, schedules map[string]Cron, names []string,
	now time.Time) (jobHealth, error) {
	var latestStatus, latestError *string
	err := tx.QueryRow(ctx, `SELECT status, error_message FROM scheduled_job_execution WHERE job_name = $1
ORDER BY started_at DESC LIMIT 1`, job.name).Scan(&latestStatus, &latestError)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return jobHealth{}, fmt.Errorf("scheduler: reading %s's last run: %w", job.name, err)
	}
	if job.name == watchdogJob {
		running := "running"
		latestStatus, latestError = &running, nil
	}
	var lastSuccess *time.Time
	err = tx.QueryRow(ctx, `SELECT started_at FROM scheduled_job_execution WHERE job_name = $1 AND status = 'success'
ORDER BY started_at DESC LIMIT 1`, job.name).Scan(&lastSuccess)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return jobHealth{}, fmt.Errorf("scheduler: reading %s's last success: %w", job.name, err)
	}
	var failures int
	if err := tx.QueryRow(ctx, `SELECT count(*)::int FROM scheduled_job_execution WHERE job_name = $1 AND status = 'failed'`,
		job.name).Scan(&failures); err != nil {
		return jobHealth{}, fmt.Errorf("scheduler: counting %s's failures: %w", job.name, err)
	}
	var firstDue *time.Time
	if latestStatus == nil {
		var started *time.Time
		if err := tx.QueryRow(ctx, `SELECT min(started_at) FROM scheduled_job_execution WHERE job_name = ANY($1)`, names).
			Scan(&started); err != nil {
			return jobHealth{}, fmt.Errorf("scheduler: reading when the scheduler started: %w", err)
		}
		if started == nil || now.Before(*started) {
			started = &now
		}
		if c, ok := schedules[job.name]; ok && started != nil {
			// get_next_fire_time(None, started): the first firing at or after it.
			if first := c.Next(started.Add(-time.Nanosecond)); !first.IsZero() {
				firstDue = &first
			}
		}
	}
	return healthOf(job, latestStatus, latestError, lastSuccess, failures, firstDue, now), nil
}

// pyDatetime is str() of an aware datetime read back in UTC.
func pyDatetime(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02 15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02 15:04:05.000000") + "+00:00"
}

// watchdogNotice is the notice of one unhealthy job.
func watchdogNotice(job string, h jobHealth) activities.Notice {
	last := "never"
	if h.lastSuccess != nil {
		last = pyDatetime(*h.lastSuccess)
	}
	words := strings.ReplaceAll(h.status, "_", " ")
	words = strings.ToUpper(words[:1]) + words[1:]
	priority := "normal"
	if h.severity == "critical" {
		priority = "high"
	}
	return activities.Notice{
		Title: fmt.Sprintf("Background job %s is %s", job, h.status),
		Body: strings.TrimSpace(fmt.Sprintf("%s. Last successful run: %s. %d recorded failure(s). %s", words, last,
			h.failures, h.lastError)),
		Event: jobUnhealthyEvent, Category: "platform", ContextType: "scheduled_job", Priority: priority,
	}
}

func activeAdmins(ctx context.Context, tx pgx.Tx) ([]activities.NoticeTo, error) {
	rows, err := tx.Query(ctx, `SELECT id FROM "user" WHERE is_active AND deleted_at IS NULL
  AND roles @> ARRAY['Admin']::varchar[] ORDER BY created_at DESC`)
	if err != nil {
		return nil, fmt.Errorf("scheduler: reading the Admins: %w", err)
	}
	defer rows.Close()
	var out []activities.NoticeTo
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, activities.NoticeTo{UserID: id, Route: "/dashboard", Label: "View Dashboard"})
	}
	return out, rows.Err()
}

// Watchdog is _do_scheduler_watchdog; it says how many notices it raised.
func Watchdog(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, push activities.NoticePush) (int, error) {
	jobs, err := registryJobs()
	if err != nil {
		return 0, err
	}
	schedules, err := djangoSchedules(kampala)
	if err != nil {
		return 0, err
	}
	names := make([]string, 0, len(jobs))
	for _, j := range jobs {
		names = append(names, j.name)
	}
	admins, err := activeAdmins(ctx, tx)
	if err != nil {
		return 0, err
	}
	raised := 0
	for _, job := range jobs {
		h, err := readJobHealth(ctx, tx, job, schedules, names, now)
		if err != nil {
			return raised, err
		}
		if h.severity == "ok" {
			if _, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, 'scheduled_job', $2, $3)`,
				jobUnhealthyEvent, job.name, now); err != nil {
				return raised, fmt.Errorf("scheduler: closing %s's notice: %w", job.name, err)
			}
			continue
		}
		if len(admins) == 0 {
			continue
		}
		if _, err := activities.NotifyInTx(ctx, tx, push, slog.Default(), now, job.name, watchdogNotice(job.name, h), admins); err != nil {
			return raised, fmt.Errorf("scheduler: telling the Admins about %s: %w", job.name, err)
		}
		raised++
	}
	return raised, nil
}
