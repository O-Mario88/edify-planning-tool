package clusterlead

import (
	"context"
	"testing"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
)

// fakeOnboarder stands in for the existing application's onboarding
// endpoint: it records each call and answers with a pending leader account.
type fakeOnboarder struct {
	calls    int
	existing bool
	token    string
	err      error
}

func (f *fakeOnboarder) Onboard(_ context.Context, clusterID string, in OnboardInput) (Onboarded, error) {
	f.calls++
	if f.err != nil {
		return Onboarded{}, f.err
	}
	return Onboarded{UserID: "u-new", Existing: f.existing, InviteToken: f.token}, nil
}

func onboardingService(f *fakeData, o *fakeOnboarder) *Service {
	f.accounts["u-new"] = Account{UserID: "u-new", Name: "Grace Nakato", IsLeader: true}
	return service(f).WithOnboarder(o, "https://edify.test")
}

func TestOnboardingAppliesTheClusterPolicyBeforeTheAccountIsMade(t *testing.T) {
	o := &fakeOnboarder{}
	svc := onboardingService(newFake(), o)
	request := func(cluster string) *connect.Request[clustersv1.OnboardLeaderRequest] {
		return connect.NewRequest(&clustersv1.OnboardLeaderRequest{ClusterId: cluster, Name: "Grace Nakato", Email: "grace@school.test"})
	}
	if _, err := svc.OnboardLeader(as(roleCCEO, "u-cceo", "sp-cceo"), request("c-other")); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("another CCEO's cluster, got %v", err)
	}
	if _, err := svc.OnboardLeader(as(RoleClusterLeader, "u-leader", ""), request("c-mine")); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("a Cluster Leader onboards nobody, got %v", err)
	}
	if o.calls != 0 {
		t.Fatalf("the existing application was asked %d times for refused requests", o.calls)
	}
	got, err := svc.OnboardLeader(as(roleCCEO, "u-cceo", "sp-cceo"), request("c-mine"))
	if err != nil {
		t.Fatal(err)
	}
	if a := got.Msg.GetAssignment(); a.GetUserId() != "u-new" || a.GetClusterId() != "c-mine" || a.GetStatus() != "active" {
		t.Fatalf("the new leader leads the cluster: %v", a)
	}
	again, err := svc.OnboardLeader(as(roleCCEO, "u-cceo", "sp-cceo"), request("c-mine"))
	if err != nil || !again.Msg.GetAlreadyLeading() {
		t.Fatalf("onboarding twice changes nothing: %v %v", again, err)
	}
}

func TestOnboardingHandsBackTheInvitationOnlyWhenEmailCannotReachTheLeader(t *testing.T) {
	o := &fakeOnboarder{token: "tok123"}
	got, err := onboardingService(newFake(), o).OnboardLeader(as(roleAdmin, "u-admin", ""),
		connect.NewRequest(&clustersv1.OnboardLeaderRequest{ClusterId: "c-other", Name: "Grace", Email: "grace@school.test"}))
	if err != nil {
		t.Fatal(err)
	}
	if got.Msg.GetInviteLink() != "https://edify.test/set-password?token=tok123" {
		t.Fatalf("invite link %q", got.Msg.GetInviteLink())
	}
	o.token = ""
	got, _ = onboardingService(newFake(), o).OnboardLeader(as(roleAdmin, "u-admin", ""),
		connect.NewRequest(&clustersv1.OnboardLeaderRequest{ClusterId: "c-other", Name: "Grace", Email: "grace@school.test"}))
	if got.Msg.GetInviteLink() != "" {
		t.Fatal("an invitation link was shown although email reaches the leader")
	}
}

func TestOnboardingSaysSoWhenTheExistingApplicationIsUnreachable(t *testing.T) {
	_, err := service(newFake()).OnboardLeader(as(roleAdmin, "u-admin", ""),
		connect.NewRequest(&clustersv1.OnboardLeaderRequest{ClusterId: "c-mine", Name: "Grace", Email: "grace@school.test"}))
	if codeOf(err) != connect.CodeUnavailable {
		t.Fatalf("no onboarding endpoint configured, got %v", err)
	}
}
