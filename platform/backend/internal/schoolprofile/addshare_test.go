package schoolprofile

import "testing"

// Python's own sums (math.fma gives the other answer for each).
func TestASharedScoreIsAddedAsPythonAddsIt(t *testing.T) {
	cases := []struct{ acc, mean, maximum, learners, want float64 }{
		{289.995, 20.79, 40, 10, 809.745},
		{4096.399, 34.7, 50, 50, 7566.399000000001},
		{754.605, 7.87, 40, 47, 1679.33},
	}
	for _, c := range cases {
		if got := addShare(c.acc, c.mean, c.maximum, c.learners); got != c.want {
			t.Errorf("%v + %v/%v*100*%v = %v, want %v", c.acc, c.mean, c.maximum, c.learners, got, c.want)
		}
	}
}
