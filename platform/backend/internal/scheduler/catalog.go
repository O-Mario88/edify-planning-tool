package scheduler

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/acting"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/actionsweep"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/autopilotjobs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btcases"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closurepages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dataqualityscan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/debriefs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iasampling"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationjobs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/telemetryrollup"
)

// JobMeta documents every operational scheduled job migrated from Django's
// apps/realtime/registry.py (41 jobs total) into the standalone Go scheduler.
type JobMeta struct {
	Name        string
	LockKey     int64
	Interval    time.Duration
	Owner       string // "go-scheduler" | "go-analytics-trigger"
	Disposition string // "native-go-mutation" | "native-go-notification" | "native-go-maintenance" | "native-go-analytics-trigger"
	Query       string // fallback/inspection query when no mutation applies
}

// UgandaCutoverJobs is the complete 41-job registry replacing Django's
// APScheduler (apps/realtime/registry.py) under single-executor PostgreSQL
// advisory locks in Africa/Kampala time.
var UgandaCutoverJobs = []JobMeta{
	{Name: "weekly_fund_request", LockKey: 400201, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM weekly_fund_request WHERE status = 'submitted_to_pl'"},
	{Name: "monthly_work_plan", LockKey: 400202, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM monthly_work_plan_budget"},
	{Name: "notification_escalation", LockKey: 400203, Interval: 30 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM notification WHERE status = 'unread'"},
	{Name: "daily_digest", LockKey: 400204, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM notification_preference WHERE email_enabled"},
	{Name: "daily_plan_notifications", LockKey: 400205, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM activity WHERE deleted_at IS NULL AND planned_date = CURRENT_DATE"},
	{Name: "activity_reminders", LockKey: 400206, Interval: 1 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM activity WHERE deleted_at IS NULL AND status = 'scheduled'"},
	{Name: "day_off_alerts", LockKey: 400207, Interval: 6 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM leave WHERE status = 'approved'"},
	{Name: "verification_reminders", LockKey: 400208, Interval: 6 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM activity WHERE deleted_at IS NULL AND status = 'submitted_to_pl'"},
	{Name: "acting_lifecycle", LockKey: 400209, Interval: 1 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM acting_assignment"},
	{Name: "target_ledger_sync", LockKey: 400210, Interval: 6 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM monthly_personal_target"},
	{Name: "hand_in_entered_work", LockKey: 400211, Interval: 2 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM activity WHERE deleted_at IS NULL AND status = 'in_progress'"},
	{Name: "pd_reminders", LockKey: 400212, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM pd_request"},
	{Name: "loan_tracking_notifications", LockKey: 400213, Interval: 6 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM bt_mfi_loan WHERE deleted_at IS NULL"},
	{Name: "school_action_sweep", LockKey: 400214, Interval: 1 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM team_action WHERE state IN ('open','acknowledged','in_progress')"},
	{Name: "planning_followup_sweep", LockKey: 400215, Interval: 1 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM planning_oversight_follow_up"},
	{Name: "planning_oversight_warm", LockKey: 400216, Interval: 30 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM school WHERE deleted_at IS NULL"},
	{Name: "cost_reprice_sweep", LockKey: 400217, Interval: 10 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM daily_visit_costs_to_follow"},
	{Name: "execution_period_snapshots", LockKey: 400218, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM activity WHERE deleted_at IS NULL"},
	{Name: "escalation_sla_sweep", LockKey: 400219, Interval: 1 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM leadership_escalation WHERE status <> 'resolved'"},
	{Name: "field_debrief_recurring_issues", LockKey: 400220, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM daily_debrief WHERE deleted_at IS NULL"},
	{Name: "daily_debrief_reminders", LockKey: 400221, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM daily_debrief_action WHERE status = 'open'"},
	{Name: "weekly_debrief_reports", LockKey: 400222, Interval: 7 * 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM daily_debrief WHERE deleted_at IS NULL"},
	{Name: "analytics_report_delivery", LockKey: 400223, Interval: 15 * time.Minute, Owner: "go-analytics-trigger", Disposition: "native-go-analytics-trigger", Query: "SELECT 1"},
	{Name: "fiscal_year_rollover", LockKey: 400224, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT 1"},
	{Name: "performance_readiness", LockKey: 400225, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM hr_performance_review"},
	{Name: "mfa_challenge_purge", LockKey: 400226, Interval: 1 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT 1"},
	{Name: "autopilot_weekly_proposals", LockKey: 400227, Interval: 7 * 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT 1"},
	{Name: "audit_chain_seal", LockKey: 400228, Interval: 5 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM audit_log"},
	{Name: "outbox_drain", LockKey: 400229, Interval: 1 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT 1"},
	{Name: "data_quality_scan", LockKey: 400230, Interval: 6 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM school WHERE deleted_at IS NULL"},
	{Name: "ssa_recommendation_sync", LockKey: 400231, Interval: 6 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM ssa_record WHERE deleted_at IS NULL"},
	{Name: "interaction_rollup", LockKey: 400232, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT 1"},
	{Name: "document_lifecycle", LockKey: 400233, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT count(*) FROM document_asset WHERE archived_at IS NULL"},
	{Name: "admin_maintenance_generation", LockKey: 400234, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT 1"},
	{Name: "scheduler_history_prune", LockKey: 400235, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-mutation", Query: "SELECT 1"},
	{Name: "closure_checklist_refresh", LockKey: 400236, Interval: 30 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT 1"},
	{Name: "scheduler_watchdog", LockKey: 400237, Interval: 30 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT 1"},
	{Name: "ia_verification_digest", LockKey: 400238, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-notification", Query: "SELECT count(*) FROM activity WHERE deleted_at IS NULL AND status = 'ia_verified'"},
	{Name: "verification_sampling", LockKey: 400239, Interval: 24 * time.Hour, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT count(*) FROM ia_verification_sample"},
	{Name: "export_jobs", LockKey: 400240, Interval: 1 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT 1"},
	{Name: "bulk_completion", LockKey: 400241, Interval: 5 * time.Minute, Owner: "go-scheduler", Disposition: "native-go-maintenance", Query: "SELECT 1"},
}

// notRunByGo are the existing jobs Go neither runs nor records as run, each
// with the existing function and why. A run recorded without its work would
// read as healthy on Platform Health, and for the queue workers it would do
// harm: the existing upload and export pages queue a large bulk completion
// or an export only while they see a recent successful run of the worker
// (worker_is_running), so a Go run recorded without the work would leave
// each queued upload or export waiting for ever; with no run seen, the pages
// complete the work in the request, as they do with no worker
// (docs/migration/189 §4).
var notRunByGo = map[string]string{
	"bulk_completion": "apps.bulk_completion.worker.work: Go has no page that queues an upload yet",
	"export_jobs":     "apps.reports.export_jobs.work: Go has no page that queues an export yet",
}

// KampalaOperationalFY returns the Uganda fiscal year (Oct 1 – Sep 30) in
// Africa/Kampala timezone for moment t.
func KampalaOperationalFY(t time.Time) (int, error) {
	loc, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		return 0, fmt.Errorf("scheduler: loading Africa/Kampala: %w", err)
	}
	local := t.In(loc)
	if local.Month() >= time.October {
		return local.Year() + 1, nil
	}
	return local.Year(), nil
}

// BuildUgandaJobs turns UgandaCutoverJobs into executable scheduler.Job entries
// backed by pool using wall-clock time.
func BuildUgandaJobs(pool *pgxpool.Pool) []Job {
	return BuildUgandaJobsWithClock(pool, time.Now, "go-scheduler")
}

// BuildUgandaJobsWithClock builds all 41 Uganda operational jobs with an
// injectable clock and runner identity, executing real Go business logic and
// recording every run into public.scheduled_job_execution.
func BuildUgandaJobsWithClock(pool *pgxpool.Pool, nowFn func() time.Time, runnerName string) []Job {
	if nowFn == nil {
		nowFn = time.Now
	}
	if runnerName == "" {
		runnerName = "go-scheduler"
	}
	writer := notificationcenter.NewWriter(pool, nowFn)
	pricing := activities.NewNativePricing(pool, writer)
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		kampala = time.FixedZone("EAT", 3*3600)
	}
	schedules, err := djangoSchedules(kampala)
	if err != nil {
		panic(err) // schedules.json is the registry, embedded at build
	}

	out := make([]Job, 0, len(UgandaCutoverJobs))
	for _, meta := range UgandaCutoverJobs {
		m := meta
		var schedule func(time.Time) time.Time
		if c, ok := schedules[m.Name]; ok {
			schedule = c.Next
		}
		out = append(out, Job{
			Name:     m.Name,
			LockKey:  m.LockKey,
			Interval: m.Interval,
			Schedule: schedule,
			Run: func(ctx context.Context) error {
				if pool == nil {
					return nil
				}
				if _, handedOn := notRunByGo[m.Name]; handedOn {
					return nil
				}
				started := nowFn().UTC()
				processed, err := executeJob(ctx, pool, writer, pricing, m, started)
				completed := nowFn().UTC()
				status := "success"
				errMsg := ""
				if err != nil {
					status = "failed"
					errMsg = err.Error()
				}
				_ = recordExecution(ctx, pool, m.Name, started, completed, status, processed, errMsg, runnerName)
				return err
			},
		})
	}
	return out
}

func recordExecution(
	ctx context.Context, pool *pgxpool.Pool,
	jobName string, started, completed time.Time, status string, records int, errMsg, runner string,
) error {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var id string
	if err := tx.QueryRow(ctx,
		`SELECT gateway_scheduler.record_execution($1, $2, $3, $4, $5, $6, $7)`,
		jobName, started, completed, status, records, errMsg, runner,
	).Scan(&id); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func executeJob(
	ctx context.Context,
	pool *pgxpool.Pool,
	writer *notificationcenter.Writer,
	pricing *activities.NativePricing,
	m JobMeta,
	now time.Time,
) (int, error) {
	loc, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		loc = time.UTC
	}
	localNow := now.In(loc)

	switch m.Name {
	case "cost_reprice_sweep":
		return pricing.SettleUnsettled(ctx, 50)

	case "mfa_challenge_purge":
		// MFA_CHALLENGE_RETENTION is seven days.
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.purge_mfa_challenges($1)`, now.AddDate(0, 0, -7))

	case "acting_lifecycle":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return acting.Sweep(ctx, tx, localNow, now, push) })

	case "notification_escalation":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.escalate_stale_notifications($1, $2)`, now.Add(-48*time.Hour), now)

	case "school_action_sweep":
		// action_service.resolve_due_actions, then mark_overdue_actions: each
		// active action's condition read again through the engine of its
		// kind, the cleared ones closed, the late ones flagged overdue.
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		day := time.Date(localNow.Year(), localNow.Month(), localNow.Day(), 0, 0, 0, 0, time.UTC)
		return actionsweep.Sweep(ctx, pool, push, now, day, slog.Default())

	case "outbox_drain":
		// apps.outbox.services.drain, for the event types Go handles; the
		// rest stay queued for a handler.
		return outboxWorker(pool, writer, func() time.Time { return time.Now() }, "go-scheduler").Drain(ctx, outboxBudget)

	case "execution_period_snapshots":
		// country_execution.snapshots.lock_ended_periods: the figures are read
		// through the gateway's read session; each row is written by the
		// owned function.
		day := time.Date(localNow.Year(), localNow.Month(), localNow.Day(), 0, 0, 0, 0, time.UTC)
		return planningmonitor.LockEndedPeriods(ctx, pool, func(ctx context.Context, country string,
			w planningmonitor.SnapshotWindow, snap planningmonitor.PeriodSnapshot) (bool, error) {
			return lockExecutionSnapshot(ctx, pool, country, w, snap, now)
		}, day, day)

	case "scheduler_history_prune":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.prune_scheduler_history($1)`, now)

	case "audit_chain_seal":
		// seal_pending chains rows the existing application wrote unsealed
		// inside a caller's transaction. Go appends every row sealed and may
		// not read payloads, so there is nothing for it to seal; rows left
		// unsealed (a lost commit hook) are reported, so the watchdog says so,
		// rather than counted as sealed.
		var unsealed int
		if err := pool.QueryRow(ctx, `SELECT gateway_scheduler.verify_audit_chain()`).Scan(&unsealed); err != nil {
			return 0, err
		}
		if unsealed > 0 {
			return 0, fmt.Errorf("scheduler: %d audit rows are unsealed; the existing application's seal_pending chains them", unsealed)
		}
		return 0, nil

	case "hand_in_entered_work":
		// Each piece of work commits on its own, as the existing job's do.
		review := plreview.NewReviewService(pool, func() time.Time { return now }).
			WithSalesforceSync(os.Getenv("SALESFORCE_SYNC_ENABLED") == "1")
		return review.HandInEnteredWork(ctx, loc)

	case "admin_maintenance_generation":
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return adminops.GenerateDueMaintenance(ctx, tx, now, loc) })

	case "weekly_fund_request":
		// Deliberately nothing, as the existing job: draft weekly fund
		// requests are made per owner when work is scheduled, and the job's
		// old regeneration once filed the whole year's national spend as one
		// request (apps.realtime.jobs._do_weekly_fund_request). The slot is
		// kept so the schedule and health tooling still see it.
		return 0, nil

	case "monthly_work_plan":
		// Next month's country budget (_do_monthly_work_plan): its month from
		// the UTC clock and its year as the existing job reckons it.
		utc := now.UTC()
		nextMonth := time.Date(utc.Year(), utc.Month(), 1, 0, 0, 0, 0, time.UTC).AddDate(0, 1, 0)
		fy := nextMonth.Year()
		if nextMonth.Month() >= time.October {
			fy++
		}
		return callIntRW(ctx, pool,
			`SELECT gateway_scheduler.upsert_monthly_budget_draft($1, $2, $3, $4)`,
			strconv.Itoa(fy), nextMonth.Format("2006-01"), "Uganda", now)

	case "document_lifecycle":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return notificationjobs.DocumentLifecycle(ctx, tx, now, loc, push) })

	case "activity_reminders":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return notificationjobs.ActivityReminders(ctx, tx, now, loc, notificationjobs.Notices{Push: push})
		})

	case "daily_plan_notifications":
		// _do_daily_planning_notices: the day's plan notices, then the
		// recruit sweep, which never stops the first being counted as sent.
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		notices := notificationjobs.Notices{Push: push}
		sent, err := inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return notificationjobs.DailyPlan(ctx, tx, now, loc, notices)
		})
		if err != nil {
			return 0, err
		}
		opened, err := inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return notificationjobs.RecruitSweep(ctx, tx, now, notices) })
		if err != nil {
			slog.Default().ErrorContext(ctx, "scheduler: the recruit sweep failed", "err", err)
			return sent, nil
		}
		return sent + opened, nil

	case "daily_digest":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return notificationjobs.DailyDigest(ctx, tx, now, loc, notificationjobs.Notices{Push: push})
		})

	case "day_off_alerts":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return notificationjobs.SendDayOffAlerts(ctx, tx, now, loc, push, nil)
		})

	case "pd_reminders":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return notificationjobs.SendPDReminders(ctx, tx, now, loc, push) })

	case "daily_debrief_reminders":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return debriefs.DebriefReminders(ctx, tx, now, loc, debriefs.RoleBridgeFrom(os.Getenv), push, nil)
		})

	case "ia_verification_digest":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return notificationjobs.SendIADigest(ctx, tx, now, loc, push) })

	case "scheduler_watchdog":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return Watchdog(ctx, tx, now, loc, push) })

	case "verification_reminders":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return plreview.VerificationReminders(ctx, tx, now, loc, push, nil)
		})

	case "escalation_sla_sweep":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return notificationjobs.SweepOverdueEscalations(ctx, tx, now, push) })

	case "planning_followup_sweep":
		// country_oversight.followups.sweep: every open follow-up's gap read
		// again through Go's Country Oversight and Country Execution figures,
		// its live figure kept, and one whose gap cleared closed by the system.
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		checked, _, err := planningmonitor.SweepFollowUps(ctx, pool, push, now, slog.Default())
		return checked, err

	case "ssa_recommendation_sync":
		var saved []string
		n, err := inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			count, plans, err := activities.SyncSSARecommendations(ctx, tx, now, loc, slog.Default())
			saved = plans
			return count, err
		})
		if err != nil {
			return n, err
		}
		// Each saved plan's package credit, after the commit, on its own.
		for _, id := range saved {
			if _, err := inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
				_, err := activities.CreditSchoolActivity(ctx, tx, id, loc, now)
				return 0, err
			}); err != nil {
				return n, err
			}
		}
		return n, nil

	case "verification_sampling":
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return iasampling.Draw(ctx, tx, now, loc) })

	case "closure_checklist_refresh":
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return closurepages.RefreshOpen(ctx, tx, now) })

	case "loan_tracking_notifications":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return btcases.LoanTracking(ctx, tx, now, loc, btcases.Notices{Push: push})
		})

	case "performance_readiness":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return notificationjobs.PerformanceReadiness(ctx, tx, now, loc, notificationjobs.Notices{Push: push})
		})

	case "field_debrief_recurring_issues":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			result, err := debriefs.ScanRecurringIssues(ctx, tx, now, loc, push, nil)
			return result.Created + result.Updated, err
		})

	case "weekly_debrief_reports":
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return debriefs.WeeklyReports(ctx, tx, now, loc) })

	case "data_quality_scan":
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			result, err := dataqualityscan.Scan(ctx, tx, now)
			return result.Schools, err
		})

	case "target_ledger_sync":
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return targets.SyncLedgers(ctx, tx, schooldirectory.OperationalFY(localNow), now)
		})

	case "planning_oversight_warm":
		// The job builds the existing pages' cached Country Oversight and
		// Execution figures before readers ask; Go's pages keep no such cache,
		// so there is nothing for Go to warm.
		return 0, nil

	case "autopilot_weekly_proposals":
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return autopilotjobs.WeeklyProposals(ctx, tx, now, loc, slog.Default())
		})

	case "interaction_rollup":
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) { return telemetryrollup.Rollup(ctx, tx, now, loc) })

	case "fiscal_year_rollover":
		// ensure_current_fiscal_year: once a year, from 1 October, the year's
		// roll-over (year-end snapshots, the new cycles, the schools' SSA
		// projection reset, every officer's draft agreement). A year whose
		// roll-over is recorded complete has nothing to do, which is every
		// run until the next 1 October. The roll-over itself needs the
		// performance engine, which is not built in Go yet: a year begun
		// without it fails here, so the watchdog tells the Admins, rather
		// than reading as a healthy run (docs/migration/189 §4).
		fy := schooldirectory.OperationalFY(localNow)
		var done bool
		if err := pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM hr_fiscal_year_rollover WHERE fy = $1 AND completed_at IS NOT NULL)`,
			fy).Scan(&done); err != nil {
			return 0, err
		}
		if !done {
			return 0, fmt.Errorf("scheduler: FY%s has begun and its roll-over is not recorded complete; Go does not roll a year "+
				"over yet, so run the existing roll-over (ensure_current_fiscal_year)", fy)
		}
		return 0, nil

	case "analytics_report_delivery":
		// deliver_due_schedules: each due schedule's analytics snapshot sent
		// to its owner's inbox. The snapshot is built from the Analytics
		// dashboard, which is not built in Go yet: with none due there is
		// nothing to do; one due fails here, so the watchdog tells the Admins,
		// rather than reading as delivered (docs/migration/189 §4).
		var due int
		if err := pool.QueryRow(ctx, `SELECT count(*)::int FROM analytics_report_schedule WHERE is_active AND next_run_at <= $1`,
			now).Scan(&due); err != nil {
			return 0, err
		}
		if due > 0 {
			return 0, fmt.Errorf("scheduler: %d analytics report schedule(s) are due and Go does not build the snapshot yet; "+
				"run the existing delivery (deliver_due_schedules)", due)
		}
		return 0, nil

	default:
		var n int64
		if err := pool.QueryRow(ctx, m.Query).Scan(&n); err != nil {
			return 0, err
		}
		return int(n), nil
	}
}

// inTx runs one job's writes in a read-write transaction of their own.
func inTx(ctx context.Context, pool *pgxpool.Pool, run func(pgx.Tx) (int, error)) (int, error) {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	n, err := run(tx)
	if err != nil {
		return 0, err
	}
	return n, tx.Commit(ctx)
}

func callIntRW(ctx context.Context, pool *pgxpool.Pool, sql string, args ...any) (int, error) {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var n int
	if err := tx.QueryRow(ctx, sql, args...).Scan(&n); err != nil {
		return 0, err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, err
	}
	return n, nil
}

// lockExecutionSnapshot writes one period's original snapshot through the
// owned function (false when the period was locked meanwhile).
func lockExecutionSnapshot(ctx context.Context, pool *pgxpool.Pool, country string, w planningmonitor.SnapshotWindow,
	snap planningmonitor.PeriodSnapshot, now time.Time) (bool, error) {
	parts := make([][]byte, 0, 4)
	for _, v := range []any{snap.Figures, snap.Channels, snap.Hierarchy, snap.FollowUps} {
		b, err := json.Marshal(v)
		if err != nil {
			return false, fmt.Errorf("scheduler: encoding the snapshot: %w", err)
		}
		parts = append(parts, b)
	}
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var wrote bool
	if err := tx.QueryRow(ctx, `SELECT gateway_scheduler.lock_execution_snapshot($1, $2, $3, $4, $5::date, $6::date, $7, $8::date, $9,
  $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14)`, cuid.New(), country, w.FY(), w.Period(), w.Start(), w.End(), w.Label(),
		snap.AsOf, snap.StagePolicy, string(parts[0]), string(parts[1]), string(parts[2]), string(parts[3]), now).Scan(&wrote); err != nil {
		return false, fmt.Errorf("scheduler: locking the snapshot: %w", err)
	}
	return wrote, tx.Commit(ctx)
}

// LockExecutionSnapshotsFor runs the execution snapshot close as if on day
// (a day at UTC midnight), the required slots read on the application's
// own day of now; for proving the close against the existing one.
func LockExecutionSnapshotsFor(ctx context.Context, pool *pgxpool.Pool, day, now time.Time) (int, error) {
	loc, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		loc = time.UTC
	}
	local := now.In(loc)
	live := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	return planningmonitor.LockEndedPeriods(ctx, pool, func(ctx context.Context, country string,
		w planningmonitor.SnapshotWindow, snap planningmonitor.PeriodSnapshot) (bool, error) {
		return lockExecutionSnapshot(ctx, pool, country, w, snap, now)
	}, day, live)
}
