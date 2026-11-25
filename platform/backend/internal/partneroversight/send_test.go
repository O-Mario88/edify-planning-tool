package partneroversight

import "testing"

// The drawer's first form is the first risk that offers a send: a role's
// queue, the Partner or the CCEO, by who the risk names; none offers one
// when no risk does.
func TestFirstFormIsTheFirstRiskWithASend(t *testing.T) {
	for _, c := range []struct {
		risks          []partnerRisk
		intent, riskID string
	}{
		{[]partnerRisk{{key: "partner_rate_missing"}, {key: "ia_verification_overdue", role: "ImpactAssessment"}},
			"nudge_queue", "ia_verification_overdue"},
		{[]partnerRisk{{key: "partner_delivery_overdue"}, {key: "salesforce_overdue"}}, "remind_partner", "partner_delivery_overdue"},
		{[]partnerRisk{{key: "assignment_returned"}}, "send_to_cceo", "assignment_returned"},
		{[]partnerRisk{{key: "partner_rate_missing"}}, "", ""},
		{nil, "", ""},
	} {
		intent, risk := firstForm(c.risks)
		if intent != c.intent || risk != c.riskID {
			t.Errorf("firstForm(%v) = %q, %q; want %q, %q", c.risks, intent, risk, c.intent, c.riskID)
		}
	}
	if rules.Work.Sends.CCEOIssueKeys["salesforce_overdue"] != "partner_salesforce_overdue" || rules.Work.Sends.EscalationScope != "PartnerAssignment" {
		t.Fatalf("the send rules: %+v", rules.Work.Sends)
	}
}

// A CCEO only asks their Lead to take back work the Partner has dated; work
// still unscheduled, or dated only by staff, they withdraw themselves, and
// every other role decides.
func TestMustRequestIsTheOfficersAsk(t *testing.T) {
	for _, c := range []struct {
		role, kind  string
		dated, want bool
	}{
		{"CCEO", "recall_scheduled", true, true},
		{"CCEO", "recall_scheduled", false, false},
		{"CCEO", "withdraw_unscheduled", false, false},
		{"CCEO", "payment_hold", false, true},
		{"Program Lead", "recall_scheduled", true, false},
	} {
		if got := mustRequest(c.role, preview{kind: c.kind, dated: c.dated}); got != c.want {
			t.Errorf("mustRequest(%s, %s, dated %v) = %v", c.role, c.kind, c.dated, got)
		}
	}
}
