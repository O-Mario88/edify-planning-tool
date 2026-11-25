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
