//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// Starting an impact report, editing the draft, adding a recommendation and
// reading its page are Go's: Impact Assessment's drawer offers the report's
// fields; a draft without a title is refused in Django's words; a full one
// is saved as a draft in the officer's country, edited, given a
// recommendation, and its page shows both; the Country Director reads that
// only IA writes reports and cannot edit; the Accountant is refused the page.
func TestImpactAssessmentStartsAReportInGo(t *testing.T) {
	ctx := context.Background()
	const title = "Go test impact report"
	clean := func() {
		_, _ = admin.Exec(ctx, `DELETE FROM impact_report_recommendation WHERE report_id IN (SELECT id FROM impact_report WHERE title = $1)`, title)
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
	var id string
	if err := admin.QueryRow(ctx, `SELECT id FROM impact_report WHERE title = $1`, title).Scan(&id); err != nil {
		t.Fatalf("the draft's id: %v", err)
	}
	editPath := "/ia/impact-reports/" + id + "/edit"
	edited, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: editPath, Values: map[string]string{
		"fy": fy, "title": title, "programme_areas": "training", "methodology": "Method", "findings": "Found"}}, token))
	if err != nil || !edited.Msg.GetSaved() || edited.Msg.GetMessage() != "Draft saved." {
		t.Fatalf("the edit: %v %v", edited, err)
	}
	recPath := "/ia/impact-reports/" + id + "/recommendations/new"
	if r, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: recPath, Values: map[string]string{
		"text": "Train more leaders", "owner_role": "Nobody", "due_date": "2027-02-01"}}, token)); err != nil ||
		r.Msg.GetError() != "Say who should act on the recommendation." {
		t.Fatalf("an unknown owner: %v %v", r, err)
	}
	if r, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: recPath, Values: map[string]string{
		"text": "Train more leaders", "owner_role": "Program Lead", "due_date": "2027-02-01"}}, token)); err != nil ||
		r.Msg.GetMessage() != "Recommendation added." {
		t.Fatalf("the recommendation: %v %v", r, err)
	}
	pages := screensv1connect.NewPageScreenServiceClient(http.DefaultClient, baseURL)
	page, err := pages.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/ia/impact-reports/" + id + "/"}, token))
	if err != nil || page.Msg.GetHeader().GetTitle() != title || len(page.Msg.GetHeader().GetActions()) != 3 {
		t.Fatalf("the report's page: %v %v", page, err)
	}
	var recommended, historyRows bool
	for _, b := range page.Msg.GetBlocks() {
		for _, row := range b.GetTable().GetRows() {
			cells := row.GetCells()
			recommended = recommended || (len(cells) > 1 && cells[0].GetText() == "Train more leaders" && cells[1].GetText() == "Programme Lead")
			historyRows = historyRows || (len(cells) > 1 && cells[1].GetText() == "Draft edited")
		}
	}
	if !recommended || !historyRows {
		t.Fatalf("the page lacks the recommendation (%v) or the edit in its history (%v)", recommended, historyRows)
	}
	pagePath := "/ia/impact-reports/" + id + "/"
	if r, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: pagePath, Form: "submit_for_review"}, token)); err != nil ||
		r.Msg.GetError() != "State the limitations: what this evidence cannot show before submitting." {
		t.Fatalf("submitting without limitations: %v %v", r, err)
	}
	if r, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: editPath, Values: map[string]string{
		"fy": fy, "title": title, "programme_areas": "training", "methodology": "Method", "findings": "Found", "limitations": "Limits"}}, token)); err != nil ||
		!r.Msg.GetSaved() {
		t.Fatalf("adding the limitations: %v %v", r, err)
	}
	if r, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: pagePath, Form: "submit_for_review"}, token)); err != nil ||
		r.Msg.GetMessage() != "Submitted. The evidence is frozen and a second reviewer has been told." {
		t.Fatalf("submitting: %v %v", r, err)
	}
	var submitted, hash string
	var frozen bool
	if err := admin.QueryRow(ctx, `SELECT status, snapshot_hash, evidence_snapshot ? 'cohort' FROM impact_report WHERE id = $1`, id).
		Scan(&submitted, &hash, &frozen); err != nil || submitted != "submitted" || len(hash) != 64 || !frozen {
		t.Fatalf("the submitted report: %q %q %v %v", submitted, hash, frozen, err)
	}
	borrowAccount(t, "cd@edify.org")
	cd := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	reviewPath := "/ia/impact-reports/" + id + "/review"
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: reviewPath}, token)); err != nil ||
		r.Msg.GetDrawer().GetCanSubmit() {
		t.Fatalf("the author's review drawer: %v %v", r, err)
	}
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: reviewPath}, cd)); err != nil ||
		!r.Msg.GetDrawer().GetCanSubmit() || r.Msg.GetDrawer().GetSubmitLabel() != "Save decision" {
		t.Fatalf("the Country Director's review drawer: %v %v", r, err)
	}
	if r, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: reviewPath, Values: map[string]string{
		"decision": "return"}}, cd)); err != nil || r.Msg.GetError() != "Say what the author needs to change." {
		t.Fatalf("returning without a note: %v %v", r, err)
	}
	if r, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: reviewPath, Values: map[string]string{
		"decision": "return", "note": "Tighten the findings"}}, cd)); err != nil || r.Msg.GetMessage() != "Report returned to its author." {
		t.Fatalf("returning: %v %v", r, err)
	}
	returned, err := pages.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: pagePath}, token))
	if err != nil || returned.Msg.GetHeader().GetDescription() != "Returned · version 1 · "+country {
		t.Fatalf("the returned report's page: %v %v", returned, err)
	}
	if r := save(map[string]string{"fy": fy, "title": title, "programme_areas": "visits"}); !r.GetSaved() {
		t.Fatalf("a second draft: %+v", r)
	}
	var second string
	if err := admin.QueryRow(ctx, `SELECT id FROM impact_report WHERE title = $1 AND status = 'draft'`, title).Scan(&second); err != nil {
		t.Fatalf("the second draft: %v", err)
	}
	if r, err := drawers.SaveDrawer(ctx, authed(&screensv1.SaveDrawerRequest{Path: "/ia/impact-reports/" + second + "/", Form: "withdraw"}, token)); err != nil ||
		r.Msg.GetMessage() != "Report withdrawn." {
		t.Fatalf("withdrawing the second draft: %v %v", r, err)
	}
	if r, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: editPath}, cd)); err != nil || r.Msg.GetDrawer().GetCanSubmit() {
		t.Fatalf("the Country Director's edit drawer: %v %v", r, err)
	}
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
