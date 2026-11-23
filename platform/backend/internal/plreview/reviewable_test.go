package plreview

import "testing"

const (
	notFoundWords   = "Activity not found."
	notWaitingWords = "Activity is not awaiting PL review."
	iaWorkWords     = "This work is verified by Impact Assessment."
	ownWorkWords    = "You cannot review your own completion."
	otherTeamWords  = "This completion belongs to another Program Lead's team."
)

func TestRefusalForIsTheExistingReviewRule(t *testing.T) {
	lead := reviewerReach{clearsOwn: true, own: []string{"u-lead", "sp-lead"}, supervised: []string{"sp-officer", "u-officer"}}
	actingLead := reviewerReach{own: []string{"u-acting", "sp-acting"}, supervised: []string{"sp-officer"}}
	admin := reviewerReach{admin: true, own: []string{"u-admin"}}
	impact := reviewerReach{own: []string{"u-ia"}}
	waiting := func(owner, delivery string) reviewCase {
		return reviewCase{found: true, status: statusSubmittedToPL, deliveryType: delivery, owner: owner}
	}
	olderPath := func(owner, delivery string, leadVerified bool) reviewCase {
		return reviewCase{found: true, status: statusAwaitingIA, deliveryType: delivery, owner: owner, ownerLeadVerified: leadVerified}
	}

	cases := []struct {
		name      string
		work      reviewCase
		reviewer  reviewerReach
		words     string
		forbidden bool
	}{
		{name: "a missing record", work: reviewCase{}, reviewer: admin, words: notFoundWords},
		{name: "work no longer waiting", work: reviewCase{found: true, status: "ia_verified", owner: "sp-officer"}, reviewer: lead, words: notWaitingWords},
		{name: "partner work left with IA, even for the Admin", work: olderPath("sp-officer", "partner", true), reviewer: admin, words: iaWorkWords},
		{name: "partner work left with IA, for the lead", work: olderPath("sp-officer", "partner", true), reviewer: lead, words: iaWorkWords},
		{name: "staff work of someone no lead verifies", work: olderPath("sp-coordinator", "staff", false), reviewer: lead, words: iaWorkWords},
		{name: "staff work an older path left with IA", work: olderPath("sp-officer", "staff", true), reviewer: lead},
		{name: "the Admin decides any waiting work", work: waiting("sp-anyone", "staff"), reviewer: admin},
		{name: "a lead clears their own staff work", work: waiting("sp-lead", "staff"), reviewer: lead},
		{name: "a lead's own work under their user id", work: waiting("u-lead", "staff"), reviewer: lead},
		{name: "a lead never clears partner work they monitor", work: waiting("sp-lead", "partner"), reviewer: lead, words: ownWorkWords, forbidden: true},
		{name: "an acting lead never clears their own work", work: waiting("u-acting", "staff"), reviewer: actingLead, words: ownWorkWords, forbidden: true},
		{name: "a supervisee filed under a profile id", work: waiting("sp-officer", "staff"), reviewer: lead},
		{name: "a supervisee filed under a user id", work: waiting("u-officer", "staff"), reviewer: lead},
		{name: "another lead's officer", work: waiting("sp-elsewhere", "staff"), reviewer: lead, words: otherTeamWords, forbidden: true},
		{name: "work with no owner", work: waiting("", "staff"), reviewer: lead, words: otherTeamWords, forbidden: true},
		{name: "Impact Assessment holds no team", work: waiting("sp-officer", "staff"), reviewer: impact, words: otherTeamWords, forbidden: true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := refusalFor(tc.work, tc.reviewer)
			if tc.words == "" {
				if got != nil {
					t.Fatalf("refused with %q", got.Message)
				}
				return
			}
			if got == nil {
				t.Fatalf("allowed, want %q", tc.words)
			}
			if got.Message != tc.words || got.Forbidden != tc.forbidden {
				t.Fatalf("got %q forbidden=%v, want %q forbidden=%v", got.Message, got.Forbidden, tc.words, tc.forbidden)
			}
		})
	}
}

func TestOnlyALeadOrTheAdminDecidesACompletion(t *testing.T) {
	for _, allowed := range []string{"Program Lead", "Admin"} {
		if !canReviewRole(allowed) {
			t.Errorf("%q should decide completions", allowed)
		}
	}
	for _, denied := range []string{"CountryDirector", "ImpactAssessment", "CCEO", "Accountant", "PartnerAdmin", ""} {
		if canReviewRole(denied) {
			t.Errorf("%q should not decide completions", denied)
		}
	}
}
