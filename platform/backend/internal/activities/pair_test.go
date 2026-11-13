package activities

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestTheCourseDecidesTheInterventionOnlyWhereGoTakesIt(t *testing.T) {
	fixed := func(intervention string) courseMapping {
		return courseMapping{Mode: "fixed", Intervention: intervention, Primary: true}
	}
	tests := []struct {
		name      string
		mappings  []courseMapping
		wantFocus string
		wantTaken bool
	}{
		{"fixed to one intervention", []courseMapping{fixed("leadership")}, "leadership", true},
		{"an orientation, linked to none", []courseMapping{{Mode: "administrative", Primary: true}}, "", true},
		{"fixed to a name outside the eight", []courseMapping{fixed("school_improvement")}, "school_improvement", false},
		{"the planner chooses", []courseMapping{{Mode: "any_ssa_intervention", Primary: true}}, "", false},
		{"no mapping", nil, "", false},
		{"two mappings", []courseMapping{fixed("leadership"), fixed("enrolment")}, "", false},
		{"not primary", []courseMapping{{Mode: "fixed", Intervention: "leadership"}}, "", false},
		{"administrative naming one", []courseMapping{{Mode: "administrative", Intervention: "leadership", Primary: true}}, "", false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			focus, taken := course{Mappings: test.mappings}.focus()
			if taken != test.wantTaken || (taken && focus != test.wantFocus) {
				t.Fatalf("focus() = %q, %v; want %q, %v", focus, taken, test.wantFocus, test.wantTaken)
			}
		})
	}
}

func TestACourseOfAnotherPurposesKindWouldBeReplacedByTheView(t *testing.T) {
	for kind, want := range map[string]bool{
		"cluster_training": false, "in_school_training": false, "training_follow_up_visit": true, "donor_visit": true,
	} {
		if got := (course{Kind: kind}).conflicts(); got != want {
			t.Errorf("conflicts(%s) = %v, want %v", kind, got, want)
		}
	}
}

func TestTheTwoPurposesPlanThePairAndNoOther(t *testing.T) {
	for purpose, want := range map[string]bool{
		"in_school_training": true, " in_school_training_ssa ": true, "training_follow_up": false,
		"in_school_training_delivery_visit": false, "": false,
	} {
		if got := IsPairPurpose(purpose); got != want {
			t.Errorf("IsPairPurpose(%q) = %v, want %v", purpose, got, want)
		}
	}
	// The six visit purposes stay the first save's: the pair never joins
	// them, so a move, cancel or edit of either half is handed on.
	for _, purpose := range inScopePurposes {
		if IsPairPurpose(purpose) {
			t.Errorf("%s is both a visit purpose and the pair's", purpose)
		}
	}
}

func TestAUniversalCourseIsOnTopOfTheEntitlementButNotOfTheChampionRule(t *testing.T) {
	client := school{Name: "A School", Type: "client"}
	// A universal course at a client school never asks the visit gate: the
	// nil querier would fail if it did.
	if err := trainingEntitlement(context.Background(), nil, client, course{Universal: true}, "2027", time.Now()); err != nil {
		t.Fatalf("universal course refused: %v", err)
	}
	champion := school{Name: "A School", Type: "champion"}
	err := trainingEntitlement(context.Background(), nil, champion, course{Universal: true}, "2027", time.Now())
	var refusal *Refusal
	if !errors.As(err, &refusal) || refusal.Message != "A School is a Champion school: it receives no training or assessment, and is planned only for a Donor Visit or a Content/Story Collection visit." {
		t.Fatalf("champion refusal = %v", err)
	}
}

func TestThePairIsHandedOnBeforeAnyReadForWhatGoDoesNotTake(t *testing.T) {
	s := &Service{now: time.Now, kampala: time.UTC}
	owner := auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: "CCEO", StaffProfileID: "sp"}}
	tests := []struct {
		name string
		p    auth.Principal
		req  Request
	}{
		{"a person in another's seat", auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: "CCEO",
			StaffProfileID: "sp", InActingAppointment: true}}, Request{Purpose: "in_school_training", Date: "2026-11-24"}},
		{"no staff profile", auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: "CCEO"}},
			Request{Purpose: "in_school_training", Date: "2026-11-24"}},
		{"a date in another form", owner, Request{Purpose: "in_school_training", Date: "24/11/2026"}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := s.Schedule(context.Background(), test.p, test.req, Origin{}); !errors.Is(err, ErrHandOn) {
				t.Fatalf("got %v, want a hand-on", err)
			}
		})
	}
}

func TestThePairsOwnRefusalsComeBeforeAnyRead(t *testing.T) {
	s := &Service{now: time.Now, kampala: time.UTC}
	owner := auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: "CCEO", StaffProfileID: "sp"}}
	for req, want := range map[Request]string{
		{Purpose: "in_school_training"}:                                            "Pick the date this is planned for before scheduling it.",
		{Purpose: "in_school_training_ssa", Date: "2026-02-30"}:                    "That scheduled date is not a valid calendar date.",
		{Purpose: "in_school_training", Date: "2026-11-24"}:                        noCourse,
		{Purpose: "in_school_training", Date: "2026-11-24", CatalogueItemID: "  "}: noCourse,
	} {
		_, err := s.Schedule(context.Background(), owner, req, Origin{})
		var refusal *Refusal
		if !errors.As(err, &refusal) || refusal.Message != want {
			t.Errorf("%+v: got %v, want %q", req, err, want)
		}
	}
}
