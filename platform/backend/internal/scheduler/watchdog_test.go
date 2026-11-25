package scheduler

import (
	"testing"
	"time"
)

func TestHealthOfFollowsJobHealth(t *testing.T) {
	now := time.Date(2026, 11, 25, 6, 0, 0, 0, time.UTC)
	job := registryJob{name: "daily_digest", maxInterval: 30 * time.Hour}
	str := func(s string) *string { return &s }
	at := func(d time.Duration) *time.Time { v := now.Add(d); return &v }
	cases := []struct {
		name                 string
		status, errMsg       *string
		success, due         *time.Time
		wantStatus, severity string
		wantErr              string
	}{
		{"never run, not due yet", nil, nil, nil, at(time.Hour), "scheduled", "ok", ""},
		{"never run and due", nil, nil, nil, at(-time.Hour), "never_run", "critical", ""},
		{"never run, scheduler never started", nil, nil, nil, nil, "never_run", "critical", ""},
		{"failed last time", str("failed"), str("ValueError: boom"), at(-time.Hour), nil, "failed", "critical", "ValueError: boom"},
		{"late", str("success"), nil, at(-31 * time.Hour), nil, "overdue", "high", ""},
		{"running but late", str("running"), nil, at(-31 * time.Hour), nil, "overdue", "high", ""},
		{"healthy", str("success"), nil, at(-time.Hour), nil, "healthy", "ok", ""},
		{"ran, never succeeded, not failed", str("running"), nil, nil, nil, "healthy", "ok", ""},
	}
	for _, c := range cases {
		h := healthOf(job, c.status, c.errMsg, c.success, 2, c.due, now)
		if h.status != c.wantStatus || h.severity != c.severity || h.lastError != c.wantErr {
			t.Errorf("%s: got %s/%s %q, want %s/%s %q", c.name, h.status, h.severity, h.lastError, c.wantStatus, c.severity, c.wantErr)
		}
	}
}

func TestWatchdogNoticeReadsLikeDjangos(t *testing.T) {
	last := time.Date(2026, 11, 25, 2, 12, 0, 5000, time.UTC)
	n := watchdogNotice("daily_digest", jobHealth{status: "never_run", severity: "critical", failures: 0})
	if n.Title != "Background job daily_digest is never_run" || n.Priority != "high" ||
		n.Body != "Never run. Last successful run: never. 0 recorded failure(s)." {
		t.Fatalf("never-run notice: %+v", n)
	}
	n = watchdogNotice("daily_digest", jobHealth{status: "overdue", severity: "high", failures: 3, lastSuccess: &last})
	if n.Priority != "normal" || n.Body != "Overdue. Last successful run: 2026-11-25 02:12:00.000005+00:00. 3 recorded failure(s)." {
		t.Fatalf("overdue notice: %+v", n)
	}
	whole := time.Date(2026, 11, 25, 2, 12, 0, 0, time.UTC)
	if got := pyDatetime(whole); got != "2026-11-25 02:12:00+00:00" {
		t.Fatalf("pyDatetime = %q", got)
	}
}

func TestRegistryJobsKeepTheRegistryOrder(t *testing.T) {
	jobs, err := registryJobs()
	if err != nil {
		t.Fatal(err)
	}
	if len(jobs) != len(UgandaCutoverJobs) || jobs[0].name != "weekly_fund_request" || jobs[0].maxInterval != 11520*time.Minute {
		t.Fatalf("registry: %d jobs, first %+v", len(jobs), jobs[0])
	}
}
