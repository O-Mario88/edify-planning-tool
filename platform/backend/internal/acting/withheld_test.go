package acting

import "testing"

func TestWithheldPagePolicy(t *testing.T) {
	if !WithheldPage("acting_pl", "/leave/approvals") {
		t.Fatal("expected /leave/approvals to be withheld for acting_pl")
	}
	if !WithheldPage("acting_pl", "/fund-approvals/123") {
		t.Fatal("expected /fund-approvals/123 to be withheld for acting_pl")
	}
	if WithheldPage("acting_pl", "/pl/review-queue") {
		t.Fatal("expected /pl/review-queue to be allowed for acting_pl")
	}
	if !WithheldPage("acting_cd", "/country-budget") {
		t.Fatal("expected /country-budget to be withheld for acting_cd")
	}
	if WithheldPage("acting_cd", "/planning-monitor") {
		t.Fatal("expected /planning-monitor to be allowed for acting_cd")
	}
}
