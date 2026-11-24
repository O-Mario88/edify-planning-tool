package screens

import (
	"context"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

type fakeAccountant struct {
	got  []activities.AccountabilityForm
	err  error
	view activities.AccountabilityView
}

func (f *fakeAccountant) AccountabilityDrawer(context.Context, auth.Principal, string) (activities.AccountabilityView, error) {
	return f.view, f.err
}

func (f *fakeAccountant) SubmitAccountability(_ context.Context, _ auth.Principal, _ string, form activities.AccountabilityForm, _ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, form)
	return activities.Answer{Message: "Saved. Press Refresh to see it on the page."}, f.err
}

func TestTheAccountabilityDrawerSavesInGoWithoutDjango(t *testing.T) {
	acc := &fakeAccountant{}
	answer, err := decideVisit(NewService(nil).WithAccountability(acc), "/my-plan/a1/accountability", map[string]string{
		"amount_spent": "9000", "amount_returned": "1000", "variance_note": "fuel", "netsuite_code": "EXP-1", "receipt_file": "st1",
	})
	want := activities.AccountabilityForm{Spent: "9000", Returned: "1000", VarianceNote: "fuel", NetsuiteCode: "EXP-1", ReceiptID: "st1"}
	if err != nil || !answer.GetSaved() || len(acc.got) != 1 || acc.got[0] != want {
		t.Fatalf("answer %v, %v, got %v", answer, err, acc.got)
	}
}

func TestAnAccountabilityRefusalIsShownInTheDrawer(t *testing.T) {
	acc := &fakeAccountant{err: &activities.Refusal{Message: "Amounts must be whole UGX numbers."}}
	answer, err := decideVisit(NewService(nil).WithAccountability(acc), "/my-plan/a1/accountability", nil)
	if err != nil || answer.GetSaved() || answer.GetError() != "Amounts must be whole UGX numbers." {
		t.Fatalf("answer %v, %v", answer, err)
	}
}

func TestTheAccountabilityDrawerShowsWhatWasDisbursed(t *testing.T) {
	drawer := accountabilityDrawer(activities.AccountabilityView{School: "Mpatta", Total: 62000, Lines: [][2]string{{"Lunch", "UGX 12,000"}}})
	if drawer.GetTitle() != "Submit accountability for Mpatta" || drawer.GetItems()[0].GetText() != "Disbursed to you: UGX 62,000" ||
		drawer.GetItems()[1].GetText() != "Lunch — UGX 12,000" || drawer.GetSubmitLabel() != "Submit for finance review" {
		t.Fatalf("drawer %v", drawer)
	}
	var file, netsuite bool
	for _, item := range drawer.GetItems() {
		f := item.GetField()
		file = file || (f.GetName() == "receipt_file" && f.GetKind() == "file")
		netsuite = netsuite || (f.GetName() == "netsuite_code" && f.GetRequired())
	}
	if !file || !netsuite {
		t.Fatalf("receipt %v netsuite %v", file, netsuite)
	}
}
