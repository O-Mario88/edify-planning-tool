//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// Starting an impact report is Go's: Impact Assessment's drawer offers the
// report's fields; a draft without a title is refused in Django's words; a
// full one is saved as a draft in the officer's country; the Country
// Director reads that only IA writes reports; the Accountant is refused the
// page.
func TestImpactAssessmentStartsAReportInGo(t *testing.T) {
	ctx := context.Background()
	const title = "Go test impact report"
	clean := func() {
		_, _ = admin.Exec(ctx, `DELETE FROM impact_report WHERE title = $1`, title)
	}
	clean()
	t.Cleanup(clean)
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	const path = "/ia/impact-reports/new"
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	opened, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, token))
	if err != nil || opened.Msg.GetDrawer().GetTitle() != "Start an impact report" ||
		opened.Msg.GetDrawer().GetSubmitLabel() != "Save draft" {
		t.Fatalf("the drawer: %v %v", opened, err)
	}
	var fy string
	for _, item := range opened.Msg.GetDrawer().GetItems() {
		if item.GetField().GetName() == "fy" {
			fy = item.GetField().GetValue()
		}
	}
	save := func(values map[string]string) *screensv1.SaveDrawerResponse {
		t.Helper()
		answer, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: path, Values: values}, token))
		if err != nil {
			t.Fatalf("saving: %v", err)
		}
		return answer.Msg
	}
	if r := save(map[string]string{"fy": fy, "title": ""}); r.GetSaved() || r.GetError() != "Title is required." {
		t.Fatalf("no title: %+v", r)
	}
	if r := save(map[string]string{"fy": fy, "title": title, "programme_areas": "training", "methodology": "Method"}); !r.GetSaved() ||
		r.GetMessage() != "Draft saved. Add recommendations, then submit it for review." {
		t.Fatalf("the draft: %+v", r)
	}
	var status, country string
	var areas []string
	if err := admin.QueryRow(ctx, `SELECT status, country, programme_areas FROM impact_report WHERE title = $1`, title).
		Scan(&status, &country, &areas); err != nil || status != "draft" || country == "" || len(areas) != 1 {
		t.Fatalf("the stored draft: %q %q %v %v", status, country, areas, err)
	}
	borrowAccount(t, "cd@edify.org")
	cd := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, cd)); err != nil ||
		r.Msg.GetDrawer().GetCanSubmit() || r.Msg.GetDrawer().GetItems()[0].GetNote().GetText() != "Only Impact Assessment writes impact reports." {
		t.Fatalf("the Country Director: %v %v", r, err)
	}
	borrowAccount(t, "accountant@edify.org")
	acc := sessionOf(t, "accountant@edify.org", seededPassword).GetAccessToken()
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, acc)); err != nil ||
		r.Msg.GetRefusal() != "Access Denied: Your active role does not have permission to view Impact Reports." {
		t.Fatalf("the Accountant: %v %v", r, err)
	}
}
