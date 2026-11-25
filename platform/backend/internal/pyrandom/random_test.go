package pyrandom

import (
	_ "embed"
	"encoding/json"
	"slices"
	"testing"
)

//go:embed cases_test.json
var casesJSON []byte

// The cases are CPython's own: random.Random(seed).sample(range(n), k) and
// getrandbits(32), printed by the existing application's interpreter.
func TestSampleIsCPythons(t *testing.T) {
	var cases []struct {
		Seed string   `json:"seed"`
		N    int      `json:"n"`
		K    int      `json:"k"`
		Pick []int    `json:"pick"`
		Bits []uint32 `json:"bits"`
	}
	if err := json.Unmarshal(casesJSON, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		r := New(c.Seed)
		if c.Bits != nil {
			for j, want := range c.Bits {
				if got := r.GetRandBits32(); got != want {
					t.Errorf("seed %q word %d: got %d, want %d", c.Seed, j, got, want)
				}
			}
			continue
		}
		if got := r.Sample(c.N, c.K); !slices.Equal(got, c.Pick) {
			t.Errorf("seed %q sample(%d, %d): got %v, want %v", c.Seed, c.N, c.K, got, c.Pick)
		}
	}
}
