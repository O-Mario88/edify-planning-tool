package countryctx

import (
	"context"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

func TestTheCountryARequestCarries(t *testing.T) {
	kenya := &country.Work{Country: country.Country{ID: "ke-id", Code: "KE"}, RolesSource: country.RolesFromRegistry}
	as := func(role string, w *country.Work) context.Context {
		return auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: role, Country: w}})
	}
	for name, c := range map[string]struct {
		ctx  context.Context
		want string
	}{
		"no caller: the platform's own work":      {context.Background(), Every},
		"the Admin":                               {as("Admin", kenya), Every},
		"a regional role":                         {as("RegionalVicePresident", kenya), Every},
		"a Country Director working in Kenya":     {as("CountryDirector", kenya), "KE"},
		"a CCEO working in no Active country":     {as("CCEO", nil), ""},
		"a Business Transformation Officer (all)": {as("BusinessTransformationOfficer", nil), Every},
	} {
		if got := Wanted(c.ctx); got != c.want {
			t.Errorf("%s: %q, want %q", name, got, c.want)
		}
	}
}
