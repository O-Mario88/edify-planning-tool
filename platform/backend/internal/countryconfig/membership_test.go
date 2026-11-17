package countryconfig

import (
	"strings"
	"testing"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
)

func TestGrantChecks(t *testing.T) {
	good := func() *countriesv1.GrantMembershipRequest {
		return &countriesv1.GrantMembershipRequest{UserId: "u1", CountryCode: "KE", EffectiveFrom: "2027-01-01",
			EffectiveUntil: "2027-07-01", Reason: "Kenya pilot"}
	}
	if g, err := grantOf(good()); err != nil || g.userID != "u1" || g.until != "2027-07-01" {
		t.Fatalf("a good grant: %+v, %v", g, err)
	}
	if _, err := grantOf(&countriesv1.GrantMembershipRequest{UserId: " u1 ", CountryCode: "UG", Reason: "Uganda"}); err != nil {
		t.Errorf("a grant from today, open-ended: %v", err)
	}
	for name, change := range map[string]func(*countriesv1.GrantMembershipRequest){
		"no account":          func(r *countriesv1.GrantMembershipRequest) { r.UserId = "  " },
		"an account too long": func(r *countriesv1.GrantMembershipRequest) { r.UserId = strings.Repeat("a", 31) },
		"a lowercase code":    func(r *countriesv1.GrantMembershipRequest) { r.CountryCode = "ke" },
		"a three-letter code": func(r *countriesv1.GrantMembershipRequest) { r.CountryCode = "KEN" },
		"a written date":      func(r *countriesv1.GrantMembershipRequest) { r.EffectiveFrom = "1 Jan 2027" },
		"a bad end":           func(r *countriesv1.GrantMembershipRequest) { r.EffectiveUntil = "2027-13-01" },
		"an end first":        func(r *countriesv1.GrantMembershipRequest) { r.EffectiveUntil = "2026-12-31" },
		"an end the same day": func(r *countriesv1.GrantMembershipRequest) { r.EffectiveUntil = r.EffectiveFrom },
		"no reason":           func(r *countriesv1.GrantMembershipRequest) { r.Reason = " \t" },
		"a long reason":       func(r *countriesv1.GrantMembershipRequest) { r.Reason = strings.Repeat("x", maxReason+1) },
	} {
		r := good()
		change(r)
		if _, err := grantOf(r); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}
