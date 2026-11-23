package activities

import (
	"errors"
	"strings"
	"testing"
	"time"
)

func TestARequestConfirmsWhoDecidesIt(t *testing.T) {
	got := requestedMessage("Paul N.")
	want := "Requested, pending Paul N.'s approval. It takes effect on your plan and enters your budget once approved."
	if got != want {
		t.Fatalf("message = %q", got)
	}
}

func TestTheOwnerIsAskedInTheRequestersWords(t *testing.T) {
	day := time.Date(2026, 12, 8, 0, 0, 0, 0, time.UTC)
	notice := requestNotice("Ann K.", "Mpatta Primary", "To check the receipts", "owner-1", day)
	if notice.title != "Visit request for your school" {
		t.Fatalf("title = %q", notice.title)
	}
	if want := "Ann K. asks to visit Mpatta Primary on 8 Dec 2026: To check the receipts"; notice.body != want {
		t.Fatalf("body = %q", notice.body)
	}
	if notice.event != "school_visit_requested" || notice.recipient != "owner-1" ||
		notice.route != "/planning/visit-requests" || notice.label != "Decide on Visit Request" ||
		notice.category != "activity" || notice.contextType != "Activity" {
		t.Fatalf("notice = %+v", notice)
	}
}

func TestARequesterWithNoNameIsAStaffMember(t *testing.T) {
	day := time.Date(2026, 12, 8, 0, 0, 0, 0, time.UTC)
	notice := requestNotice("", "Mpatta", "Why", "owner-1", day)
	if want := "A staff member asks to visit Mpatta on 8 Dec 2026: Why"; notice.body != want {
		t.Fatalf("body = %q", notice.body)
	}
}

func TestTheRequestsReasonIsReadFromTheForm(t *testing.T) {
	req, taken := RequestFromForm(map[string][]string{
		"require_catalogue": {"yes"}, "purpose_of_visit": {"donor_visit"}, "visit_justification": {"  To check receipts "},
	})
	if !taken || req.Justification != "To check receipts" {
		t.Fatalf("taken = %v, reason = %q", taken, req.Justification)
	}
}

func TestARequestStillMeetsTheChampionRule(t *testing.T) {
	champion := school{Name: "Nakifuma", Type: "champion"}
	if err := requestEntitlement(champion, "donor_visit"); err != nil {
		t.Fatalf("a Champion school takes a donor visit: %v", err)
	}
	err := requestEntitlement(champion, "school_visit_ssa_collection")
	var refused *Refusal
	if !errors.As(err, &refused) || !strings.Contains(refused.Message, "is a Champion school") {
		t.Fatalf("err = %v", err)
	}
	if err := requestEntitlement(school{Name: "Mpatta", Type: "client"}, "school_visit_ssa_collection"); err != nil {
		t.Fatalf("a client school's request waits for its owner: %v", err)
	}
}

func TestARequestWaitsForTheOwnerAndCostsNothing(t *testing.T) {
	r := activityRow{approvalOwner: "owner-1", justification: "Why"}
	if r.status() != "awaiting_owner_approval" {
		t.Fatalf("status = %q", r.status())
	}
	if !r.isRequest() {
		t.Fatal("this row is a request")
	}
	if plain := (activityRow{}); plain.status() != "scheduled" || plain.isRequest() {
		t.Fatalf("a plain visit: %q %v", plain.status(), plain.isRequest())
	}
}
