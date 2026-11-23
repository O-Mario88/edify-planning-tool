package screens

import (
	"slices"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

func TestReviewFormsAnswerTheirAddresses(t *testing.T) {
	form, ok := fieldFormFor("/pl/review-queue/act1/return-drawer")
	if !ok {
		t.Fatal("the return form is not served")
	}
	if got := form.recordID("/pl/review-queue/act1/return-drawer"); got != "act1" {
		t.Fatalf("record id %q", got)
	}
	for _, role := range []string{rbac.Admin, rbac.ProgramLead, roleIA} {
		if why := form.refusal(fieldPrincipal(role)); why != "" {
			t.Errorf("%s refused: %s", role, why)
		}
	}
	want := "Access Denied: Your active role does not have permission to view Pl Review Queue."
	for _, role := range []string{roleCD, rbac.CCEO, roleAccountant, rolePC} {
		if why := form.refusal(fieldPrincipal(role)); why != want {
			t.Errorf("%s: %q", role, why)
		}
	}
}

func TestReturnDrawerAsksForTheReason(t *testing.T) {
	drawer := plReturnDrawer(plreview.Review{
		Officer: "Paul N.", Activity: "School Visit", Where: "Goma Primary", Delivered: "23 Nov 2026",
	})
	if drawer.GetTitle() != "Return completion" || drawer.GetSubtitle() != "School Visit" ||
		drawer.GetSubmitLabel() != "Return to officer" || !drawer.GetCanSubmit() {
		t.Fatalf("header: %v", drawer)
	}
	facts := drawer.GetItems()[0].GetFacts().GetFacts()
	labels := make([]string, 0, len(facts))
	for _, fact := range facts {
		labels = append(labels, fact.GetLabel())
	}
	if !slices.Equal(labels, []string{"Officer", "Activity", "School or cluster", "Delivered"}) {
		t.Fatalf("facts: %v", labels)
	}
	reasons, written := drawer.GetItems()[1].GetField(), drawer.GetItems()[2].GetField()
	if reasons.GetName() != "reasons" || reasons.GetKind() != "checklist" || len(reasons.GetOptions()) != 5 {
		t.Fatalf("reasons: %v", reasons)
	}
	if written.GetName() != "reason" || written.GetKind() != "textarea" || written.GetMaxLength() != 400 {
		t.Fatalf("written reason: %v", written)
	}
}

func TestVerifyDrawerStandsOnTheSalesforceID(t *testing.T) {
	review := plreview.Review{Officer: "Paul N.", Activity: "School Visit", Where: "Goma Primary", Delivered: "3 Apr 2026"}
	const decisionNote = "Verified confirms the completion against Salesforce and marks it complete. Return sends it back to the officer with your reason — for example, participants not entered in Salesforce."

	withID := plReviewDrawer(review, plreview.ReviewDetail{SalesforceKind: "training", SalesforceID: "TR-1"}, "")
	if !withID.GetCanSubmit() || withID.GetSubmitLabel() != "Verified" {
		t.Fatalf("an ID lets the lead verify: %v", withID)
	}
	if got := withID.GetItems()[1].GetHeading(); got != "Training ID" {
		t.Fatalf("heading %q", got)
	}
	if got := withID.GetItems()[2].GetText(); got != "TR-1" {
		t.Fatalf("id %q", got)
	}
	if got := withID.GetItems()[len(withID.GetItems())-1].GetNote().GetText(); got != decisionNote {
		t.Fatalf("decision note %q", got)
	}

	missing := plReviewDrawer(review, plreview.ReviewDetail{SalesforceKind: "visit"}, "")
	if missing.GetCanSubmit() || missing.GetSubmitLabel() != "" {
		t.Fatalf("no ID, nothing to confirm: %v", missing)
	}
	if got := missing.GetItems()[2].GetNote(); got.GetTone() != "warning" ||
		got.GetText() != "No visit ID was entered with this completion. Return it to the officer with the reason." {
		t.Fatalf("missing id note: %v", got)
	}

	noRecord := plReviewDrawer(review, plreview.ReviewDetail{}, "")
	if !noRecord.GetCanSubmit() || noRecord.GetItems()[1].GetHeading() != "Salesforce ID" ||
		noRecord.GetItems()[2].GetText() != "This activity has no Salesforce record, so it carries no ID." {
		t.Fatalf("no Salesforce record: %v", noRecord)
	}

	partner := plReviewDrawer(review, plreview.ReviewDetail{SalesforceKind: "training", SalesforceID: "TR-1"}, "partner-trainings")
	if partner.GetSubmitLabel() != "Confirm Verification" {
		t.Fatalf("partner trainings wording: %q", partner.GetSubmitLabel())
	}
}

func TestVerifyDrawerFactsKeepTheirOrder(t *testing.T) {
	drawer := plReviewDrawer(plreview.Review{Officer: "Paul N."}, plreview.ReviewDetail{
		SSABasis: "Off priority. Reason.", SSADeparture: "Asked for first.",
	}, "")
	want := []string{"Officer", "Activity", "School or cluster", "Delivered", "Intervention", "SSA basis",
		"Why it departs from the SSA", "Attendance", "Purpose", "Outcome", "Observations", "Follow-up"}
	got := []string{}
	for _, fact := range drawer.GetItems()[0].GetFacts().GetFacts() {
		got = append(got, fact.GetLabel())
	}
	if !slices.Equal(got, want) {
		t.Fatalf("facts: %v", got)
	}
}

func TestReviewFormSaysWhyItIsNotWaiting(t *testing.T) {
	drawer := reviewNoticeDrawer("Return completion", "Activity is not awaiting PL review.")
	if drawer.GetSubtitle() != "Not waiting on you" || drawer.GetCanSubmit() {
		t.Fatalf("notice: %v", drawer)
	}
	note := drawer.GetItems()[0].GetNote()
	if note.GetText() != "Activity is not awaiting PL review." || note.GetTone() != "info" {
		t.Fatalf("note: %v", note)
	}
}
