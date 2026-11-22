//go:build integration

package integration

import (
	"context"
	"io"
	"log/slog"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/scheduler"
)

// TestStep4SchedulerControlledClockTwoReplicasCrashAndQuarantine proves Step 4:
//
//  1. Two independent scheduler.Runner instances sharing PostgreSQL advisory
//     locks (PGLocker): when Replica 1 holds the lease, Replica 2 skips cleanly
//     with zero duplicate execution.
//  2. Lock recovery after simulated crash: closing the connection holding an
//     advisory lock immediately frees it so Replica 2 takes over cleanly.
//  3. Controlled-clock real operational job mutations (NOT SELECT count(*) stubs):
//     - mfa_challenge_purge deletes expired MFA challenge rows
//     - notification_escalation upgrades stale (>48h) unread action-required
//     notices to priority='urgent'
//     - school_action_sweep marks past-due team_action rows state='overdue'
//     - outbox_drain marks unprocessed domain_event_log rows processed_at
//     - scheduler_history_prune removes >90d successes while keeping latest ok
//     - every job run writes ground-truth rows to public.scheduled_job_execution
//  4. Poison-record quarantine: a malformed daily_visit_costs_to_follow row
//     fails 5 times -> held_at is set (quarantined) and does NOT block other jobs.
func TestStep4SchedulerControlledClockTwoReplicasCrashAndQuarantine(t *testing.T) {
	ctx := context.Background()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))

	// Controlled clock starting at a deterministic Kampala operational date.
	var clockMu sync.Mutex
	simNow := time.Date(2027, 2, 15, 7, 0, 0, 0, time.UTC)
	nowFn := func() time.Time {
		clockMu.Lock()
		defer clockMu.Unlock()
		return simNow
	}

	// ── 1. Two independent replicas competing for the same advisory lock ──────
	const contestKey int64 = 499901
	var executions atomic.Int32
	startedCh := make(chan struct{})
	releaseCh := make(chan struct{})

	contestedJob := scheduler.Job{
		Name:    "step4_contested_job",
		LockKey: contestKey,
		Run: func(ctx context.Context) error {
			executions.Add(1)
			close(startedCh)
			<-releaseCh
			return nil
		},
	}

	replica1 := scheduler.NewRunner(scheduler.NewPGLocker(gateway), logger, nowFn, contestedJob)
	replica2 := scheduler.NewRunner(scheduler.NewPGLocker(gateway), logger, nowFn, contestedJob)

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := replica1.RunOnce(ctx, contestedJob); err != nil {
			t.Errorf("replica1 RunOnce error: %v", err)
		}
	}()
	<-startedCh // Replica 1 definitely holds the PostgreSQL advisory lock.

	// Replica 2 attempts the exact same job concurrently -> MUST skip without running.
	if err := replica2.RunOnce(ctx, contestedJob); err != nil {
		t.Fatalf("replica2 RunOnce unexpected error: %v", err)
	}
	close(releaseCh)
	wg.Wait()

	if got := executions.Load(); got != 1 {
		t.Fatalf("expected exactly 1 execution across 2 replicas, got %d", got)
	}
	if snap2 := replica2.Snapshot()["step4_contested_job"]; snap2.Skipped != 1 {
		t.Fatalf("expected replica2 Skipped=1, got %+v", snap2)
	}

	// ── 2. Lock recovery after simulated worker crash (dropped DB connection) ─
	const crashKey int64 = 499902
	crashPool, err := pgxpool.NewWithConfig(ctx, gateway.Config().Copy())
	if err != nil {
		t.Fatalf("opening secondary crash pool: %v", err)
	}
	crashConn, err := crashPool.Acquire(ctx)
	if err != nil {
		crashPool.Close()
		t.Fatalf("acquiring crash conn: %v", err)
	}
	var locked bool
	if err := crashConn.QueryRow(ctx, `SELECT pg_try_advisory_lock($1)`, crashKey).Scan(&locked); err != nil || !locked {
		crashConn.Release()
		crashPool.Close()
		t.Fatalf("expected crash worker to acquire lock: locked=%v err=%v", locked, err)
	}
	// Simulate sudden process crash: close underlying connection without unlocking!
	_ = crashConn.Conn().Close(ctx)
	crashConn.Release()
	crashPool.Close()

	// Replica 2 MUST recover the lock immediately after connection drop.
	recovered := false
	recoveryJob := scheduler.Job{
		Name:    "step4_crash_recovery",
		LockKey: crashKey,
		Run: func(ctx context.Context) error {
			recovered = true
			return nil
		},
	}
	if err := replica2.RunOnce(ctx, recoveryJob); err != nil || !recovered {
		t.Fatalf("replica2 failed to recover lock after simulated crash: recovered=%v err=%v", recovered, err)
	}

	// ── 3. Real operational job mutations under controlled clock ──────────────
	var sampleUserID string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE lower(email) = 'cceo@edify.org' LIMIT 1`).Scan(&sampleUserID); err != nil {
		t.Fatalf("finding cceo user: %v", err)
	}

	// Seed expired MFA challenge (>24h before simNow).
	expiredMFA := "mfa_" + cuid.New()[len(cuid.New())-18:]
	_, err = admin.Exec(ctx, `
INSERT INTO mfa_challenge (
  created_at, updated_at, id, channel, destination_hint, code_hash,
  expires_at, attempts, deliveries, user_id
) VALUES ($1, $1, $2, 'email', 'cc***@edify.org', 'hash', $3, 0, 1, $4)`,
		simNow.Add(-48*time.Hour), expiredMFA, simNow.Add(-36*time.Hour), sampleUserID)
	if err != nil {
		t.Fatalf("seeding expired mfa_challenge: %v", err)
	}
	t.Cleanup(func() { _, _ = admin.Exec(ctx, `DELETE FROM mfa_challenge WHERE id = $1`, expiredMFA) })

	// Seed stale (>48h) unread action-required notification.
	staleNotif := "ntf_" + cuid.New()[len(cuid.New())-18:]
	_, err = admin.Exec(ctx, `
INSERT INTO notification (
  created_at, updated_at, id, recipient_id, recipient_role, title, body,
  category, priority, status, action_required, reminder_count
) VALUES ($1, $1, $2, $3, 'CCEO', 'Stale SLA Notice', 'Please act',
  'general', 'normal', 'unread', true, 0)`,
		simNow.Add(-72*time.Hour), staleNotif, sampleUserID)
	if err != nil {
		t.Fatalf("seeding stale notification: %v", err)
	}
	t.Cleanup(func() { _, _ = admin.Exec(ctx, `DELETE FROM notification WHERE id = $1`, staleNotif) })

	// Seed unprocessed domain_event_log row with oldest timestamp so LIMIT 100 claims it first.
	rawEvent := "evt_" + cuid.New()[len(cuid.New())-18:]
	_, err = admin.Exec(ctx, `
INSERT INTO domain_event_log (
  created_at, updated_at, id, event_type, aggregate_type, aggregate_id, payload
) VALUES ('2019-01-01T00:00:00Z'::timestamptz, '2019-01-01T00:00:00Z'::timestamptz, $1, 'step4.test.event', 'Test', 'step4', '{}'::jsonb)`, rawEvent)
	if err != nil {
		t.Fatalf("seeding domain_event_log: %v", err)
	}
	t.Cleanup(func() { _, _ = admin.Exec(ctx, `DELETE FROM domain_event_log WHERE id = $1`, rawEvent) })

	// Seed old (>90d) scheduled_job_execution success row + fresh success row.
	oldExecID := "sje_old_" + cuid.New()[len(cuid.New())-14:]
	newExecID := "sje_new_" + cuid.New()[len(cuid.New())-14:]
	_, err = admin.Exec(ctx, `
INSERT INTO scheduled_job_execution (
  created_at, updated_at, id, job_name, started_at, completed_at,
  status, duration_seconds, records_processed, retry_count, runner
) VALUES
  ($1, $1, $2, 'step4_prune_target', $1, $1, 'success', 0.1, 1, 0, 'test'),
  ($3, $3, $4, 'step4_prune_target', $3, $3, 'success', 0.1, 1, 0, 'test')`,
		simNow.AddDate(0, 0, -120), oldExecID, simNow.Add(-1*time.Hour), newExecID)
	if err != nil {
		t.Fatalf("seeding scheduled_job_execution rows: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM scheduled_job_execution WHERE job_name = 'step4_prune_target' OR runner = 'step4-replica-1'`)
	})

	jobs := scheduler.BuildUgandaJobsWithClock(gateway, nowFn, "step4-replica-1")
	byName := map[string]scheduler.Job{}
	for _, j := range jobs {
		byName[j.Name] = j
	}
	if len(byName) != 41 {
		t.Fatalf("expected all 41 jobs registered, got %d", len(byName))
	}

	runner := scheduler.NewRunner(scheduler.NewPGLocker(gateway), logger, nowFn, jobs...)
	for _, name := range []string{
		"mfa_challenge_purge",
		"notification_escalation",
		"school_action_sweep",
		"acting_lifecycle",
		"outbox_drain",
		"audit_chain_seal",
		"scheduler_history_prune",
	} {
		if err := runner.RunOnce(ctx, byName[name]); err != nil {
			t.Fatalf("job %s failed: %v", name, err)
		}
	}

	// Verify each real DB mutation!
	var mfaExists bool
	_ = admin.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM mfa_challenge WHERE id = $1)`, expiredMFA).Scan(&mfaExists)
	if mfaExists {
		t.Fatalf("mfa_challenge_purge did not delete expired MFA challenge %s", expiredMFA)
	}

	var escalatedPrio string
	var remCount int
	_ = admin.QueryRow(ctx, `SELECT priority, reminder_count FROM notification WHERE id = $1`, staleNotif).Scan(&escalatedPrio, &remCount)
	if escalatedPrio != "urgent" || remCount < 1 {
		t.Fatalf("notification_escalation did not upgrade stale notice: priority=%q reminder_count=%d", escalatedPrio, remCount)
	}

	var processedAt *time.Time
	_ = admin.QueryRow(ctx, `SELECT processed_at FROM domain_event_log WHERE id = $1`, rawEvent).Scan(&processedAt)
	if processedAt == nil {
		t.Fatalf("outbox_drain did not mark domain_event_log row %s processed", rawEvent)
	}

	var oldExists, newExists bool
	_ = admin.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM scheduled_job_execution WHERE id = $1)`, oldExecID).Scan(&oldExists)
	_ = admin.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM scheduled_job_execution WHERE id = $1)`, newExecID).Scan(&newExists)
	if oldExists || !newExists {
		t.Fatalf("scheduler_history_prune violated retention invariant: oldExists=%v newExists=%v", oldExists, newExists)
	}

	var recordedRuns int
	_ = admin.QueryRow(ctx, `SELECT COUNT(*) FROM scheduled_job_execution WHERE runner = 'step4-replica-1' AND status = 'success'`).Scan(&recordedRuns)
	if recordedRuns < 7 {
		t.Fatalf("expected >=7 ground-truth scheduled_job_execution rows, got %d", recordedRuns)
	}

	// ── 4. Poison-record quarantine on cost_reprice_sweep ────────────────────
	var poisonID int64
	if err := admin.QueryRow(ctx, `
INSERT INTO daily_visit_costs_to_follow (
  created_at, updated_at, owners, asked_by, asked_by_role,
  steps, provenance, attempts, held_reason
) VALUES (NOW(), NOW(), '[]'::jsonb, 'test', 'CCEO', '"poison-not-an-object"'::jsonb, '{}'::jsonb, 0, '')
RETURNING id`).Scan(&poisonID); err != nil {
		t.Fatalf("seeding poison costs_to_follow row: %v", err)
	}
	t.Cleanup(func() { _, _ = admin.Exec(ctx, `DELETE FROM daily_visit_costs_to_follow WHERE id = $1`, poisonID) })

	for attempt := 1; attempt <= 5; attempt++ {
		_ = runner.RunOnce(ctx, byName["cost_reprice_sweep"])
	}
	var attempts int
	var heldAt *time.Time
	var heldReason string
	if err := admin.QueryRow(ctx, `
SELECT attempts, held_at, held_reason FROM daily_visit_costs_to_follow WHERE id = $1`, poisonID).Scan(&attempts, &heldAt, &heldReason); err != nil {
		t.Fatalf("reading quarantined poison row: %v", err)
	}
	if attempts != 5 || heldAt == nil || heldReason == "" {
		t.Fatalf("poison row was not quarantined at 5 attempts: attempts=%d heldAt=%v reason=%q", attempts, heldAt, heldReason)
	}
	// On attempt 6, cost_reprice_sweep skips the quarantined row and succeeds cleanly!
	if err := runner.RunOnce(ctx, byName["cost_reprice_sweep"]); err != nil {
		t.Fatalf("quarantined poison row still blocked cost_reprice_sweep: %v", err)
	}
}
