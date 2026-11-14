package allocations

import (
	"math/big"
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
