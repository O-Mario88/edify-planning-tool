package activities

import "testing"

func TestPackageKindFollowsTheExistingRule(t *testing.T) {
	cases := []struct {
		name, kind, purpose, cluster, delivery, want string
	}{
		{"a school visit", "school_visit", "", "", "staff", "visit"},
		{"an in-school training", "in_school_training", "", "", "staff", "training"},
		{"a cluster session", "training", "", "cl1", "staff", ""},
		{"a donor visit", "donor_visit", "", "", "staff", ""},
		{"an outreach purpose", "school_visit", "story_gathering", "", "staff", ""},
		{"staff SSA Support", "school_visit", "ssa_support", "", "staff", "visit"},
		{"a partner's SSA Support", "school_visit", "ssa_support", "", "partner", ""},
		{"an SSA collection visit", "school_visit_ssa_collection", "", "", "staff", "visit"},
		{"something else", "meeting", "", "", "staff", ""},
	}
	for _, c := range cases {
		if got := packageKindFor(c.kind, c.purpose, c.cluster, c.delivery); got != c.want {
			t.Errorf("%s: got %q, want %q", c.name, got, c.want)
		}
	}
	companion := creditWork{kind: "school_visit", purpose: creditRules.CompanionVisitPurpose, delivery: "staff"}
	if got := slotKindFor(companion); got != "visit" {
		t.Errorf("the visit beside an in-school training: got %q, want a package visit", got)
	}
	if got := packageKindFor(companion.kind, companion.purpose, "", "staff"); got != "" {
		t.Errorf("package_kind_for leaves the companion visit out, got %q", got)
	}
}
