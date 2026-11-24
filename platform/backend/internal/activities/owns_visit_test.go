package activities

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestOwnsVisitTakesEitherIdTheWorkIsFiledUnder(t *testing.T) {
	p := auth.Principal{UserID: "u1", StaffProfileID: "sp1"}
	cases := map[string]bool{"sp1": true, "u1": true, "": false, "sp2": false}
	for responsible, want := range cases {
		if got := ownsVisit(p, responsible); got != want {
			t.Errorf("ownsVisit(%q) = %v, want %v", responsible, got, want)
		}
	}
	if ownsVisit(auth.Principal{}, "") {
		t.Error("no ids own nothing")
	}
}
