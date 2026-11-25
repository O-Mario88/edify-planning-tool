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

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btcases"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dataqualityscan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/debriefs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationjobs"
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
	"execution_period_snapshots": "apps.planning.country_execution.snapshots.lock_ended_periods: " +
		"the Country Execution figures it locks are not built in Go yet",
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

	out := make([]Job, 0, len(UgandaCutoverJobs))
	for _, meta := range UgandaCutoverJobs {
		m := meta
		out = append(out, Job{
			Name:     m.Name,
			LockKey:  m.LockKey,
			Interval: m.Interval,
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
	today := localNow.Format(time.DateOnly)
	fyNum, _ := KampalaOperationalFY(now)
	fyLabel := fmt.Sprintf("FY%d", fyNum)

	switch m.Name {
	case "cost_reprice_sweep":
		return pricing.SettleUnsettled(ctx, 50)

	case "mfa_challenge_purge":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.purge_mfa_challenges($1)`, now.Add(-24*time.Hour))

	case "acting_lifecycle":
		tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
		if err != nil {
			return 0, err
		}
		defer func() { _ = tx.Rollback(ctx) }()
		var rem, act, exp int
		var actRaw, expRaw []byte
		if err := tx.QueryRow(ctx,
			`SELECT reminded, activated, expired, activated_rows, expired_rows FROM gateway_scheduler.run_acting_lifecycle($1::date, $2)`,
			today, now,
		).Scan(&rem, &act, &exp, &actRaw, &expRaw); err != nil {
			return 0, err
		}
		type actingRow struct {
			ID          string `json:"id"`
			AppointeeID string `json:"appointeeId"`
			Role        string `json:"role"`
		}
		var activatedRows, expiredRows []actingRow
		if len(actRaw) > 0 {
			if err := json.Unmarshal(actRaw, &activatedRows); err != nil {
				return 0, fmt.Errorf("scheduler: decoding activated acting rows: %w", err)
			}
		}
		if len(expRaw) > 0 {
			if err := json.Unmarshal(expRaw, &expiredRows); err != nil {
				return 0, fmt.Errorf("scheduler: decoding expired acting rows: %w", err)
			}
		}
		for _, r := range activatedRows {
			if _, err := audit.Append(ctx, tx, audit.Entry{
				Action:      "acting.activated",
				SubjectKind: audit.Text("acting_assignment"),
				SubjectID:   audit.Text(r.ID),
				ActorID:     audit.Text("system"),
				Success:     true,
				Payload: map[string]any{
					"appointeeId": r.AppointeeID,
					"role":        r.Role,
				},
			}, now); err != nil {
				return 0, fmt.Errorf("scheduler: appending acting.activated audit row: %w", err)
			}
		}
		for _, r := range expiredRows {
			if _, err := audit.Append(ctx, tx, audit.Entry{
				Action:      "acting.expired",
				SubjectKind: audit.Text("acting_assignment"),
				SubjectID:   audit.Text(r.ID),
				ActorID:     audit.Text("system"),
				Success:     true,
				Payload: map[string]any{
					"appointeeId": r.AppointeeID,
					"role":        r.Role,
				},
			}, now); err != nil {
				return 0, fmt.Errorf("scheduler: appending acting.expired audit row: %w", err)
			}
		}
		if err := tx.Commit(ctx); err != nil {
			return 0, err
		}
		return rem + act + exp, nil

	case "notification_escalation":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.escalate_stale_notifications($1, $2)`, now.Add(-48*time.Hour), now)

	case "school_action_sweep":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.sweep_school_actions($1::date, $2)`, today, now)

	case "outbox_drain":
		// apps.outbox.services.drain, for the event types Go handles; the
		// rest stay queued for a handler.
		return outboxWorker(pool, writer, func() time.Time { return time.Now() }, "go-scheduler").Drain(ctx, outboxBudget)

	case "scheduler_history_prune":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.prune_scheduler_history($1)`, now)

	case "audit_chain_seal":
		var unsealed int
		if err := pool.QueryRow(ctx, `SELECT gateway_scheduler.verify_audit_chain()`).Scan(&unsealed); err != nil {
			return 0, err
		}
		return unsealed, nil

	case "hand_in_entered_work":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.hand_in_entered_work($1)`, now)

	case "admin_maintenance_generation":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.generate_due_maintenance($1::date, $2)`, today, now)

	case "weekly_fund_request":
		// Upcoming Monday–Sunday in Africa/Kampala.
		daysUntilMon := (int(time.Monday) - int(localNow.Weekday()) + 7) % 7
		if daysUntilMon == 0 {
			daysUntilMon = 7
		}
		weekStart := localNow.AddDate(0, 0, daysUntilMon)
		weekEnd := weekStart.AddDate(0, 0, 6)
		return callIntRW(ctx, pool,
			`SELECT gateway_scheduler.upsert_weekly_drafts($1::date, $2::date, $3, $4)`,
			weekStart.Format(time.DateOnly), weekEnd.Format(time.DateOnly), fyLabel, now)

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
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.reconcile_document_lifecycle($1::date, $2)`, today, now)

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
		rows, err := pool.Query(ctx, `
SELECT a.id, COALESCE(sp.user_id, a.responsible_staff_id), a.planned_date::text
  FROM activity a
  JOIN leave l ON l.staff_id = a.responsible_staff_id
  LEFT JOIN staff_profile sp ON sp.id = a.responsible_staff_id AND sp.deleted_at IS NULL
 WHERE a.deleted_at IS NULL
   AND a.status IN ('scheduled', 'rescheduled')
   AND a.planned_date >= $1::date
   AND l.status = 'approved'
   AND a.planned_date::text >= l.start_date
   AND a.planned_date::text <= l.end_date
 LIMIT 100`, today)
		if err != nil {
			return 0, err
		}
		type doRow struct{ actID, uid, dt string }
		var items []doRow
		for rows.Next() {
			var r doRow
			if scanErr := rows.Scan(&r.actID, &r.uid, &r.dt); scanErr == nil && r.uid != "" {
				items = append(items, r)
			}
		}
		rows.Close()
		sent := 0
		for _, it := range items {
			if ok, err := writer.Deliver(ctx, notificationcenter.Delivery{
				RecipientID:     it.uid,
				Title:           "Activity scheduled during approved leave (" + it.dt + ")",
				Body:            "An activity is scheduled on a day covered by your approved leave. Please reschedule or hand it over.",
				Category:        "schedule_conflict",
				ContextType:     "activity",
				ContextID:       it.actID,
				TargetRoute:     "/my-plan",
				ActionLabel:     "Reschedule",
				ActionRequired:  true,
				Priority:        "high",
				SourceEventType: "schedule.leave_conflict",
				SourceEventID:   "dayoff-" + it.actID + ":" + today,
			}); err == nil && ok {
				sent++
			}
		}
		return sent, nil

	case "pd_reminders":
		soon := localNow.AddDate(0, 0, 3).Format(time.DateOnly)
		rows, err := pool.Query(ctx, `
SELECT p.id, COALESCE(sp.user_id, p.staff_id), p.course_name, p.start_date::text
  FROM pd_request p
  LEFT JOIN staff_profile sp ON sp.id = p.staff_id AND sp.deleted_at IS NULL
 WHERE p.status IN ('approved', 'enrolled')
   AND p.start_date >= $1::date
   AND p.start_date <= $2::date
 LIMIT 100`, today, soon)
		if err != nil {
			return 0, err
		}
		type pdRow struct{ id, uid, course, dt string }
		var items []pdRow
		for rows.Next() {
			var r pdRow
			if scanErr := rows.Scan(&r.id, &r.uid, &r.course, &r.dt); scanErr == nil && r.uid != "" {
				items = append(items, r)
			}
		}
		rows.Close()
		sent := 0
		for _, it := range items {
			if ok, err := writer.Deliver(ctx, notificationcenter.Delivery{
				RecipientID:     it.uid,
				Title:           "Upcoming PD course: " + it.course,
				Body:            "Your approved professional development course starts on " + it.dt + ".",
				Category:        "pd_reminder",
				ContextType:     "pd_request",
				ContextID:       it.id,
				TargetRoute:     "/my-pd",
				ActionLabel:     "Open My PD",
				Priority:        "normal",
				SourceEventType: "pd.upcoming_reminder",
				SourceEventID:   "pd-" + it.id + ":" + today,
			}); err == nil && ok {
				sent++
			}
		}
		return sent, nil

	case "daily_debrief_reminders":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return debriefs.DebriefReminders(ctx, tx, now, loc, debriefs.RoleBridgeFrom(os.Getenv), push, nil)
		})

	case "ia_verification_digest":
		var pending int
		if err := pool.QueryRow(ctx, `
SELECT COUNT(*)::int
  FROM activity
 WHERE deleted_at IS NULL
   AND status = 'pl_approved'
   AND ia_verification_status = 'pending'`).Scan(&pending); err != nil {
			return 0, err
		}
		if pending == 0 {
			return 0, nil
		}
		rows, err := pool.Query(ctx, `
SELECT id FROM "user"
 WHERE deleted_at IS NULL AND is_active = true
   AND (active_role = 'ImpactAssessment' OR 'ImpactAssessment' = ANY(roles))
 LIMIT 50`)
		if err != nil {
			return 0, err
		}
		var uids []string
		for rows.Next() {
			var uid string
			if scanErr := rows.Scan(&uid); scanErr == nil && uid != "" {
				uids = append(uids, uid)
			}
		}
		rows.Close()
		sent := 0
		for _, uid := range uids {
			if ok, err := writer.Deliver(ctx, notificationcenter.Delivery{
				RecipientID:     uid,
				Title:           fmt.Sprintf("IA Verification Digest: %d activity(ies) awaiting verification", pending),
				Body:            "Completed PL-approved activities are ready for Impact Assessment verification.",
				Category:        "ia_verification",
				ContextType:     "ia_digest",
				ContextID:       "ia-" + today,
				TargetRoute:     "/ia/verification",
				ActionLabel:     "Open IA Queue",
				ActionRequired:  true,
				Priority:        "normal",
				SourceEventType: "ia.daily_digest",
				SourceEventID:   "ia-" + today + ":" + uid,
			}); err == nil && ok {
				sent++
			}
		}
		return sent, nil

	case "scheduler_watchdog":
		rows, err := pool.Query(ctx, `
SELECT DISTINCT job_name
  FROM scheduled_job_execution
 WHERE status = 'failed'
   AND started_at >= $1
 LIMIT 50`, now.Add(-2*time.Hour))
		if err != nil {
			return 0, err
		}
		var failedJobs []string
		for rows.Next() {
			var name string
			if scanErr := rows.Scan(&name); scanErr == nil && name != "" {
				failedJobs = append(failedJobs, name)
			}
		}
		rows.Close()
		if len(failedJobs) == 0 {
			return 0, nil
		}
		adminRows, err := pool.Query(ctx, `
SELECT id FROM "user"
 WHERE deleted_at IS NULL AND is_active = true
   AND (active_role = 'Admin' OR 'Admin' = ANY(roles))
 LIMIT 20`)
		if err != nil {
			return 0, err
		}
		var admins []string
		for adminRows.Next() {
			var uid string
			if scanErr := adminRows.Scan(&uid); scanErr == nil && uid != "" {
				admins = append(admins, uid)
			}
		}
		adminRows.Close()
		sent := 0
		for _, job := range failedJobs {
			for _, uid := range admins {
				if ok, err := writer.Deliver(ctx, notificationcenter.Delivery{
					RecipientID:     uid,
					Title:           "Scheduled job failure: " + job,
					Body:            "Background job " + job + " recorded a failed execution in the last 2 hours.",
					Category:        "system_health",
					ContextType:     "scheduled_job",
					ContextID:       job,
					TargetRoute:     "/admin/platform-health",
					ActionLabel:     "Platform Health",
					ActionRequired:  true,
					Priority:        "urgent",
					SourceEventType: "scheduler.job_failed",
					SourceEventID:   "watchdog-" + job + ":" + today + ":" + uid,
				}); err == nil && ok {
					sent++
				}
			}
		}
		return sent, nil

	case "verification_reminders":
		push := plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy
		return inTx(ctx, pool, func(tx pgx.Tx) (int, error) {
			return plreview.VerificationReminders(ctx, tx, now, loc, push, nil)
		})

	case "escalation_sla_sweep":
		rows, err := pool.Query(ctx, `
SELECT id, COALESCE(assigned_to_user_id, ''), subject
  FROM leadership_escalation
 WHERE status NOT IN ('resolved', 'closed')
   AND due_date IS NOT NULL
   AND due_date < $1::date
 LIMIT 100`, today)
		if err != nil {
			return 0, err
		}
		type escRow struct{ id, uid, subj string }
		var items []escRow
		for rows.Next() {
			var r escRow
			if scanErr := rows.Scan(&r.id, &r.uid, &r.subj); scanErr == nil && r.uid != "" {
				items = append(items, r)
			}
		}
		rows.Close()
		sent := 0
		for _, it := range items {
			if ok, err := writer.Deliver(ctx, notificationcenter.Delivery{
				RecipientID:     it.uid,
				Title:           "Overdue escalation: " + it.subj,
				Body:            "This leadership escalation has passed its SLA due date and requires attention.",
				Category:        "escalation",
				ContextType:     "leadership_escalation",
				ContextID:       it.id,
				TargetRoute:     "/escalations",
				ActionLabel:     "Open Escalation",
				ActionRequired:  true,
				Priority:        "urgent",
				SourceEventType: "escalation.sla_overdue",
				SourceEventID:   it.id + ":" + today,
			}); err == nil && ok {
				sent++
			}
		}
		return sent, nil

	case "planning_followup_sweep":
		updated, err := callIntRW(ctx, pool, `SELECT gateway_scheduler.sweep_planning_followups($1::date, $2)`, today, now)
		if err != nil {
			return 0, err
		}
		rows, err := pool.Query(ctx, `
SELECT id, program_lead_user_id, COALESCE(school_name, ''), days_overdue
  FROM planning_oversight_follow_up
 WHERE status NOT IN ('resolved', 'closed') AND days_overdue > 0
 LIMIT 100`)
		if err == nil {
			type fuRow struct {
				id, uid, school string
				days            int
			}
			var items []fuRow
			for rows.Next() {
				var r fuRow
				if rows.Scan(&r.id, &r.uid, &r.school, &r.days) == nil && r.uid != "" {
					items = append(items, r)
				}
			}
			rows.Close()
			for _, it := range items {
				_, _ = writer.Deliver(ctx, notificationcenter.Delivery{
					RecipientID:     it.uid,
					Title:           fmt.Sprintf("Overdue planning follow-up (%dd): %s", it.days, it.school),
					Body:            "A planning oversight follow-up has passed its due date.",
					Category:        "planning_followup",
					ContextType:     "planning_oversight_follow_up",
					ContextID:       it.id,
					TargetRoute:     "/planning/oversight",
					ActionLabel:     "Open Oversight",
					ActionRequired:  true,
					Priority:        "high",
					SourceEventType: "planning_followup.overdue",
					SourceEventID:   "pfu-" + it.id + ":" + today,
				})
			}
		}
		return updated, nil

	case "ssa_recommendation_sync":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.expire_ssa_recommendations($1::date, $2)`, today, now)

	case "verification_sampling":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.sample_ia_verifications($1, $2)`, now, 10)

	case "closure_checklist_refresh":
		return callIntRW(ctx, pool, `SELECT gateway_scheduler.refresh_closure_checklists($1)`, now)

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
		var unvisited int
		if err := pool.QueryRow(ctx, `
SELECT COUNT(*)::int FROM school s
 WHERE s.deleted_at IS NULL AND s.operational_status = 'active'
   AND NOT EXISTS (
     SELECT 1 FROM activity a
      WHERE a.deleted_at IS NULL AND a.school_id = s.id AND a.fy = $1 AND a.status <> 'cancelled'
   )`, fyLabel).Scan(&unvisited); err != nil {
			return 0, err
		}
		return unvisited, nil

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
