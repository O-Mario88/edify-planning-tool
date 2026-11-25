package planningoversight

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
)

// _period_days: a year runs October to September (to the horizon's last
// year when several are read), a month in October..December falls in the
// year before the FY, a quarter is three months from October.
func TestPeriodDaysReadTheYearAsCoverageDoes(t *testing.T) {
	cases := []struct {
		name       string
		per        partneroversight.Period
		years      []string
		start, end string
	}{
		{"the year", partneroversight.Period{FY: "2026", Kind: "fy"}, []string{"2026"}, "2025-10-01", "2026-09-30"},
		{"the horizon", partneroversight.Period{FY: "2026", Kind: "fy"}, []string{"2026", "2027", "2028"}, "2025-10-01", "2028-09-30"},
		{"October", partneroversight.Period{FY: "2026", Kind: "month", Month: 10}, []string{"2026"}, "2025-10-01", "2025-10-31"},
		{"March", partneroversight.Period{FY: "2026", Kind: "month", Month: 3}, []string{"2026"}, "2026-03-01", "2026-03-31"},
		{"February in a leap year", partneroversight.Period{FY: "2028", Kind: "month", Month: 2}, []string{"2028"}, "2028-02-01", "2028-02-29"},
		{"Q1", partneroversight.Period{FY: "2026", Kind: "quarter", Quarter: "Q1"}, []string{"2026"}, "2025-10-01", "2025-12-31"},
		{"Q4", partneroversight.Period{FY: "2026", Kind: "quarter", Quarter: "Q4"}, []string{"2026"}, "2026-07-01", "2026-09-30"},
	}
	for _, tc := range cases {
		start, end := periodDays(tc.per, tc.years)
		if got := start.Format("2006-01-02"); got != tc.start {
			t.Errorf("%s: starts %s, want %s", tc.name, got, tc.start)
		}
		if got := end.Format("2006-01-02"); got != tc.end {
			t.Errorf("%s: ends %s, want %s", tc.name, got, tc.end)
		}
	}
}

// CoverageGroup.page_param: anything not a letter or digit becomes an
// underscore, trimmed; an empty key is "group".
func TestCoverageGroupPageParam(t *testing.T) {
	for key, want := range map[string]string{
		"2026-11":   "planned_2026_11_page",
		"Q2":        "planned_Q2_page",
		"--":        "planned_group_page",
		"not dated": "planned_not_dated_page",
	} {
		if got := (coverageGroup{key: key}).pageParam(); got != want {
			t.Errorf("%q: %q, want %q", key, got, want)
		}
	}
}

// The planned row names who delivers it, the finance state after the
// budget, and opens the activity drawer only for a dated activity.
func TestCoverageRowCells(t *testing.T) {
	r := coverageRow{code: "S1", school: "Hill School", owner: "Ann", kind: "cluster_meeting",
		partner: true, partnerName: "Literacy Uganda", budget: "In weekly request", finance: "paid", activityID: "a1"}
	cells := r.cells().GetCells()
	if got := cells[6].GetText(); got != "Cluster meeting" {
		t.Errorf("category %q", got)
	}
	if got := cells[7].GetText(); got != "Not dated" {
		t.Errorf("planned date %q", got)
	}
	if got := cells[8].GetText(); got != "Partner · Literacy Uganda" {
		t.Errorf("channel %q", got)
	}
	if got := cells[1].GetHref(); got != "/schools/S1" {
		t.Errorf("school link %q", got)
	}
	if a := cells[12].GetActions(); len(a) != 1 || a[0].GetHref() != "/team-planning-oversight/detail?activity=a1" || !a[0].GetDrawer() {
		t.Errorf("action %v", a)
	}
	undated := coverageRow{school: "Hill School", kind: "school_visit"}
	cells = undated.cells().GetCells()
	if got := cells[0].GetText(); got != "—" {
		t.Errorf("no code %q", got)
	}
	if got := cells[8].GetText(); got != "Staff" {
		t.Errorf("staff channel %q", got)
	}
	if a := cells[12].GetActions(); len(a) != 0 {
		t.Errorf("an undated hand-over opens nothing, got %v", a)
	}
}

// A school outside a cluster is sent to its own page; one in a cluster to
// the cluster, to plan a session.
func TestMissingSchoolAction(t *testing.T) {
	alone := coverageSchool{code: "S1", name: "Hill"}.missingCells().GetCells()
	if got := alone[4].GetText(); got != "Not in a cluster" {
		t.Errorf("cluster %q", got)
	}
	if a := alone[7].GetActions()[0]; a.GetLabel() != "Open school" || a.GetHref() != "/schools/S1" {
		t.Errorf("action %v", a)
	}
	in := coverageSchool{code: "S1", name: "Hill", clusterID: "c1", clusterName: "Kira"}.missingCells().GetCells()
	if a := in[7].GetActions()[0]; a.GetLabel() != "Plan a cluster session" || a.GetHref() != "/clusters/c1" {
		t.Errorf("action %v", a)
	}
}

// An empty table keeps its columns and carries its message as one row.
func TestPagedTableOrEmpty(t *testing.T) {
	blocks := pagedTableOr(missingColumns, nil, nil, "untrained_page", "Every school has one.")
	tbl := blocks[0].GetTable()
	if len(blocks) != 1 || len(tbl.GetColumns()) != len(missingColumns) || tbl.GetEmptyMessage() != "Every school has one." {
		t.Fatalf("empty table %v", blocks)
	}
	if rows := tbl.GetRows(); len(rows) != 1 || rows[0].GetCells()[0].GetText() != "Every school has one." {
		t.Errorf("empty row %v", rows)
	}
}
