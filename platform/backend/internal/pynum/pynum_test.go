package pynum

import "testing"

func TestIntReadsAsPythonReads(t *testing.T) {
	for _, c := range []struct {
		text string
		n    int
		ok   bool
	}{
		{"2", 2, true}, {" 2 ", 2, true}, {"+2", 2, true}, {"-4", -4, true}, {"1_0", 10, true},
		{"", 0, false}, {"x", 0, false}, {"_1", 0, false}, {"1__0", 0, false}, {"+-1", 0, false}, {"2.0", 0, false},
	} {
		if n, ok := Int(c.text); n != c.n || ok != c.ok {
			t.Errorf("Int(%q) = %d, %v; want %d, %v", c.text, n, ok, c.n, c.ok)
		}
	}
}
