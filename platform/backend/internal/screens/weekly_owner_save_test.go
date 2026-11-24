package screens

import (
	"context"
	"fmt"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

type fakeWeekOwner struct {
	got    []string
	answer activities.Answer
	err    error
}

func (f *fakeWeekOwner) DecideOwnWeek(_ context.Context, _ auth.Principal, id, op string, bank bool, _ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, fmt.Sprintf("%s|%s|%v", id, op, bank))
	return f.answer, f.err
}

func (f *fakeWeekOwner) ConfirmMonthReceipt(_ context.Context, _ auth.Principal, id string, _ activities.Origin) (activities.Answer, error) {
	f.got = append(f.got, "month|"+id)
	return f.answer, f.err
}

func TestAMonthlyPlansReceiptSavesInGoWithoutDjango(t *testing.T) {
	owner := &fakeWeekOwner{answer: activities.Answer{Message: "Receipt confirmed for 2026-12."}}
	answer, err := decideVisit(NewService(nil).WithWeekOwner(owner), "/fund-requests/receipt-confirm?fund_request_id=fr1", nil)
	if err != nil || !answer.GetSaved() || len(owner.got) != 1 || owner.got[0] != "month|fr1" {
		t.Fatalf("answer %v, %v, got %v", answer, err, owner.got)
	}
}

func TestAnOwnersWeekButtonSavesInGoWithoutDjango(t *testing.T) {
	tests := []struct {
		path   string
		values map[string]string
		want   string
	}{
		{"/fund-requests/weekly/w1/confirm?fy=2027&week=2026-12-07", nil, "w1|send|false"},
		{"/fund-requests/weekly/w1/self-funded", nil, "w1|self_fund|false"},
		{"/fund-requests/weekly/w1/not-requested", nil, "w1|skip|false"},
		{"/fund-requests/weekly/w1/confirm-receipt", map[string]string{"bank_message_received": "on"}, "w1|receipt|true"},
	}
	for _, tt := range tests {
		owner := &fakeWeekOwner{answer: activities.Answer{Message: "Saved it."}}
		answer, err := decideVisit(NewService(nil).WithWeekOwner(owner), tt.path, tt.values)
		if err != nil || !answer.GetSaved() || answer.GetMessage() != "Saved it." || len(owner.got) != 1 || owner.got[0] != tt.want {
			t.Fatalf("%s: answer %v, %v, got %v", tt.path, answer, err, owner.got)
		}
	}
}

func TestAnOwnersWeekRefusalIsShownInTheDrawer(t *testing.T) {
	owner := &fakeWeekOwner{err: &activities.Refusal{Message: "Only the owner can confirm this request."}}
	answer, err := decideVisit(NewService(nil).WithWeekOwner(owner), "/fund-requests/weekly/w1/confirm", nil)
	if err != nil || answer.GetSaved() || answer.GetError() != "Only the owner can confirm this request." {
		t.Fatalf("answer %v, %v", answer, err)
	}
}

func TestAnOwnersWeekButtonStaysWithDjangoWhileDjangoIsThere(t *testing.T) {
	owner := &fakeWeekOwner{}
	fetcher := &formFetcher{}
	if _, err := decideVisit(NewService(fetcher).WithWeekOwner(owner), "/fund-requests/weekly/w1/confirm", nil); err != nil {
		t.Fatal(err)
	}
	if len(owner.got) != 0 || len(fetcher.paths) != 1 {
		t.Fatalf("Go saved %d, Django was asked %v", len(owner.got), fetcher.paths)
	}
}

func TestFundReceivedAsksForTheBankMessage(t *testing.T) {
	drawer, ok := NewService(nil).WithWeekOwner(&fakeWeekOwner{}).weekOwnerDrawer("/fund-requests/weekly/w1/confirm-receipt")
	if !ok || drawer.GetDrawer().GetSubmitLabel() != "Fund Received" {
		t.Fatalf("drawer %v, %v", drawer, ok)
	}
	field := drawer.GetDrawer().GetItems()[0].GetField()
	if field.GetName() != "bank_message_received" || field.GetKind() != "checkbox" || !field.GetRequired() || field.GetLabel() != bankReceivedLabel {
		t.Fatalf("field %v", field)
	}
	if _, ok := NewService(nil).WithWeekOwner(&fakeWeekOwner{}).weekOwnerDrawer("/fund-requests/weekly/w1/approve"); ok {
		t.Fatal("approve is not an owner's button")
	}
}
