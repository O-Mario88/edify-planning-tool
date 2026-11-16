package pydecimal

import "testing"

// Each case is what Python 3 prints for the operation, format(r, "f").
var cases = [][4]string{
	{"div", "0", "20.00", "0"},
	{"div", "1", "20.00", "0.05"},
	{"div", "1600.0000", "20.00", "80.00"},
	{"div", "2", "3", "0.6666666666666666666666666667"},
	{"div", "10", "4", "2.5"},
	{"div", "1", "3.00", "0.3333333333333333333333333333"},
	{"div", "100.00", "7", "14.28571428571428571428571429"},
	{"div", "2.50", "0.5", "5.0"},
	{"div", "5.00", "80.00", "0.0625"},
	{"div", "1", "1024", "0.0009765625"},
	{"mul", "0E+2", "100", "0"},
	{"mul", "0.05", "100", "5.00"},
	{"mul", "25.00", "80.00", "2000.0000"},
	{"add", "0", "1.00", "1.00"},
	{"add", "3.00", "2", "5.00"},
	{"sub", "5.00", "0", "5.00"},
	{"sub", "12.00", "2", "10.00"},
	{"q2", "20.0000", "", "20.00"},
	{"q2", "0.125", "", "0.12"},
	{"q2", "0.135", "", "0.14"},
	{"q2", "2", "", "2.00"},
	{"q2", "-0.125", "", "-0.12"},
}

func TestDecimalArithmeticPrintsAsPython(t *testing.T) {
	for _, c := range cases {
		a := MustParse(c[1])
		var got Decimal
		switch c[0] {
		case "div":
			got = a.Div(MustParse(c[2]))
		case "mul":
			got = a.Mul(MustParse(c[2]))
		case "add":
			got = a.Add(MustParse(c[2]))
		case "sub":
			got = a.Sub(MustParse(c[2]))
		case "q2":
			got = a.Quantize(-2)
		}
		if got.String() != c[3] {
			t.Errorf("%s %s %s = %s, Python prints %s", c[0], c[1], c[2], got, c[3])
		}
	}
}

func TestMaxAndMinKeepTheFirstOfEqualValues(t *testing.T) {
	if got := Max(Zero(), MustParse("0.00")); got.String() != "0" {
		t.Errorf("max(Decimal(0), Decimal(\"0.00\")) = %s, Python gives 0", got)
	}
	if got := Min(MustParse("100.00"), Int(100)); got.String() != "100.00" {
		t.Errorf("min = %s", got)
	}
}
