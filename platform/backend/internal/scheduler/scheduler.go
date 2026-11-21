// Package scheduler runs background jobs in Go with single-executor
// PostgreSQL advisory-lock leasing, graceful shutdown, and observable run
// outcomes. It replaces Django's APScheduler worker (runscheduler.py) job by
// job without overlapping runs across replicas.
package scheduler

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Job defines one recurring background task.
type Job struct {
	Name     string
	LockKey  int64
	Interval time.Duration
	Run      func(ctx context.Context) error
}

// JobStats records the latest execution outcome for observability.
type JobStats struct {
	Runs      int64
	Failures  int64
	Skipped   int64
	LastStart time.Time
	LastOK    time.Time
	LastError string
}

// Locker acquires and releases a non-blocking distributed lease for a job.
type Locker interface {
	TryLock(ctx context.Context, key int64) (unlock func(context.Context), acquired bool, err error)
}

// PGLocker uses PostgreSQL session-level advisory locks on a dedicated pooled
// connection so the lease is automatically released if the process dies.
type PGLocker struct {
	pool *pgxpool.Pool
}

// NewPGLocker builds a PostgreSQL advisory-lock Locker over pool.
func NewPGLocker(pool *pgxpool.Pool) *PGLocker {
	return &PGLocker{pool: pool}
}

// TryLock acquires pg_try_advisory_lock(key) on one acquired pool connection.
func (l *PGLocker) TryLock(ctx context.Context, key int64) (func(context.Context), bool, error) {
	conn, err := l.pool.Acquire(ctx)
	if err != nil {
		return nil, false, fmt.Errorf("scheduler: acquiring lease connection: %w", err)
	}
	var locked bool
	if err := conn.QueryRow(ctx, `SELECT pg_try_advisory_lock($1)`, key).Scan(&locked); err != nil {
		conn.Release()
		return nil, false, fmt.Errorf("scheduler: pg_try_advisory_lock(%d): %w", key, err)
	}
	if !locked {
		conn.Release()
		return nil, false, nil
	}
	return func(rctx context.Context) {
		_, _ = conn.Exec(rctx, `SELECT pg_advisory_unlock($1)`, key)
		conn.Release()
	}, true, nil
}

// Runner coordinates a set of Jobs under one Locker and Logger.
type Runner struct {
	locker Locker
	logger *slog.Logger
	now    func() time.Time
	jobs   []Job

	mu    sync.Mutex
	stats map[string]*JobStats
}

// NewRunner returns a Runner for jobs.
func NewRunner(locker Locker, logger *slog.Logger, now func() time.Time, jobs ...Job) *Runner {
	if now == nil {
		now = time.Now
	}
	stats := make(map[string]*JobStats, len(jobs))
	for _, j := range jobs {
		stats[j.Name] = &JobStats{}
	}
	return &Runner{locker: locker, logger: logger, now: now, jobs: jobs, stats: stats}
}

// RunOnce executes a single job if its lease is acquired; returns true when it
// ran and succeeded.
func (r *Runner) RunOnce(ctx context.Context, job Job) error {
	unlock, acquired, err := r.locker.TryLock(ctx, job.LockKey)
	if err != nil {
		r.record(job.Name, false, true, err)
		return err
	}
	if !acquired {
		r.record(job.Name, true, false, nil)
		return nil
	}
	defer func() {
		releaseCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		unlock(releaseCtx)
	}()

	started := r.now().UTC()
	runErr := job.Run(ctx)
	r.record(job.Name, false, false, runErr)
	if r.logger != nil {
		attrs := []slog.Attr{
			slog.String("job", job.Name),
			slog.Duration("duration", r.now().UTC().Sub(started)),
		}
		if runErr != nil {
			attrs = append(attrs, slog.String("error", runErr.Error()))
			r.logger.LogAttrs(ctx, slog.LevelError, "scheduler: job failed", attrs...)
		} else {
			r.logger.LogAttrs(ctx, slog.LevelInfo, "scheduler: job completed", attrs...)
		}
	}
	return runErr
}

// Start runs all registered jobs on their intervals until ctx is cancelled,
// waiting for all in-flight jobs to finish before returning.
func (r *Runner) Start(ctx context.Context) {
	var wg sync.WaitGroup
	for _, job := range r.jobs {
		j := job
		if j.Interval <= 0 {
			continue
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = r.RunOnce(ctx, j)
			ticker := time.NewTicker(j.Interval)
			defer ticker.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
					_ = r.RunOnce(ctx, j)
				}
			}
		}()
	}
	wg.Wait()
}

// Snapshot returns a copy of all job execution statistics.
func (r *Runner) Snapshot() map[string]JobStats {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make(map[string]JobStats, len(r.stats))
	for name, st := range r.stats {
		out[name] = *st
	}
	return out
}

func (r *Runner) record(name string, skipped, lockErr bool, err error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	st, ok := r.stats[name]
	if !ok {
		st = &JobStats{}
		r.stats[name] = st
	}
	now := r.now().UTC()
	if skipped {
		st.Skipped++
		return
	}
	st.Runs++
	st.LastStart = now
	if err != nil || lockErr {
		st.Failures++
		if err != nil {
			st.LastError = err.Error()
		}
		return
	}
	st.LastOK = now
	st.LastError = ""
}
