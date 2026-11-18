//go:build integration

package integration

import (
	"context"
	"slices"
	"testing"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// The country through clusters (docs/migration/80-multi-country-phase-0.md
// §16). With Kenya Active, a Kenyan region and a cluster in it, and an
// officer who works in Kenya alone as Programme Lead: a cluster's country is
// read through the registry; the Cluster Leader portal offers a Programme
// Lead only their own country's clusters and refuses to let them manage
// another country's, while Uganda's Programme Lead keeps every Ugandan
// cluster and an Admin every cluster. Every row the test files starts
// "gccl".
func TestTheCountryThroughClusters(t *testing.T) {
	ctx := context.Background()
	_, officer, exec := twoKenyans(t, "gccl")
	exec(`INSERT INTO country_registry.country_role_assignment (id, membership_id, country_id, user_id, role_name, scope_type, granted_by, grant_reason)
SELECT gen_random_uuid(), m.id, m.country_id, m.user_id, 'Program Lead', 'portfolio', 'gccl', 'Country test'
FROM country_registry.country_membership m WHERE m.user_id = $1 AND m.granted_by = 'gccl'`, officer.user)

	var baseRegion, baseDistrict, baseCluster, ugandanCluster, ugandanLead, adminID string
	if err := admin.QueryRow(ctx, `SELECT (SELECT id FROM region ORDER BY id LIMIT 1), (SELECT id FROM district ORDER BY id LIMIT 1),
  (SELECT id FROM cluster WHERE deleted_at IS NULL ORDER BY id LIMIT 1),
  (SELECT id FROM cluster WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1),
  (SELECT id FROM "user" WHERE active_role = 'Program Lead' AND is_active AND deleted_at IS NULL ORDER BY email LIMIT 1),
  (SELECT id FROM "user" WHERE email = 'admin@edify.org')`).Scan(&baseRegion, &baseDistrict, &baseCluster, &ugandanCluster, &ugandanLead, &adminID); err != nil {
		t.Fatalf("a region, clusters and leads to work with: %v", err)
	}
	exec(`INSERT INTO region SELECT (json_populate_record(NULL::region, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcclRG', 'name', 'Gccl Nairobi', 'country', 'Kenya'))::json)).* FROM region t WHERE id = $1`, baseRegion)
	exec(`INSERT INTO district SELECT (json_populate_record(NULL::district, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcclDT', 'name', 'Gccl Westlands', 'region_id', 'gcclRG'))::json)).* FROM district t WHERE id = $1`, baseDistrict)
	exec(`INSERT INTO cluster SELECT (json_populate_record(NULL::cluster, (row_to_json(t)::jsonb || jsonb_build_object(
  'id', 'gcclKE', 'name', 'Gccl Kenyan Cluster', 'region_id', 'gcclRG', 'district_id', 'gcclDT', 'sub_county_id', NULL,
  'responsible_staff_id', NULL, 'facilitating_partner_id', NULL))::json)).* FROM cluster t WHERE id = $1`, baseCluster)

	// The cluster's country, read through the registry.
	in := func(code string) []string {
		t.Helper()
		rows, err := admin.Query(ctx, `SELECT c.id FROM cluster c WHERE c.deleted_at IS NULL AND `+country.ClusterIn("c", "$1")+` ORDER BY c.id`,
			[]string{countryID(t, code)})
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		out := []string{}
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				t.Fatal(err)
			}
			out = append(out, id)
		}
		return out
	}
	if got := in("KE"); !slices.Equal(got, []string{"gcclKE"}) {
		t.Errorf("Kenya's clusters %v", got)
	}
	if got := in("UG"); slices.Contains(got, "gcclKE") || !slices.Contains(got, ugandanCluster) {
		t.Errorf("Uganda's clusters %v", got)
	}

	// The Cluster Leader portal.
	client := clustersClient()
	managed := func(user, role string) ([]string, error) {
		got, err := client.ListManagedClusters(ctx, authed(&clustersv1.ListManagedClustersRequest{
			Page: &commonv1.PageRequest{Page: 1, PageSize: 100}}, token(t, user, role, time.Hour)))
		if err != nil {
			return nil, err
		}
		out := []string{}
		for _, c := range got.Msg.GetClusters() {
			out = append(out, c.GetCluster().GetId())
		}
		return out, nil
	}
	kenyan, err := managed(officer.user, "Program Lead")
	if err != nil || !slices.Equal(kenyan, []string{"gcclKE"}) {
		t.Errorf("Kenya's Programme Lead manages %v (%v), want Kenya's cluster alone", kenyan, err)
	}
	ugandan, err := managed(ugandanLead, "Program Lead")
	if err != nil || slices.Contains(ugandan, "gcclKE") || !slices.Contains(ugandan, ugandanCluster) {
		t.Errorf("Uganda's Programme Lead manages %v (%v)", ugandan, err)
	}
	everything, err := managed(adminID, "Admin")
	if err != nil || !slices.Contains(everything, "gcclKE") || !slices.Contains(everything, ugandanCluster) {
		t.Errorf("the Admin manages %v (%v), want every country's clusters", everything, err)
	}
	leaders := func(user, cluster string) error {
		_, err := client.ListLeaders(ctx, authed(&clustersv1.ListLeadersRequest{ClusterId: cluster}, token(t, user, "Program Lead", time.Hour)))
		return err
	}
	if err := leaders(officer.user, ugandanCluster); connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("Kenya's Programme Lead managing a Ugandan cluster's leaders: %v", err)
	}
	if err := leaders(officer.user, "gcclKE"); err != nil {
		t.Errorf("Kenya's Programme Lead managing Kenya's cluster: %v", err)
	}
	if err := leaders(ugandanLead, "gcclKE"); connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("Uganda's Programme Lead managing a Kenyan cluster's leaders: %v", err)
	}
}
