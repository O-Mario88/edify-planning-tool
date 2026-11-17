package targets

import (
	"testing"
	"time"
)

// The rebuild worked out in memory follows TargetAchievementService._rebuild
// row by row: a verified visit with its Activity SF ID credits, one without
// it waits, a returned one reverses, scheduled work is no achievement, a
// source moved from another year moves its row (keeping its area), a source
// that left the workflow is reversed in this year only, and an area that is
// not active credits nothing.
func TestTheRebuildWorksOutEachRowAsTheExistingOneWrites(t *testing.T) {
	const fy = "2027"
	day := func(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }
	p := Person{UserID: "u1", StaffID: "s1"}
	active := map[string]bool{"school_visits": true, "ssa_completed": true, "mscs": true}
	src := sources{
		activities: map[string][]activityRow{
			"s1": {
				{id: "v1", kind: "school_visit", status: "ia_verified", salesforceID: " SVE-1 ", day: day(2026, 10, 5)},
				{id: "v2", kind: "school_visit", status: "ia_verified", salesforceID: "  ", day: day(2026, 11, 5)},
				{id: "v3", kind: "school_visit", status: "returned_by_ia", day: day(2026, 11, 6)},
				{id: "v4", kind: "school_visit", status: "scheduled", day: day(2026, 11, 7)},
				{id: "v5", kind: "school_visit", status: "closed", salesforceID: "SVE-5", day: day(2026, 12, 1)},
			},
			"u1": {{id: "c1", kind: "cluster_meeting", status: "ia_verified", salesforceID: "SVE-9", day: day(2026, 10, 9)}},
		},
		ssa:  map[string][]dayRow{"u1": {{id: "r1", status: "confirmed", day: day(2027, 1, 2)}}},
		mscs: map[string][]dayRow{"u1": {{id: "m1", status: "archived", day: day(2026, 10, 3)}, {id: "m2", status: "approved", day: day(2025, 1, 1)}}},
		ledger: map[string]map[sourceKey]ledgerRow{"u1": {
			// Credited last year, now dated this year: moved, area kept.
			{"activity", "v5"}: {fy: "2026", area: "legacy_area", status: validated, day: day(2026, 9, 30), month: 12, quantity: 2},
			// Gone from the workflow: reversed in this year…
			{"activity", "gone"}: {fy: fy, area: "school_visits", status: validated, day: day(2026, 10, 1), month: 1, quantity: 1},
			// …but another year's row is left alone.
			{"activity", "old"}: {fy: "2026", area: "school_visits", status: validated, day: day(2026, 1, 1), month: 4, quantity: 1},
			// Unchanged: kept as stored.
			{"activity", "v1"}: {fy: fy, area: "school_visits", status: validated, day: day(2026, 10, 5), month: 1, quantity: 3},
		}},
	}
	rows, err := rebuilt(p, fy, active, src)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]ledgerRow{}
	for _, r := range rows {
		got[r.area+"/"+r.status+"/"+r.fy+"/"+r.day.Format(time.DateOnly)] = r
	}
	want := map[string]int{ // row → quantity
		"school_visits/validated/2027/2026-10-05":   3, // v1 as stored
		"school_visits/provisional/2027/2026-11-05": 1, // v2: no Activity SF ID
		"school_visits/reversed/2027/2026-11-06":    1, // v3: returned
		"legacy_area/validated/2027/2026-12-01":     2, // v5 moved into the year
		"school_visits/reversed/2027/2026-10-01":    1, // gone
		"school_visits/validated/2026/2026-01-01":   1, // old, untouched
		"ssa_completed/validated/2027/2027-01-02":   1, // r1
		"mscs/reversed/2027/2026-10-03":             1, // m1 archived
	}
	for key, quantity := range want {
		r, ok := got[key]
		if !ok {
			t.Errorf("missing %s", key)
			continue
		}
		if r.quantity != quantity {
			t.Errorf("%s: quantity %d, want %d", key, r.quantity, quantity)
		}
	}
	if len(rows) != len(want) {
		t.Errorf("%d rows, want %d (the scheduled visit, the inactive area's meeting and last year's story credit nothing): %v",
			len(rows), len(want), got)
	}
	if r := got["legacy_area/validated/2027/2026-12-01"]; r.month != 3 {
		t.Errorf("the moved row is credited to month %d, want 3", r.month)
	}
}
