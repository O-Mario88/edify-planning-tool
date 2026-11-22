package scheduler

import (
	"context"
	"testing"
	"time"
)

func TestUgandaCutoverCatalogCoversAll41JobsWithUniqueLocks(t *testing.T) {
	if got := len(UgandaCutoverJobs); got != 41 {
		t.Fatalf("UgandaCutoverJobs count = %d, want 41", got)
	}
	seenNames := map[string]bool{}
	seenLocks := map[int64]bool{}
	for _, j := range UgandaCutoverJobs {
		if j.Name == "" || j.LockKey <= 0 || j.Interval <= 0 {
			t.Fatalf("invalid job metadata: %+v", j)
		}
		if seenNames[j.Name] {
			t.Fatalf("duplicate job name: %s", j.Name)
		}
		seenNames[j.Name] = true
		if seenLocks[j.LockKey] {
			t.Fatalf("duplicate lock key %d on %s", j.LockKey, j.Name)
		}
		seenLocks[j.LockKey] = true
	}

	// Execute all 41 jobs once under a fake locker to prove zero overlap & clean stats.
	locker := &memLocker{}
	jobs := BuildUgandaJobs(nil)
	runner := NewRunner(locker, nil, time.Now, jobs...)
	for _, j := range jobs {
		if err := runner.RunOnce(context.Background(), j); err != nil {
			t.Fatalf("job %s failed: %v", j.Name, err)
		}
	}
	stats := runner.Snapshot()
	if len(stats) != 41 {
		t.Fatalf("stats count = %d, want 41", len(stats))
	}
	for name, st := range stats {
		if st.Runs != 1 || st.Failures != 0 {
			t.Fatalf("job %s unexpected stats: %+v", name, st)
		}
	}
}

func TestKampalaFYRolloverBoundary(t *testing.T) {
	// 30 Sep 2026 20:59 UTC = 30 Sep 2026 23:59 EAT -> FY 2026
	before, err := KampalaOperationalFY(time.Date(2026, time.September, 30, 20, 59, 0, 0, time.UTC))
	if err != nil || before != 2026 {
		t.Fatalf("before rollover: fy=%d err=%v, want 2026", before, err)
	}
	// 30 Sep 2026 21:00 UTC = 1 Oct 2026 00:00 EAT -> FY 2027
	after, err := KampalaOperationalFY(time.Date(2026, time.September, 30, 21, 0, 0, 0, time.UTC))
	if err != nil || after != 2027 {
		t.Fatalf("after rollover: fy=%d err=%v, want 2027", after, err)
	}
}
