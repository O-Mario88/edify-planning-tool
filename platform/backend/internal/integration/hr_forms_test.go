//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// The HR programmes' forms are Go's with Django absent: Recognise someone
// offers the People records HR reaches and records a recognition with its
// audit row; a role without HR's authority is told so; and the compliance
// register refuses a requirement for every country to anyone but the Admin.
func TestTheHRFormsSaveInGo(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "hr@edify.org")
	hr := sessionOf(t, "hr@edify.org", seededPassword).GetAccessToken()
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	d, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: "/recognition/new"}, hr))
	if err != nil {
		t.Fatalf("the recognition drawer: %v", err)
	}
	var staff string
	for _, item := range d.Msg.GetDrawer().GetItems() {
		if f := item.GetField(); f.GetName() == "staff_id" && len(f.GetOptions()) > 1 {
			staff = f.GetOptions()[1].GetValue()
		}
	}
	if d.Msg.GetDrawer().GetTitle() != "Recognise someone" || staff == "" {
		t.Fatalf("drawer %q offers no employee", d.Msg.GetDrawer().GetTitle())
	}
	const citation = "integration: led the cluster week"
	t.Cleanup(func() { _, _ = admin.Exec(ctx, `DELETE FROM hr_staff_recognition WHERE citation = $1`, citation) })
	save := func(token, path string, values map[string]string) *screensv1.SaveDrawerResponse {
		t.Helper()
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: path, Values: values}, token))
		if err != nil {
			t.Fatalf("saving %s: %v", path, err)
		}
		return answer.Msg
	}
	answer := save(hr, "/recognition/new", map[string]string{"staff_id": staff, "category": "teamwork", "citation": citation, "awarded_on": "2026-11-20"})
	if !answer.GetSaved() {
		t.Fatalf("recognition refused: %q", answer.GetError())
	}
	var n int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM hr_staff_recognition r JOIN audit_log a ON a.subject_id = r.id
WHERE r.citation = $1 AND r.staff_id = $2 AND a.action = 'hr.staff_recognised'`, citation, staff).Scan(&n); err != nil || n != 1 {
		t.Fatalf("recognition with its audit row: %d, %v", n, err)
	}
	if answer := save(hr, "/recognition/new", map[string]string{"staff_id": staff, "category": "kindness", "citation": "x"}); answer.GetError() != "Choose what the recognition is for." {
		t.Fatalf("an unknown category: %+v", answer)
	}
	if answer := save(hr, "/compliance-register/requirement", map[string]string{"country": "All", "name": "integration requirement"}); answer.GetError() != "Only an Admin sets a requirement for every country." {
		t.Fatalf("a requirement for every country: %+v", answer)
	}
	borrowAccount(t, "ia@edify.org")
	ia := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	if answer := save(ia, "/recognition/new", map[string]string{"staff_id": staff, "category": "values", "citation": "x"}); answer.GetError() != "Only HR may record this." {
		t.Fatalf("Impact Assessment recognising: %+v", answer)
	}
	borrowAccount(t, "cceo@edify.org")
	officer := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	if _, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: "/pulse-surveys/new"}, officer)); err == nil {
		t.Fatal("an officer opened the pulse survey form")
	} else if code := connect.CodeOf(err); code != connect.CodeUnavailable && code != connect.CodeNotFound {
		t.Fatalf("an officer's pulse survey form: %v", err)
	}
}
