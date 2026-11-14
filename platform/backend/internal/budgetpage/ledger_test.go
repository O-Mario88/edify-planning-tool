package budgetpage

import (
	"reflect"
	"testing"
	"time"
)

func TestThePeriodsAreTheExistingPagesHorizons(t *testing.T) {
	p := periods(2026, date(2026, time.April, 10))
	want := map[string]string{
		"week":    "Week of 06 Apr – 12 Apr 2026",
		"month":   "April 2026",
		"quarter": "Q3 FY 2026 · 01 Apr – 30 Jun 2026",
		"fy":      "FY 2026 · 01 Oct 2025 – 30 Sep 2026",
	}
	for key, title := range want {
		if p[key].title != title {
			t.Errorf("%s: %q, want %q", key, p[key].title, title)
		}
	}
	if q := periods(2027, date(2026, time.October, 2))["quarter"]; q.start != date(2026, time.October, 1) || q.end != date(2026, time.December, 31) {
		t.Errorf("Q1 runs %v to %v", q.start, q.end)
	}
}

func TestAMonthOnlyLineJoinsOnlyTheMonthsWhollyInside(t *testing.T) {
	if got := wholeMonths(date(2026, time.April, 1), date(2026, time.June, 30)); !reflect.DeepEqual(got, []int{4, 5, 6}) {
		t.Errorf("quarter months %v", got)
	}
	if got := wholeMonths(date(2026, time.April, 6), date(2026, time.April, 12)); len(got) != 0 {
		t.Errorf("a week holds months %v", got)
	}
}

func TestASnapshotSetsOnlyTheRatesItHolds(t *testing.T) {
	got, err := snapshotRates([]byte(`{"lunch_per_day": "15000", "primary_transport_per_day": 60000.0, "secondary_breakfast_per_day": 0, "x": ""}`))
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]int64{"lunch_per_day": 15000, "primary_transport_per_day": 60000}; !reflect.DeepEqual(got, want) {
		t.Errorf("rates %v, want %v", got, want)
	}
	if _, err := snapshotRates([]byte(`{"lunch_per_day": "15000.5"}`)); err == nil {
		t.Error("a rate int() refuses was read")
	}
}

func TestTheLedgerGroupsByActivityAndRowsByItemAndRate(t *testing.T) {
	d := date(2026, time.April, 15)
	lines := []line{
		{activityID: "a1", label: "Lunch", settingKey: "lunch_per_day", amount: 6000, unitCost: 12000, plannedDate: &d,
			activityType: "cluster_training", expected: 20, batchID: "b1"},
		{activityID: "a2", label: "", settingKey: "group_training_venue_cost", amount: 40000, unitCost: 40000,
			plannedDate: &d, activityType: "school_visit", deliveryType: "partner"},
		{activityID: "a3", label: "Partner training", settingKey: "partner_training_lump_sum", amount: 90000,
			unitCost: 90000, plannedDate: &d, activityType: "training", programmeType: "admin"},
	}
	gs := groups(lines, map[string]map[string]int64{"b1": {"lunch_per_day": 15000}})
	if len(gs) != 3 || gs[0].label != "Admin" || gs[0].kind != "admin" || gs[0].rows[0].item != "Facilitation fee" {
		t.Fatalf("groups %+v", gs[0])
	}
	if gs[1].rows[0].item != "Group Training Venue Cost" || gs[1].vendorTotal != 40000 || gs[1].staffTotal != 0 {
		t.Fatalf("the partner visit %+v", gs[1].rows[0])
	}
	if r := gs[2].rows[0]; r.rate != 15000 || r.people["a1"] != 20 {
		t.Fatalf("the training's lunch %+v", r)
	}
}

func TestAnEmptyLedgerSaysSo(t *testing.T) {
	v := view{a: ask{fy: 2026, anchor: date(2026, time.April, 10), period: "month", budgetScope: "my",
		selected: periods(2026, date(2026, time.April, 10))["month"]}, now: date(2026, time.November, 14)}
	blocks := v.blocks()
	last := blocks[len(blocks)-1].GetPanel()
	if last.GetTitle() != "Activity cost plan" || len(last.GetItems()) != 1 {
		t.Fatalf("last block %v", last)
	}
}
