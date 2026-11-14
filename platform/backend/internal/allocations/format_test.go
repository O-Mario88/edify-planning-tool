package allocations

import (
	"math/big"
	"strings"
	"testing"
)

func TestNumbersReadAsTheTemplateWritesThem(t *testing.T) {
	r := func(s string) *big.Rat { v, _ := new(big.Rat).SetString(s); return v }
	for _, c := range []struct {
		v      string
		places int
		want   string
	}{{"34", -2, "34"}, {"34.5", -2, "34.50"}, {"34.005", -2, "34.01"}, {"34.004", -2, "34.00"}, {"0.5", 0, "1"}, {"2.5", 0, "3"}, {"-1.5", 0, "-2"}} {
		if got := FloatFormat(r(c.v), c.places); got != c.want {
			t.Errorf("%s|floatformat:%d = %q, want %q", c.v, c.places, got, c.want)
		}
	}
	if Repr(100) != "100.0" || Repr(85.5) != "85.5" || Repr(12.34) != "12.34" {
		t.Errorf("%s %s %s", Repr(100), Repr(85.5), Repr(12.34))
	}
	if round(2.675, 2) != 2.67 || round(0.125, 2) != 0.12 {
		t.Error("round reads the binary value as Python does")
	}
}

func TestTheContractListsMilestonesInThePlansOrder(t *testing.T) {
	allocs := []allocation{
		{id: "a5", milestoneID: "m9", sequence: 2, sourceOrder: 1},
		{id: "a4", milestoneID: "m3", sequence: 1, sourceOrder: 3},
		{id: "a2", milestoneID: "m2", sequence: 1, sourceOrder: 1, code: "B"},
		{id: "a1", milestoneID: "m1", sequence: 1, sourceOrder: 1, code: "A"},
		{id: "a3", milestoneID: "m1", sequence: 1, sourceOrder: 1, code: "A"},
	}
	inPlanOrder(allocs)
	got := []string{}
	for _, a := range allocs {
		got = append(got, a.id)
	}
	if want := "a1 a3 a2 a4 a5"; strings.Join(got, " ") != want {
		t.Errorf("%v, want %s", got, want)
	}
}
