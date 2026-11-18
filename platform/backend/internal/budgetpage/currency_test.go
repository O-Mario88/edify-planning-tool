package budgetpage

import "testing"

// Money is shown in the request's country's currency (docs/migration/80,
// §18); Uganda's stays UGX exactly as the existing page writes it.
func TestMoneyInTheCountrysCurrency(t *testing.T) {
	for _, c := range []struct{ got, want string }{
		{ugx(24000), "UGX 24,000"},
		{inCurrency("KES", -1234567), "KES -1,234,567"},
		{ugxCompact(1_200_000), "UGX 1.2M"},
		{compactIn("RWF", 850_000), "RWF 850K"},
		{compactIn("ETB", 640), "ETB 640"},
		{view{}.amount(5), "UGX 5"},
		{view{currency: "KES"}.amountCompact(2_500_000_000), "KES 2.5B"},
	} {
		if c.got != c.want {
			t.Errorf("got %q, want %q", c.got, c.want)
		}
	}
}
