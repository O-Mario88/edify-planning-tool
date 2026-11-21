package scheduler

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type memLocker struct {
	mu   sync.Mutex
	held map[int64]bool
	fail error
}

func (m *memLocker) TryLock(_ context.Context, key int64) (func(context.Context), bool, error) {
	if m.fail != nil {
		return nil, false, m.fail
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.held == nil {
		m.held = map[int64]bool{}
	}
	if m.held[key] {
		return nil, false, nil
	}
	m.held[key] = true
	return func(context.Context) {
		m.mu.Lock()
		delete(m.held, key)
		m.mu.Unlock()
	}, true, nil
}

func TestRunnerSingleExecutorLeasePreventsDuplicateRuns(t *testing.T) {
	locker := &memLocker{held: map[int64]bool{101: true}}
	var ran atomic.Int32
	job := Job{
		Name:    "leased_job",
		LockKey: 101,
		Run: func(context.Context) error {
			ran.Add(1)
			return nil
		},
	}
	r := NewRunner(locker, nil, time.Now, job)
	// First attempt: lease already held by another replica -> skipped.
	if err := r.RunOnce(context.Background(), job); err != nil {
		t.Fatalf("unexpected error while lease held: %v", err)
	}
	if ran.Load() != 0 {
		t.Fatalf("job ran while another replica held lease")
	}
	if st := r.Snapshot()["leased_job"]; st.Skipped != 1 || st.Runs != 0 {
		t.Fatalf("unexpected stats after skip: %+v", st)
	}

	// Release the other replica's lease -> failover succeeds on next run.
	delete(locker.held, 101)
	if err := r.RunOnce(context.Background(), job); err != nil {
		t.Fatalf("expected failover run to succeed, got %v", err)
	}
	if ran.Load() != 1 {
		t.Fatalf("ran = %d, want 1", ran.Load())
	}
	if st := r.Snapshot()["leased_job"]; st.Runs != 1 || st.Failures != 0 || st.LastOK.IsZero() {
		t.Fatalf("unexpected stats after failover: %+v", st)
	}
}

func TestRunnerRecordsFailuresAndShutsDownGracefully(t *testing.T) {
	locker := &memLocker{}
	job := Job{
		Name:     "failing_job",
		LockKey:  202,
		Interval: 20 * time.Millisecond,
		Run:      func(context.Context) error { return errors.New("upstream down") },
	}
	r := NewRunner(locker, nil, time.Now, job)
	ctx, cancel := context.WithTimeout(context.Background(), 55*time.Millisecond)
	defer cancel()
	r.Start(ctx)
	st := r.Snapshot()["failing_job"]
	if st.Runs < 1 || st.Failures != st.Runs || st.LastError != "upstream down" {
		t.Fatalf("unexpected failure stats: %+v", st)
	}
}
