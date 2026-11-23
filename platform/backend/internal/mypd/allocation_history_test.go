package mypd

import (
	"reflect"
	"testing"
)

func TestHistoryYears(t *testing.T) {
	allocations := map[string]historyAllocation{
		"2026": {annual: 50_000, currency: "UGX"},
		"2027": {annual: 100_000, currency: "USD"},
	}
	requests := []historyRequest{
		{fy: "2027", status: "disbursed", requested: 30_000},
		{fy: "2027", status: "draft", requested: 90_000},            // not committed
		{fy: "2027", status: "completed_closed", accounted: 25_000}, // accounted whatever its status
		{fy: "2026", status: "disbursed", requested: 70_000},        // more than the allocation
		{fy: "2025", status: "disbursed", requested: 1_000},         // a year with no allocation row
	}
	want := []HistoryYear{
		{FY: "2027", Allocation: "USD 1,000", Committed: "USD 300", Accounted: "USD 250", Remaining: "USD 450"},
		{FY: "2026", Allocation: "UGX 500", Committed: "UGX 700", Accounted: "UGX 0", Remaining: "UGX 0"},
		{FY: "2025", Allocation: "USD 0", Committed: "USD 10", Accounted: "USD 0", Remaining: "USD 0"},
	}
	if got := historyYears(allocations, requests); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v\nwant %+v", got, want)
	}
}

func TestHistoryYearsWithNothingIsEmpty(t *testing.T) {
	if got := historyYears(nil, nil); len(got) != 0 {
		t.Fatalf("got %+v", got)
	}
}
