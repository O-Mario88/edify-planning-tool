//go:build integration

package integration

import (
	"strings"
	"testing"

	"connectrpc.com/connect"
)

// Platform Health through the gateway, as Admin: the database reached as the
// gateway's own role, its sessions read-only by default, and each schema Go
// owns listed with its migration; a CCEO is refused.
func TestPlatformHealthReadsTheGatewaysOwnState(t *testing.T) {
	borrowAccount(t, "admin@edify.org")
	result, err := signIn(t, signInClientAt("10.30.1.1"), "admin@edify.org", seededPassword)
	if err != nil || result.GetSession() == nil {
		t.Fatalf("signing in: %v", err)
	}
	page, err := pageOf(result.GetSession().GetAccessToken(), "/platform-health", map[string]string{})
	if err != nil {
		t.Fatal(err)
	}
	if page.GetHeader().GetTitle() != "Platform Health" {
		t.Fatalf("title %q", page.GetHeader().GetTitle())
	}
	rows := map[string]string{}
	for _, b := range page.GetBlocks() {
		for _, item := range b.GetPanel().GetItems() {
			for _, r := range item.GetRows().GetRows() {
				rows[r.GetLabel()] = r.GetValue() + " | " + r.GetTone()
			}
		}
	}
	if got := rows["Read-only by default"]; got != "Yes | success" {
		t.Errorf("read-only by default: %q", got)
	}
	if got := rows["Connection"]; !strings.Contains(got, " as ") || !strings.HasSuffix(got, "| success") {
		t.Errorf("connection: %q", got)
	}
	for _, schema := range []string{"cluster_leadership", "field_routes", "school_loans"} {
		if _, ok := rows[schema]; !ok {
			t.Errorf("schema %s is not listed (rows: %v)", schema, rows)
		}
	}
	for _, label := range []string{"Audit chain", "Audit rows waiting to be sealed", "Target ledgers to rebuild", "Costs to settle after Go saves"} {
		if v := rows[label]; v == "" || strings.HasPrefix(v, "Could not be read") {
			t.Errorf("%s: %q", label, v)
		}
	}
	t.Logf("rows: %v", rows)

	borrowAccount(t, "cceo1@edify.org")
	officer, err := signIn(t, signInClientAt("10.30.1.2"), "cceo1@edify.org", seededPassword)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := pageOf(officer.GetSession().GetAccessToken(), "/platform-health", map[string]string{}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Errorf("a CCEO: %v, want not found", err)
	}
}
