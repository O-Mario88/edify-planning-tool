//go:build integration

package integration

import (
	"context"
	"net/http"
	"sort"
	"testing"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1/clustersv1connect"
	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
)

const roleClusterLeader = "ClusterLeader"

func clustersClient() clustersv1connect.ClusterLeadershipServiceClient {
	return clustersv1connect.NewClusterLeadershipServiceClient(http.DefaultClient, baseURL)
}

// leaderFixture turns one seeded account into a Cluster Leader for the test
// (the role an Admin gives on the Users page) and puts it back afterwards.
func leaderFixture(t *testing.T) string {
	t.Helper()
	ctx := context.Background()
	var userID string
	var roles []string
	var activeRole string
	if err := admin.QueryRow(ctx, `SELECT id, roles, active_role FROM "user"
WHERE email = 'partner@edify.org' AND deleted_at IS NULL`).Scan(&userID, &roles, &activeRole); err != nil {
		t.Fatalf("the test database needs the demo seed: %v", err)
	}
	if _, err := admin.Exec(ctx, `UPDATE "user" SET roles = $2, active_role = $3 WHERE id = $1`,
		userID, []string{roleClusterLeader}, roleClusterLeader); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		ctx := context.Background()
		_, _ = admin.Exec(ctx, `UPDATE "user" SET roles = $2, active_role = $3 WHERE id = $1`, userID, roles, activeRole)
		// Test database only: the gateway itself can never delete these.
		_, _ = admin.Exec(ctx, `DELETE FROM cluster_leadership.assignment_event WHERE assignment_id IN
  (SELECT id FROM cluster_leadership.leader_assignment WHERE user_id = $1)`, userID)
		_, _ = admin.Exec(ctx, `DELETE FROM cluster_leadership.leader_assignment WHERE user_id = $1`, userID)
	})
	return userID
}

// clusterWithSchools is a cluster with the most operating member schools,
// and another cluster to be refused.
func clusterWithSchools(t *testing.T) (string, string, []string) {
	t.Helper()
	ctx := context.Background()
	var mine, other string
	if err := admin.QueryRow(ctx, `
SELECT c.id FROM cluster c JOIN school s ON s.cluster_id = c.id
  AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
WHERE c.deleted_at IS NULL GROUP BY c.id ORDER BY count(*) DESC, c.id LIMIT 1`).Scan(&mine); err != nil {
		t.Fatalf("the test database has no cluster with schools: %v", err)
	}
	if err := admin.QueryRow(ctx, `SELECT id FROM cluster WHERE deleted_at IS NULL AND id <> $1 ORDER BY id LIMIT 1`,
		mine).Scan(&other); err != nil {
		t.Fatal(err)
	}
	// The members written independently of the gateway's query.
	rows, err := admin.Query(ctx, `SELECT school_id FROM school
WHERE cluster_id = $1 AND deleted_at IS NULL AND operational_status IN ('active', 'reopened')`, mine)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var members []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			t.Fatal(err)
		}
		members = append(members, id)
	}
	sort.Strings(members)
	return mine, other, members
}

func adminAccount(t *testing.T) string {
	t.Helper()
	var id string
	if err := admin.QueryRow(context.Background(), `SELECT id FROM "user"
WHERE email = 'admin@edify.org' AND deleted_at IS NULL`).Scan(&id); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestClusterLeaderSeesOnlyTheirAssignedClusterAndItsSchools(t *testing.T) {
	ctx := context.Background()
	leaderID := leaderFixture(t)
	mine, other, members := clusterWithSchools(t)
	adminBearer := token(t, adminAccount(t), "Admin", time.Hour)
	leaderBearer := token(t, leaderID, roleClusterLeader, time.Hour)
	client := clustersClient()

	assigned, err := client.AssignLeader(ctx, authed(&clustersv1.AssignLeaderRequest{
		ClusterId: mine, UserId: leaderID, Reason: "integration test",
	}, adminBearer))
	if err != nil {
		t.Fatalf("an Admin assigns a Cluster Leader: %v", err)
	}
	if got := assigned.Msg.GetAssignment(); got.GetStatus() != "active" || len(got.GetHistory()) != 1 {
		t.Fatalf("the assignment and its first event: %v", got)
	}

	clusters, err := client.GetMyClusters(ctx, authed(&clustersv1.GetMyClustersRequest{}, leaderBearer))
	if err != nil || len(clusters.Msg.GetClusters()) != 1 || clusters.Msg.GetClusters()[0].GetId() != mine {
		t.Fatalf("the leader's clusters: %v %v", clusters, err)
	}
	if got := clusters.Msg.GetClusters()[0].GetMemberSchoolCount(); int(got) != len(members) {
		t.Fatalf("member schools: gateway %d, database %d", got, len(members))
	}

	managed, err := client.ListManagedClusters(ctx, authed(&clustersv1.ListManagedClustersRequest{
		Search: clusters.Msg.GetClusters()[0].GetName(),
	}, adminBearer))
	if err != nil {
		t.Fatal(err)
	}
	var liveLeaders []string
	for _, m := range managed.Msg.GetClusters() {
		if m.GetCluster().GetId() == mine {
			liveLeaders = m.GetLiveLeaders()
		}
	}
	if len(liveLeaders) != 1 || liveLeaders[0] != assigned.Msg.GetAssignment().GetLeaderName() {
		t.Fatalf("the managed cluster names its live leader: %v", liveLeaders)
	}

	listed, err := client.ListMemberSchools(ctx, authed(&clustersv1.ListMemberSchoolsRequest{
		ClusterId: mine, Page: &commonv1.PageRequest{PageSize: 200},
	}, leaderBearer))
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, school := range listed.Msg.GetSchools() {
		got = append(got, school.GetSchoolId())
	}
	sort.Strings(got)
	if len(got) != len(members) {
		t.Fatalf("members: gateway %v, database %v", got, members)
	}
	for i := range got {
		if got[i] != members[i] {
			t.Fatalf("members: gateway %v, database %v", got, members)
		}
	}

	if _, err := client.GetClusterHome(ctx, authed(&clustersv1.GetClusterHomeRequest{ClusterId: mine}, leaderBearer)); err != nil {
		t.Fatalf("the leader's Home: %v", err)
	}
	_, err = client.ListMemberSchools(ctx, authed(&clustersv1.ListMemberSchoolsRequest{ClusterId: other}, leaderBearer))
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("another cluster must be refused, got %v", err)
	}

	ended, err := client.EndAssignment(ctx, authed(&clustersv1.EndAssignmentRequest{
		AssignmentId: assigned.Msg.GetAssignment().GetId(), Reason: "integration test ends",
	}, adminBearer))
	if err != nil {
		t.Fatal(err)
	}
	if ended.Msg.GetAssignment().GetStatus() != "ended" || len(ended.Msg.GetAssignment().GetHistory()) != 2 {
		t.Fatalf("an ended assignment keeps its history: %v", ended.Msg.GetAssignment())
	}
	_, err = client.GetClusterHome(ctx, authed(&clustersv1.GetClusterHomeRequest{ClusterId: mine}, leaderBearer))
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("an ended assignment gives no access, got %v", err)
	}
	leaders, err := client.ListLeaders(ctx, authed(&clustersv1.ListLeadersRequest{ClusterId: mine}, adminBearer))
	if err != nil || len(leaders.Msg.GetAssignments()) != 1 || leaders.Msg.GetAssignments()[0].GetStatus() != "ended" {
		t.Fatalf("the ended assignment is kept as history: %v %v", leaders, err)
	}
}
