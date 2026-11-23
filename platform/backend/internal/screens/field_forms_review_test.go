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
