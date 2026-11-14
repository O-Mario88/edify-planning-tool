package btpages

import "testing"

func TestThePortfolioPagerFollowsDjango(t *testing.T) {
	cases := []struct {
		raw           string
		total, size   int
		number, pages int
	}{{"", 4, 50, 1, 1}, {"9", 120, 50, 3, 3}, {"0", 120, 50, 3, 3}, {"x", 120, 50, 1, 3}, {"2", 120, 50, 2, 3}}
	for _, c := range cases {
		if n, p := djangoPage(c.raw, c.total, c.size); n != c.number || p != c.pages {
			t.Errorf("djangoPage(%q, %d) = %d of %d", c.raw, c.total, n, p)
		}
	}
}

func TestScoresAreWrittenAsTheTemplateWritesThem(t *testing.T) {
	if signed(0) != "+0" || signed(1.5) != "+1.5" || signed(-2.6) != "-2.6" {
		t.Errorf("signed: %q %q %q", signed(0), signed(1.5), signed(-2.6))
	}
	if floatformatOne(7) != "7" || floatformatOne(5.4) != "5.4" || floatformatOne(7.04) != "7" {
		t.Errorf("floatformat: %q %q %q", floatformatOne(7), floatformatOne(5.4), floatformatOne(7.04))
	}
	if !kindOf(FinancePath).finance || kindOf(GovernmentPath).finance || kindOf(GovernmentPath).intervention != "government_requirement" {
		t.Error("kinds")
	}
}
