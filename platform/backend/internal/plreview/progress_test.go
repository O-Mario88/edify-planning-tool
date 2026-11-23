package plreview

import "testing"

func TestACreditRuleMatchesAsTheExistingRuleDoes(t *testing.T) {
	work := creditFacts{Project: "p1", Delivery: "staff", Method: "in_person", HasSchool: true, SchoolType: "champion", Intervention: "leadership"}
	cases := []struct {
		name string
		rule creditRule
		want bool
	}{
		{"no conditions", creditRule{}, true},
		{"its project", creditRule{Project: "p1"}, true},
		{"another project", creditRule{Project: "p2"}, false},
		{"its executor", creditRule{Executor: "staff"}, true},
		{"another executor", creditRule{Executor: "partner"}, false},
		{"its delivery method", creditRule{Method: "in_person"}, true},
		{"another delivery method", creditRule{Method: "online"}, false},
		{"a family holding the school's type", creditRule{SchoolType: "core"}, true},
		{"a family without it", creditRule{SchoolType: "client"}, false},
		{"the type itself", creditRule{SchoolType: "champion"}, true},
		{"its intervention", creditRule{Intervention: "leadership"}, true},
		{"another intervention", creditRule{Intervention: "enrolment"}, false},
		{"a school level, which no school record carries", creditRule{SchoolLevel: "primary"}, false},
	}
	for _, tc := range cases {
		if got := tc.rule.matches(work); got != tc.want {
			t.Errorf("%s: got %v", tc.name, got)
		}
	}
	if (creditRule{SchoolType: "core"}).matches(creditFacts{}) {
		t.Error("work at no school cannot meet a school-type rule")
	}
}

func TestOneMilestoneEarnsOneCredit(t *testing.T) {
	work := creditFacts{Delivery: "staff"}
	rules := []creditRule{
		{ID: "r1", Milestone: "m1"},
		{ID: "r2", Milestone: "m2", Executor: "partner"},
		{ID: "r3", Milestone: "m3"},
	}
	planned, ambiguous := plannedCredits(rules, work, map[string]bool{"m3": true})
	if ambiguous || len(planned) != 1 || planned[0].ID != "r1" {
		t.Fatalf("planned=%v ambiguous=%v", planned, ambiguous)
	}
}

func TestTwoRulesOnOneMilestoneAreLeftToTheExistingApplication(t *testing.T) {
	// Which of two matching rules earns the credit is the unordered query's
	// choice there, so Go does not guess it.
	rules := []creditRule{{ID: "r1", Milestone: "m1"}, {ID: "r2", Milestone: "m1"}}
	if _, ambiguous := plannedCredits(rules, creditFacts{}, map[string]bool{}); !ambiguous {
		t.Fatal("expected the choice to be handed on")
	}
	if _, ambiguous := plannedCredits(rules, creditFacts{}, map[string]bool{"m1": true}); ambiguous {
		t.Fatal("a milestone already credited has nothing to choose")
	}
}

func TestACreditNeedsItsSalesforceReference(t *testing.T) {
	cases := []struct {
		recordType, id string
		want           bool
	}{
		{"NONE", "", true},
		{"VISIT", "SV-1", true},
		{"VISIT", "   ", false},
		{"", "", false},
		{"none", "", false},
	}
	for _, tc := range cases {
		if got := salesforceSatisfied(tc.recordType, tc.id); got != tc.want {
			t.Errorf("%q %q: got %v", tc.recordType, tc.id, got)
		}
	}
}
