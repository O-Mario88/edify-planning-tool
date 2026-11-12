package myplan

import (
	"encoding/json"
	"testing"
	"time"
)

func ptr[T any](v T) *T { return &v }

func line(t *testing.T, raw string) map[string]any {
	t.Helper()
	v, err := decode([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	return v.(map[string]any)
}

// costing_service.minimum_share at its edges: Decimal's half up, a shared
// day's share, a retired rate, a missing rate, a component Go leaves to
// the existing code (a float, an allocation it would fail on).
func TestAComponentIsRepricedAsTheExistingCodeRepricesIt(t *testing.T) {
	rate := setting{approvedMinimum: ptr(int64(45000)), unitCost: 50000}
	for _, tc := range []struct {
		name, line string
		s          setting
		found      bool
		want       *int64
		ok         bool
	}{
		{"pro rata", `{"key":"k","unit":50000,"amount":50000}`, rate, true, ptr(int64(45000)), true},
		{"half up", `{"key":"k","unit":4,"amount":1}`, setting{approvedMinimum: ptr(int64(2))}, true, ptr(int64(1)), true},
		{"below half", `{"key":"k","unit":3,"amount":1}`, setting{approvedMinimum: ptr(int64(1))}, true, ptr(int64(0)), true},
		{"shared day", `{"key":"k","unit":25000,"amount":25000,"label":"Transport (shared, 2 schools)"}`, rate, true, ptr(int64(22500)), true},
		{"allocated", `{"key":"k","unit":1,"amount":1,"dailyAllocation":{"count":4,"index":1}}`, setting{approvedMinimum: ptr(int64(10))}, true, ptr(int64(3)), true},
		{"allocated last", `{"key":"k","unit":1,"amount":1,"dailyAllocation":{"count":4,"index":3}}`, setting{approvedMinimum: ptr(int64(10))}, true, ptr(int64(2)), true},
		{"no minimum", `{"key":"k","unit":1,"amount":1}`, setting{unitCost: 5}, true, nil, true},
		{"missing", `{"key":"k","unit":1,"amount":1,"missing":true}`, rate, true, nil, true},
		{"no unit", `{"key":"k","amount":1}`, rate, true, nil, true},
		{"zero unit, zero rate", `{"key":"k","unit":0,"amount":1}`, setting{approvedMinimum: ptr(int64(0))}, true, ptr(int64(0)), true},
		{"zero unit", `{"key":"k","unit":0,"amount":1}`, rate, true, nil, true},
		{"retired", `{"key":"breakfast","unit":9,"amount":9000}`, setting{}, false, ptr(int64(9000)), true},
		{"retired, no amount", `{"key":"breakfast","unit":9}`, setting{}, false, ptr(int64(0)), true},
		{"retired, missing", `{"key":"breakfast","unit":9,"amount":9000,"missing":true}`, setting{}, false, nil, true},
		{"unknown", `{"key":"nothing","unit":9,"amount":9000}`, setting{}, false, nil, true},
		{"float", `{"key":"k","unit":1.5,"amount":1}`, rate, true, nil, false},
		{"allocation out of range", `{"key":"k","unit":1,"amount":1,"dailyAllocation":{"count":2,"index":2}}`, rate, true, nil, false},
		{"label not text", `{"key":"k","unit":1,"amount":1,"label":null}`, rate, true, nil, false},
	} {
		got, ok := minimumShare(line(t, tc.line), tc.s, tc.found)
		if ok != tc.ok || (got == nil) != (tc.want == nil) || (got != nil && *got != *tc.want) {
			t.Errorf("%s: %v %v, want %v %v", tc.name, got, ok, tc.want, tc.ok)
		}
	}
	if !in(rules.Rows.RetiredCostSettingKeys, "breakfast") {
		t.Fatal("the retired key the cases use is no longer retired")
	}
}

func TestTruthIsPythons(t *testing.T) {
	for raw, want := range map[string]bool{`0`: false, `0.0`: false, `""`: false, `[]`: false, `{}`: false, `null`: false, `false`: false, `1`: true, `"x"`: true, `["x"]`: true, `{"a":1}`: true} {
		v, err := decode([]byte(raw))
		if err != nil {
			t.Fatal(err)
		}
		if truthy(v) != want {
			t.Errorf("%s: %v", raw, !want)
		}
	}
	if _, isNumber := json.Number("1").Int64(); isNumber != nil {
		t.Fatal("json.Number")
	}
}

// The Budget status words for every weekly request state.
func TestTheBudgetStatusReadsTheFirstLinesRequest(t *testing.T) {
	lines := costLines{"a": {"l1", "l2"}}
	for status, want := range map[string]string{
		"pending_responsible_confirmation": "In Weekly Request", "submitted_to_pl": "Awaiting PL Approval",
		"submitted_to_cd": "Awaiting CD Approval", "returned_by_pl": "Request Returned", "returned_by_cd": "Request Returned",
		"returned_by_accountant": "Request Returned", "confirmed_for_advance": "Approved", "disbursed": "Disbursed",
		"draft": "Included in Request",
	} {
		got := budgetStatus(&activity{id: "a"}, lines, map[string]*string{"l1": ptr(status), "l2": ptr("disbursed")}, nil)
		if got != want {
			t.Errorf("%s: %q, want %q", status, got, want)
		}
	}
	for _, tc := range []struct {
		a     *activity
		lines costLines
		notes map[string]string
		want  string
	}{
		{&activity{id: "a"}, lines, nil, "Budget Created"},
		{&activity{id: "a", costMissing: true}, lines, nil, "Cost Setup Required"},
		{&activity{id: "a", activityType: "in_school_training"}, nil, map[string]string{"a": "x"}, "In School Visit"},
		{&activity{id: "a", activityType: "school_visit"}, nil, map[string]string{"a": "x"}, "In Training"},
		{&activity{id: "a"}, nil, nil, "No Budget"},
	} {
		if got := budgetStatus(tc.a, tc.lines, map[string]*string{}, tc.notes); got != tc.want {
			t.Errorf("%+v: %q, want %q", tc.a, got, tc.want)
		}
	}
}

func TestTheStatusPillAndItsCompletionWords(t *testing.T) {
	today := time.Date(2026, 11, 12, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		a    activity
		want string
	}{
		{activity{status: "submitted_to_pl"}, "Activity ID Missing"},
		{activity{status: "submitted_to_pl", salesforce: ptr("SVE-1")}, "Complete"},
		{activity{status: "awaiting_owner_approval"}, "Awaiting owner approval"},
		{activity{status: "scheduled", plannedDate: ptr(today)}, "Due Today"},
		{activity{status: "scheduled", plannedDate: ptr(today.AddDate(0, 0, 7))}, "This Week"},
		{activity{status: "scheduled", plannedDate: ptr(today.AddDate(0, 0, 8))}, "Scheduled"},
		{activity{status: "scheduled", rescheduleCount: 1, plannedDate: ptr(today.AddDate(0, 0, 2))}, "Rescheduled"},
	} {
		if got := statusLabel(&tc.a, today); got != tc.want {
			t.Errorf("%+v: %q, want %q", tc.a, got, tc.want)
		}
	}
	if completionGap(true, completion{}) != "Not Complete" || completionGap(true, completion{salesforce: "x"}) != "Missing evidence" ||
		completionGap(true, completion{evidenceOK: true}) != "Missing Salesforce ID" || completionGap(false, completion{}) != "" {
		t.Error("completion gap")
	}
}

func TestTheDayMarkAndTheCells(t *testing.T) {
	for _, tc := range []struct {
		types []string
		want  string
	}{{nil, "primary"}, {[]string{"", "secondary"}, "mixed"}, {[]string{"secondary", "secondary"}, "secondary"}, {[]string{"odd"}, "primary"}} {
		if got := dayMark(tc.types); got != tc.want {
			t.Errorf("%v: %q", tc.types, got)
		}
	}
	for n, want := range map[int64]string{0: "UGX 0", 999: "UGX 999", 1000: "UGX 1,000", 1234567: "UGX 1,234,567", -4500: "UGX -4,500"} {
		if got := money(n); got != want {
			t.Errorf("%d: %q", n, got)
		}
	}
	if pyFloorDiv(7, 2) != 3 || pyFloorDiv(-7, 2) != -4 {
		t.Error("floor division")
	}
	d := time.Date(2026, 10, 5, 0, 0, 0, 0, time.UTC)
	if shownDay(&d) != "5 Oct 2026" {
		t.Error(shownDay(&d))
	}
}
