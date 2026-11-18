package schoolprofile

import "testing"

func TestTheDistrictSearchEscapesLikeWildcardsAsDjangoDoes(t *testing.T) {
	cases := map[string]string{
		"ka":   "%ka%",
		"%":    `%\%%`,
		"_a":   `%\_a%`,
		`a\b`:  `%a\\b%`,
		"Kam ": "%Kam %",
	}
	for in, want := range cases {
		if got := likeContains(in); got != want {
			t.Errorf("likeContains(%q) = %q, want %q", in, got, want)
		}
	}
}
