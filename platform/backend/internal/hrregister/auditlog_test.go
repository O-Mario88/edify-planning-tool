package hrregister

import "testing"

func TestAnAuditActionReadsAsItsAreaAndItsName(t *testing.T) {
	for action, want := range map[string]string{
		"hr.er_case_opened":       "HR · Er case opened",
		"leave.approved":          "Leave · Approved",
		"documents.policy.agreed": "Policy · Policy agreed",
		"admin.user_disabled":     "Accounts · User disabled",
		"pd_request_approved":     "Pd_Request_Approved · Pd request approved",
		"other.thing":             "Other · Thing",
		"":                        "—",
		"hr.":                     "HR · Hr",
	} {
		if got := auditActionLabel(action); got != want {
			t.Errorf("%q reads %q, want %q", action, got, want)
		}
	}
}

func TestStartsWithEscapesLikeWildcards(t *testing.T) {
	if got := likeStarts(`pd_`); got != `pd\_%` {
		t.Errorf("likeStarts = %q", got)
	}
}
