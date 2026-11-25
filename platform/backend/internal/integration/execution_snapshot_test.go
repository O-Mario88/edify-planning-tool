//go:build integration

package integration

import (
	"context"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/scheduler"
)

// The execution period close is Go's: on 1 October the last week, September,
// the year's last quarter and the year are locked for each country a
// Director or Impact Assessment officer reads, through the read role and the
// owned function, once; the same day again locks nothing more.
func TestExecutionPeriodSnapshotsAreLockedOnce(t *testing.T) {
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM execution_period_snapshot`); err != nil {
			t.Errorf("clearing the snapshots: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	countries, err := planningmonitor.SnapshotCountries(ctx, gateway)
	if err != nil || len(countries) == 0 {
		t.Fatalf("the countries: %v %v", countries, err)
	}
	day := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)
	want := len(countries) * len(planningmonitor.DueSnapshotWindows(day))
	locked, err := scheduler.LockExecutionSnapshotsFor(ctx, gateway, day, time.Now())
	if err != nil || locked != want {
		t.Fatalf("the close: locked %d (want %d), %v", locked, want, err)
	}
	var rows int
	var policy string
	if err := admin.QueryRow(ctx, `SELECT count(*), min(stage_policy) FROM execution_period_snapshot WHERE kind = 'original' AND version = 1`).
		Scan(&rows, &policy); err != nil || rows != want || policy == "" {
		t.Fatalf("rows %d policy %q: %v", rows, policy, err)
	}
	if again, err := scheduler.LockExecutionSnapshotsFor(ctx, gateway, day, time.Now()); err != nil || again != 0 {
		t.Fatalf("the same day again: locked %d, %v", again, err)
	}
}
