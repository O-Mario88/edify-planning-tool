package extrawork

import "testing"

func TestTheAssignLinkIsReadBackAsTheFeedReadsTheTemplatesUnencodedYear(t *testing.T) {
	cases := []struct{ fy, want string }{
		{"2027", "/extra-work/assign-drawer?fy=2027"},
		{"a&b", "/extra-work/assign-drawer?fy=a"},
		{" 2026 ", "/extra-work/assign-drawer?fy=+2026+"},
		{"", "/extra-work/assign-drawer"},
	}
	for _, c := range cases {
		if got := assignHref(c.fy); got != c.want {
			t.Errorf("assignHref(%q) = %q, want %q", c.fy, got, c.want)
		}
	}
}
