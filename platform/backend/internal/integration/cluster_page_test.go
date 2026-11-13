//go:build integration

package integration

import (
	"context"
	"fmt"
	"net/http"
	"slices"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

func pageOf(token, path string, query map[string]string) (*screensv1.GetPageResponse, error) {
	answer, err := screensv1connect.NewPageScreenServiceClient(http.DefaultClient, baseURL).GetPage(context.Background(),
		authed(&screensv1.GetPageRequest{Path: path, Query: query}, token))
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func recordsOf(page *screensv1.GetPageResponse) []*screensv1.PageRecord {
	out := []*screensv1.PageRecord{}
	for _, block := range page.GetBlocks() {
		if r := block.GetRecord(); r != nil {
			out = append(out, r)
		}
	}
	return out
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTheClustersPageListsTheOfficersOwnClusters(t *testing.T) {
	var owned int
	if err := admin.QueryRow(context.Background(), `
SELECT count(*) FROM cluster c JOIN staff_profile sp ON sp.id = c.responsible_staff_id JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo@edify.org' AND c.deleted_at IS NULL AND c.status = 'active'`).Scan(&owned); err != nil || owned == 0 {
		t.Skip("the seeded officer owns no cluster")
	}
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/clusters", nil)
	if err != nil {
		t.Fatal(err)
	}
	// The header band as the feed reads it (page-header-actions, proved by
	// parity): Create Cluster, the two scheduling drawers, then Export.
	if page.GetHeader().GetTitle() != "Clusters" || !slices.Equal(headerActionKeys(page),
		[]string{"create_cluster", "schedule_group_training", "schedule_cluster_meeting", "export"}) {
		t.Fatalf("the header: %v", page.GetHeader())
	}
	if total := page.GetBlocks()[1].GetStrip().GetMetrics()[0].GetValue(); total != fmt.Sprint(owned) {
		t.Fatalf("Total Clusters %s, want %d", total, owned)
	}
	if got := len(recordsOf(page)); got != min(owned, 5) {
		t.Fatalf("%d cards on the first page, want %d", got, min(owned, 5))
	}
	healthy, err := pageOf(token, "/clusters", map[string]string{"cluster_risk": "healthy"})
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range recordsOf(healthy) {
		if r.GetBadges()[0].GetText() != "Healthy" {
			t.Fatalf("the risk filter kept %s (%s)", r.GetTitle(), r.GetBadges()[0].GetText())
		}
	}
}

func TestAnOfficerWithNoClustersIsOfferedToCreateOne(t *testing.T) {
	borrowAccount(t, "cceo1@edify.org")
	token := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/clusters", nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(recordsOf(page)) != 0 {
		t.Skip("the seeded officer owns clusters")
	}
	links := page.GetBlocks()[2].GetPanel().GetItems()[2].GetLinks().GetLinks()
	if len(links) != 2 || links[0].GetText() != "Create Cluster" || !links[0].GetDrawer() {
		t.Fatalf("the empty list: %v", page.GetBlocks()[2])
	}
}

func TestARoleOutsideThePageIsTurnedAway(t *testing.T) {
	borrowAccount(t, "coordinator@edify.org")
	token := sessionOf(t, "coordinator@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/clusters", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Project Coordinator opening Clusters: %v, want not found", err)
	}
}

func TestAClusterCardsSchoolsAreReadThroughGo(t *testing.T) {
	var clusterID string
	var schools int
	if err := admin.QueryRow(context.Background(), `
SELECT c.id, (SELECT count(*) FROM school s WHERE s.cluster_id = c.id AND s.deleted_at IS NULL
  AND s.operational_status IN ('active', 'reopened') AND s.school_type IS DISTINCT FROM 'champion')
FROM cluster c JOIN staff_profile sp ON sp.id = c.responsible_staff_id JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo@edify.org' AND c.deleted_at IS NULL ORDER BY c.name LIMIT 1`).Scan(&clusterID, &schools); err != nil {
		t.Skip("the seeded officer owns no cluster")
	}
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/partials/clusters/"+clusterID+"/schools", nil)
	if err != nil {
		t.Fatal(err)
	}
	if want := fmt.Sprintf("Schools in Cluster (%d)", schools); page.GetBlocks()[0].GetPanel().GetItems()[0].GetHeading() != want {
		t.Fatalf("heading %v, want %s", page.GetBlocks()[0], want)
	}
	if schools > 0 {
		table := page.GetBlocks()[1].GetTable()
		if len(table.GetRows()) != schools || page.GetSelection() == nil {
			t.Fatalf("%d rows for %d schools, selection %v", len(table.GetRows()), schools, page.GetSelection())
		}
	}

	borrowAccount(t, "cceo1@edify.org")
	other := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(other, "/partials/clusters/"+clusterID+"/schools", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("another officer opening it: %v, want not found", err)
	}
}

// headerActionKeys are the page header's action keys, in order.
func headerActionKeys(page *screensv1.GetPageResponse) []string {
	keys := []string{}
	for _, a := range page.GetHeader().GetActions() {
		keys = append(keys, a.GetKey())
	}
	return keys
}
