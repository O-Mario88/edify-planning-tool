package activities

import (
	"testing"
	"time"
)

func TestTheOwnerIsToldOfAVisitSomeoneElsePutOnTheirPlan(t *testing.T) {
	day := time.Date(2026, 12, 2, 0, 0, 0, 0, time.UTC)
	notice, ok := ownerNotice("donor_visit", "owner-staff", "actor-user", "actor-staff", "Mpatta Primary", day)
	if !ok {
		t.Fatal("the owner must be told")
	}
	if notice.title != "School visit scheduled" || notice.body != "Mpatta Primary on 2 Dec 2026." {
		t.Fatalf("notice = %+v", notice)
	}
	if notice.event != "school_visit_scheduled" {
		t.Fatalf("event = %q", notice.event)
	}
}

func TestNobodyIsToldOfTheirOwnScheduling(t *testing.T) {
	day := time.Date(2026, 12, 2, 0, 0, 0, 0, time.UTC)
	for name, owner := range map[string]string{"their staff id": "actor-staff", "their user id": "actor-user", "no owner": ""} {
		if _, ok := ownerNotice("donor_visit", owner, "actor-user", "actor-staff", "Mpatta", day); ok {
			t.Fatalf("%s: nobody should be told", name)
		}
	}
}

func TestTheSchedulerIsToldWhosePlanTheVisitLandedOn(t *testing.T) {
	day := time.Date(2026, 12, 2, 0, 0, 0, 0, time.UTC)
	message, planURL, label := colleagueConfirmation("Paul N.", day)
	want := "School visit scheduled onto Paul N.'s My Plan, because the responsible staff member comes from the school's owner."
	if message != want {
		t.Fatalf("message = %q", message)
	}
	if planURL != "/calendar?month=12&year=2026" || label != "Open the Calendar" {
		t.Fatalf("link = %q %q", planURL, label)
	}
}

func TestOnlyVisitsTellTheOwner(t *testing.T) {
	day := time.Date(2026, 12, 2, 0, 0, 0, 0, time.UTC)
	if _, ok := ownerNotice("in_school_training", "owner", "actor-user", "actor-staff", "Mpatta", day); ok {
		t.Fatal("a training is not a school visit")
	}
	for _, kind := range []string{
		"donor_visit", "story_gathering_visit", "school_invitation", "social_visit",
		"training_follow_up_visit", "school_visit_ssa_collection",
	} {
		if _, ok := ownerNotice(kind, "owner", "actor-user", "actor-staff", "Mpatta", day); !ok {
			t.Fatalf("%s is a visit", kind)
		}
	}
}
