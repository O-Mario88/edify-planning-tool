package pyhash

import (
	"strings"
	"testing"
)

// Each expected digest is Python's hashlib.blake2s(s.encode(), digest_size=n).hexdigest().
func TestBlake2sIsPythonsHashlib(t *testing.T) {
	cases := []struct {
		in   string
		size int
		want string
	}{
		{"cmw9p77fk00hcskekheei", 8, "1e52da3fece01574"},
		{"cmw9p77fk00hcskekheei", 7, "b5ae6cb2e2e353"},
		{"a", 8, "3746ba2ac42c6821"},
		{"a", 7, "b6bfc0818250fb"},
		{"", 8, "ef2a8b78dd80da9c"},
		{"", 7, "de1931c0881609"},
		// RFC 7693 Appendix B: BLAKE2s-256("abc").
		{"abc", 32, "508c5e8c327c14e2e1a72ba34eeb452f37458b209ed63a294d999b4c86675982"},
		// Longer than one block.
		{strings.Repeat("x", 130), 32, "8f489717e52fa50061294fd571775eaa6fce9e9a77b4b9450eec18c362d2dcd2"},
		// Exactly one block.
		{strings.Repeat("y", 64), 8, "d16fec0049f5853d"},
	}
	for _, c := range cases {
		got := Blake2sHex([]byte(c.in), c.size)
		if c.want != "" && got != c.want {
			t.Errorf("Blake2sHex(%q, %d) = %s, want %s", c.in, c.size, got, c.want)
		}
		if len(got) != 2*c.size {
			t.Errorf("Blake2sHex(%q, %d) is %d hex digits", c.in, c.size, len(got))
		}
	}
}
