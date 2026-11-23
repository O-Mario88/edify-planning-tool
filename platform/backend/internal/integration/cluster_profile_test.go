//go:build integration

package integration

import (
	"context"
	"errors"
	"testing"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func stripOf(page *screensv1.GetPageResponse, title string) *screensv1.PageStrip {
	for _, block := range page.GetBlocks() {
		if s := block.GetStrip(); s != nil && s.GetTitle() == title {
			return s
		}
	}
	return nil
}

func metricOf(s *screensv1.PageStrip, label string) *screensv1.PageMetric {
	for _, m := range s.GetMetrics() {
		if m.GetLabel() == label {
			return m
		}
	}
	return nil
}

// A cluster is read only by someone whose scope holds it; anyone else is told
// it does not exist, exactly as the existing page's _scoped_cluster does.
func TestTheClusterProfileIsOnlyForReadersWhoseScopeHoldsIt(t *testing.T) {
	ctx := context.Background()
	var clusterID string
	if err := admin.QueryRow(ctx, `
SELECT c.id FROM cluster c JOIN staff_profile sp ON sp.id = c.responsible_staff_id JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo@edify.org' AND c.deleted_at IS NULL AND c.status = 'active' ORDER BY c.id LIMIT 1`).Scan(&clusterID); err != nil {
		t.Skip("the seeded officer owns no cluster")
	}
	borrowAccount(t, "cceo@edify.org")
	owner := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(owner, "/clusters/"+clusterID, nil)
	if err != nil {
		t.Fatalf("the owner opens the cluster: %v", err)
	}
	if got := len(page.GetTabs()); got != 7 {
		t.Fatalf("%d tabs, want 7", got)
	}
	if stripOf(page, "Cluster Summary") == nil {
		t.Fatal("the page has no Cluster Summary")
	}

	borrowAccount(t, "cceo1@edify.org")
	outsider := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	_, err = pageOf(outsider, "/clusters/"+clusterID, nil)
	var refused *connect.Error
	if !errors.As(err, &refused) || refused.Code() != connect.CodeNotFound {
		t.Fatalf("an officer outside the cluster got %v, want not found", err)
	}
}

// A cluster whose schools have no confirmed SSA reads Not Assessed: no school
// is averaged in as a zero.
func TestAClusterWithNoSSAReadsNotAssessedNotZero(t *testing.T) {
	ctx := context.Background()
	var staffID string
	if err := admin.QueryRow(ctx, `
SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'cceo@edify.org'`).Scan(&staffID); err != nil {
		t.Skip("the seeded officer has no staff profile")
	}
	id := "qaclusternossa"
	now := time.Now()
	if _, err := admin.Exec(ctx, `
INSERT INTO cluster (id, name, cluster_type, status, district_id, region_id, responsible_staff_id, created_at, updated_at, environment, source)
SELECT $1, 'QA Cluster With No SSA', c.cluster_type, 'active', c.district_id, c.region_id, $2, $3, $3, c.environment, c.source
FROM cluster c WHERE c.deleted_at IS NULL ORDER BY c.id LIMIT 1`, id, staffID, now); err != nil {
		t.Fatalf("creating the cluster: %v", err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM cluster WHERE id = $1`, id); err != nil {
			t.Errorf("removing the cluster: %v", err)
		}
	})
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/clusters/"+id, nil)
	if err != nil {
		t.Fatal(err)
	}
	score := metricOf(stripOf(page, "Cluster Summary"), "Cluster SSA Score")
	if score == nil || score.GetValue() != "Not Assessed" {
		t.Fatalf("Cluster SSA Score = %v, want Not Assessed", score)
	}
	for _, block := range page.GetBlocks() {
		rail := block.GetRail()
		if rail == nil {
			continue
		}
		for _, meter := range rail.GetParts()[0].GetMeters() {
			if meter.GetValue() != "Not Assessed" || meter.GetFraction() != 0 {
				t.Fatalf("%s reads %q", meter.GetLabel(), meter.GetValue())
			}
		}
	}
}
