package partnerpayments

import "testing"

func TestTheDocumentRouteNamesBothDownloadsAndNothingElse(t *testing.T) {
	route := DocumentRoute(nil, nil)
	for target, want := range map[string]bool{
		"/accounts/partner-invoices/inv1/download": true,
		"/fund-approvals/invoices/inv1/download":   true,
		"/fund-approvals/invoices/inv1/action":     false,
		"/accounts/partner-invoices/":              false,
	} {
		if _, ok := route(target); ok != want {
			t.Fatalf("%s: %v", target, ok)
		}
	}
}
