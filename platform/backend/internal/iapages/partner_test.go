package iapages

import "testing"

func TestPartnerEvidenceCountsTheRequiredKindsItHolds(t *testing.T) {
	if got, done := evidenceLabel(partnerWork{Kind: "school_visit"}); got != "0/1 required" || done {
		t.Errorf("none held: %q %v", got, done)
	}
	if got, done := evidenceLabel(partnerWork{Kind: "school_visit", Held: []string{"visit_form", "photo"}}); got != "1/1 required" || !done {
		t.Errorf("held: %q %v", got, done)
	}
	if got, done := evidenceLabel(partnerWork{Kind: "made_up", Held: []string{"photo"}}); got != "1 file(s)" || !done {
		t.Errorf("nothing required: %q %v", got, done)
	}
	if got, _ := evidenceLabel(partnerWork{Kind: "school_visit", Profile: "ADMIN_NONE"}); got != "0 file(s)" {
		t.Errorf("profile none: %q", got)
	}
}
