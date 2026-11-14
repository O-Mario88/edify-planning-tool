package trainingsummary

import "testing"

func TestCeilingButtonsFollowWhoMaySetWhich(t *testing.T) {
	cases := []struct {
		s    summary
		want []string
	}{
		{summary{fy: "2027"}, nil},
		{summary{fy: "2027", maySet: true}, []string{"/training-ceilings/set?fy=2027"}},
		{summary{fy: "2026", maySetCountry: true}, []string{"/training-ceilings/country/set?fy=2026"}},
		{summary{fy: "2027", maySet: true, maySetCountry: true}, []string{"/training-ceilings/set?fy=2027", "/training-ceilings/country/set?fy=2027"}},
	}
	for _, c := range cases {
		got := ceilingButtons(c.s)
		if len(got) != len(c.want) {
			t.Fatalf("%+v: %v", c.s, got)
		}
		for i, a := range got {
			if a.GetHref() != c.want[i] || !a.GetPrimary() || !a.GetDrawer() {
				t.Errorf("%+v: %v, want %q", c.s, a, c.want[i])
			}
		}
	}
}
