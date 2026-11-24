package activities

import (
	"errors"
	"testing"
)

// accountability_action: one declared total, split by what each advance
// disbursed, Python's round (half to even), the remainder to the last.
func TestTheDeclaredSpendIsSplitByWhatEachAdvanceDisbursed(t *testing.T) {
	tests := []struct {
		name            string
		spent, returned int64
		shares          []int64
		want            [][2]int64
	}{
		{"one", 50000, 0, []int64{50000}, [][2]int64{{50000, 0}}},
		{"two even", 30000, 0, []int64{20000, 10000}, [][2]int64{{20000, 0}, {10000, 0}}},
		{"under-spend", 27000, 3000, []int64{20000, 10000}, [][2]int64{{18000, 2000}, {9000, 1000}}},
		// 5 * 1/2 = 2.5 rounds to 2 (half to even); the last takes 3.
		{"half to even", 5, 1, []int64{1, 1}, [][2]int64{{2, 0}, {3, 1}}},
		{"three", 100, 0, []int64{1, 1, 1}, [][2]int64{{33, 0}, {33, 0}, {34, 0}}},
		{"nothing disbursed", 900, 0, []int64{0, 0}, [][2]int64{{900, 0}, {0, 0}}},
	}
	for _, tt := range tests {
		got := allocateAccountability(tt.spent, tt.returned, tt.shares)
		if len(got) != len(tt.want) {
			t.Fatalf("%s: got %v", tt.name, got)
		}
		for i := range got {
			if got[i] != tt.want[i] {
				t.Fatalf("%s: got %v, want %v", tt.name, got, tt.want)
			}
		}
	}
}

// An empty spend is the whole advance spent; an empty return is none.
func TestAnEmptySpendIsTheWholeAdvance(t *testing.T) {
	spent, returned, err := accountabilityAmounts("", "", 42000)
	if err != nil || spent != 42000 || returned != 0 {
		t.Fatalf("got %d %d %v", spent, returned, err)
	}
	spent, returned, err = accountabilityAmounts(" 40000 ", "2000", 42000)
	if err != nil || spent != 40000 || returned != 2000 {
		t.Fatalf("got %d %d %v", spent, returned, err)
	}
	for _, bad := range [][2]string{{"12.5", ""}, {"abc", ""}, {"", "x"}} {
		_, _, err := accountabilityAmounts(bad[0], bad[1], 1)
		var r *Refusal
		if !errors.As(err, &r) || r.Message != "Amounts must be whole UGX numbers." {
			t.Fatalf("%v: %v", bad, err)
		}
	}
}

// submit_accountability's refusals, word for word.
func TestAccountabilityRefusalsAreTheExistingWords(t *testing.T) {
	tests := []struct {
		answer string
		spent  int64
		want   string
	}{
		{"gone", 0, "Advance request not found."},
		{"not_disbursed", 0, "Accountability applies to a disbursed advance."},
		{"not_owner", 0, "Only the responsible user can submit accountability."},
		{"unreceipted", 0, "Confirm receipt of the disbursed funds first — accountability opens once you have confirmed the money actually arrived."},
		{"no_netsuite", 0, "NetSuite Code is required — accountability is incomplete without proof the expense was entered into NetSuite."},
		{"negative", 0, "Amount spent and amount returned must not be negative."},
		{"netsuite_used", 0, "This NetSuite Code already clears another advance. A NetSuite Code clears at most one advance, so each advance needs its own."},
		{"returned_on_overspend", 0, "Amount returned must be zero unless actual spend is less than the disbursed amount."},
		{"variance:2500", 47500, "Actual spend (UGX 47,500) is UGX 2,500 less than the disbursed amount — enter the returned amount or a variance explanation."},
	}
	for _, tt := range tests {
		err := accountabilityRefusal(tt.answer, tt.spent)
		var r *Refusal
		if !errors.As(err, &r) || r.Message != tt.want {
			t.Fatalf("%s: got %v\nwant %q", tt.answer, err, tt.want)
		}
	}
	if accountabilityRefusal("ok", 1) != nil {
		t.Fatal("ok is no refusal")
	}
}

// _notify's body for the Programme Lead.
func TestTheLeadIsToldWhatWasAccountedFor(t *testing.T) {
	got := accountedBody("Grace A.", 47500, "EXP-2026-00889")
	want := "Grace A. accounted for UGX 47,500 (EXP-2026-00889). Confirm the money is accounted for so the Accountant can settle it."
	if got != want {
		t.Fatalf("got %q", got)
	}
}
