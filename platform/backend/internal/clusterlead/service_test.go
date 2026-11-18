package clusterlead

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"slices"
	"testing"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// fakeData is an in-memory Data: clusters, accounts and assignments.
type fakeData struct {
	clusters    map[string]Cluster
	accounts    map[string]Account
	assignments []Assignment
	members     map[string][]School
	upcoming    map[string][]Activity
}

func newFake() *fakeData {
	return &fakeData{
		clusters: map[string]Cluster{
			"c-mine":  {ID: "c-mine", Name: "Cluster A", ResponsibleStaffID: "sp-cceo", CountryIDs: []string{"ug"}},
			"c-other": {ID: "c-other", Name: "Cluster B", ResponsibleStaffID: "sp-someone-else", CountryIDs: []string{"ug"}},
			"c-kenya": {ID: "c-kenya", Name: "Cluster K", ResponsibleStaffID: "sp-someone-else", CountryIDs: []string{"ke"}},
		},
		accounts: map[string]Account{
			"u-leader":  {UserID: "u-leader", Name: "Grace", IsLeader: true},
			"u-leader2": {UserID: "u-leader2", Name: "Moses", IsLeader: true},
			"u-staff":   {UserID: "u-staff", Name: "Paul", IsLeader: false},
		},
		members: map[string][]School{
			"c-mine": {
				{ID: "s1", SchoolID: "1001", Name: "Kasawo Primary", District: "Mukono"},
				// Cross-district: a member school is eligible wherever it is.
				{ID: "s2", SchoolID: "1002", Name: "Nakifuma Primary", District: "Kayunga"},
			},
		},
		upcoming: map[string][]Activity{},
	}
}

func (f *fakeData) LiveAssignments(_ context.Context, userID string, day time.Time) ([]Assignment, error) {
	var live []Assignment
	for _, a := range f.assignments {
		if a.UserID == userID && a.Status == "active" && !a.StartsOn.After(day) && (a.EndsOn == nil || !a.EndsOn.Before(day)) {
			live = append(live, a)
		}
	}
	return live, nil
}

func (f *fakeData) Cluster(_ context.Context, id string) (Cluster, error) {
	c, ok := f.clusters[id]
	if !ok {
		return Cluster{}, ErrNotFound
	}
	return c, nil
}

func (f *fakeData) MemberSchools(_ context.Context, id, _ string, limit, offset int) ([]School, int64, error) {
	all := f.members[id]
	if offset > len(all) {
		offset = len(all)
	}
	end := min(offset+limit, len(all))
	return all[offset:end], int64(len(all)), nil
}

func (f *fakeData) UpcomingActivities(_ context.Context, id string, _ time.Time, _ int) ([]Activity, error) {
	return f.upcoming[id], nil
}

func (f *fakeData) PastActivities(context.Context, string, time.Time, int) ([]Activity, error) {
	return nil, nil
}

func (f *fakeData) ManagedClusters(_ context.Context, ownerIDs, countryIDs []string, _ string, _ time.Time, _, _ int) ([]ManagedCluster, int64, error) {
	var out []ManagedCluster
	for _, id := range []string{"c-kenya", "c-mine", "c-other"} {
		c := f.clusters[id]
		inCountry := countryIDs == nil || slices.ContainsFunc(c.CountryIDs, func(id string) bool { return slices.Contains(countryIDs, id) })
		if (ownerIDs == nil || slices.Contains(ownerIDs, c.ResponsibleStaffID)) && inCountry {
			out = append(out, ManagedCluster{Cluster: c, Members: int64(len(f.members[id]))})
		}
	}
	return out, int64(len(out)), nil
}

func (f *fakeData) OperationsOf(context.Context, string, string, time.Time) (Operations, error) {
	return Operations{Confirmed: map[string]int32{"act1": 2}, Unanswered: 3}, nil
}

func (f *fakeData) ClusterAssignments(_ context.Context, id string) ([]Assignment, error) {
	var out []Assignment
	for _, a := range f.assignments {
		if a.ClusterID == id {
			out = append(out, a)
		}
	}
	return out, nil
}

func (f *fakeData) Assignment(_ context.Context, id string) (Assignment, error) {
	for _, a := range f.assignments {
		if a.ID == id {
			return a, nil
		}
	}
	return Assignment{}, ErrNotFound
}

func (f *fakeData) Candidates(context.Context) ([]Account, error) {
	var out []Account
	for _, a := range f.accounts {
		if a.IsLeader {
			out = append(out, a)
		}
	}
	return out, nil
}

func (f *fakeData) Account(_ context.Context, id string) (Account, error) {
	a, ok := f.accounts[id]
	if !ok {
		return Account{}, ErrNotFound
	}
	return a, nil
}

func (f *fakeData) InvitedLeader(_ context.Context, id string) (Account, error) {
	a, ok := f.accounts[id]
	if !ok || !a.IsLeader {
		return Account{}, ErrNotFound
	}
	return a, nil
}

func (f *fakeData) CreateAssignment(_ context.Context, n NewAssignment) error {
	for _, a := range f.assignments {
		if a.ClusterID == n.ClusterID && a.UserID == n.UserID && a.Status != "ended" {
			return ErrAlreadyAssigned
		}
	}
	f.assignments = append(f.assignments, Assignment{
		ID: n.ID, ClusterID: n.ClusterID, UserID: n.UserID, StartsOn: n.StartsOn, EndsOn: n.EndsOn,
		Status: "active", Reason: n.Reason, ReplacesID: n.ReplacesID,
		History: []Event{{Event: "assigned", Actor: n.ActorID, Reason: n.Reason}},
	})
	return nil
}

func (f *fakeData) EndAssignment(_ context.Context, id, actor, reason string, day time.Time) error {
	return f.end(id, actor, reason, "ended", day)
}

func (f *fakeData) end(id, actor, reason, event string, day time.Time) error {
	for i, a := range f.assignments {
		if a.ID == id {
			if a.Status == "ended" {
				return ErrNotLive
			}
			f.assignments[i].Status = "ended"
			f.assignments[i].EndsOn = &day
			f.assignments[i].EndedReason = reason
			f.assignments[i].History = append(a.History, Event{Event: event, Actor: actor, Reason: reason})
			return nil
		}
	}
	return ErrNotLive
}

func (f *fakeData) ReplaceAssignment(ctx context.Context, id string, next NewAssignment, day time.Time) error {
	if err := f.end(id, next.ActorID, next.Reason, "replaced", day); err != nil {
		return err
	}
	next.ReplacesID = id
	return f.CreateAssignment(ctx, next)
}

var day = time.Date(2026, 11, 10, 0, 0, 0, 0, time.UTC)

func live(id, cluster, user string, starts time.Time, ends *time.Time, status string) Assignment {
	return Assignment{ID: id, ClusterID: cluster, UserID: user, StartsOn: starts, EndsOn: ends, Status: status}
}

func service(data Data) *Service {
	// 10:00 in Kampala on 10 November 2026.
	now := func() time.Time { return time.Date(2026, 11, 10, 7, 0, 0, 0, time.UTC) }
	return NewService(data, now, nil, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

func as(role, userID, staffProfile string) context.Context {
	return auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{
		UserID: userID, ActiveRole: role, Roles: []string{role}, Status: "active", StaffProfileID: staffProfile,
	}})
}

// inUganda is ctx's caller working in Uganda (docs/migration/80, §16).
func inUganda(ctx context.Context) context.Context {
	p, _ := auth.PrincipalFrom(ctx)
	p.Country = &country.Work{Country: country.Country{ID: "ug", Code: "UG", Name: "Uganda"}, RolesSource: country.RolesFromProfile}
	return auth.WithPrincipal(context.Background(), p)
}

func codeOf(err error) connect.Code {
	var connectErr *connect.Error
	if errors.As(err, &connectErr) {
		return connectErr.Code()
	}
	return connect.CodeUnknown
}

func TestALeaderReachesOnlyTheClustersAssignedToThem(t *testing.T) {
	data := newFake()
	data.assignments = []Assignment{live("a1", "c-mine", "u-leader", day.AddDate(0, -1, 0), nil, "active")}
	svc := service(data)
	ctx := as(RoleClusterLeader, "u-leader", "")

	mine, err := svc.GetMyClusters(ctx, connect.NewRequest(&clustersv1.GetMyClustersRequest{}))
	if err != nil || len(mine.Msg.GetClusters()) != 1 || mine.Msg.GetClusters()[0].GetId() != "c-mine" {
		t.Fatalf("want exactly the assigned cluster, got %v %v", mine, err)
	}
	if mine.Msg.GetClusters()[0].GetMemberSchoolCount() != 2 {
		t.Fatalf("want 2 member schools, got %d", mine.Msg.GetClusters()[0].GetMemberSchoolCount())
	}
	if _, err := svc.GetClusterHome(ctx, connect.NewRequest(&clustersv1.GetClusterHomeRequest{ClusterId: "c-mine"})); err != nil {
		t.Fatalf("the leader's own cluster: %v", err)
	}
	for _, call := range []func() error{
		func() error {
			_, err := svc.GetClusterHome(ctx, connect.NewRequest(&clustersv1.GetClusterHomeRequest{ClusterId: "c-other"}))
			return err
		},
		func() error {
			_, err := svc.ListMemberSchools(ctx, connect.NewRequest(&clustersv1.ListMemberSchoolsRequest{ClusterId: "c-other"}))
			return err
		},
	} {
		if err := call(); codeOf(err) != connect.CodePermissionDenied {
			t.Fatalf("another leader's cluster must be refused, got %v", err)
		}
	}
}

func TestAnAssignmentGivesAccessOnlyWhileItIsLive(t *testing.T) {
	ended := day.AddDate(0, 0, -1)
	cases := map[string]Assignment{
		"ended":            live("a1", "c-mine", "u-leader", day.AddDate(0, -2, 0), &ended, "ended"),
		"past its end":     live("a1", "c-mine", "u-leader", day.AddDate(0, -2, 0), &ended, "active"),
		"not started yet":  live("a1", "c-mine", "u-leader", day.AddDate(0, 0, 1), nil, "active"),
		"suspended":        live("a1", "c-mine", "u-leader", day.AddDate(0, -1, 0), nil, "suspended"),
		"another leader's": live("a1", "c-mine", "u-leader2", day.AddDate(0, -1, 0), nil, "active"),
	}
	for name, assignment := range cases {
		t.Run(name, func(t *testing.T) {
			data := newFake()
			data.assignments = []Assignment{assignment}
			_, err := service(data).ListMemberSchools(as(RoleClusterLeader, "u-leader", ""),
				connect.NewRequest(&clustersv1.ListMemberSchoolsRequest{ClusterId: "c-mine"}))
			if codeOf(err) != connect.CodePermissionDenied {
				t.Fatalf("want PermissionDenied, got %v", err)
			}
		})
	}
}

func TestMemberSchoolsCrossDistrictsAndCarryTheEdifySchoolID(t *testing.T) {
	data := newFake()
	data.assignments = []Assignment{live("a1", "c-mine", "u-leader", day, nil, "active")}
	got, err := service(data).ListMemberSchools(as(RoleClusterLeader, "u-leader", ""),
		connect.NewRequest(&clustersv1.ListMemberSchoolsRequest{ClusterId: "c-mine"}))
	if err != nil {
		t.Fatal(err)
	}
	schools := got.Msg.GetSchools()
	if len(schools) != 2 || schools[1].GetDistrict() != "Kayunga" || schools[1].GetSchoolId() != "1002" {
		t.Fatalf("want both members, across districts, with their School IDs: %v", schools)
	}
}

func TestOnlyClusterLeadersUseThePortal(t *testing.T) {
	data := newFake()
	data.assignments = []Assignment{live("a1", "c-mine", "u-staff", day, nil, "active")}
	_, err := service(data).GetMyClusters(as(roleCCEO, "u-staff", "sp-cceo"), connect.NewRequest(&clustersv1.GetMyClustersRequest{}))
	if codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("a CCEO is not a Cluster Leader, got %v", err)
	}
	acting := auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{
		UserID: "u-leader", ActiveRole: RoleClusterLeader, InActingAppointment: true,
	}})
	if _, err := service(data).GetMyClusters(acting, connect.NewRequest(&clustersv1.GetMyClustersRequest{})); codeOf(err) != connect.CodeFailedPrecondition {
		t.Fatalf("an acting appointment must be refused, got %v", err)
	}
}

func TestTheAssignmentPolicy(t *testing.T) {
	cases := []struct {
		name    string
		ctx     context.Context
		cluster string
		allowed bool
	}{
		{"Admin, any cluster", as(roleAdmin, "u-admin", ""), "c-other", true},
		{"Program Lead, any cluster of their country", inUganda(as(roleProgramLead, "u-pl", "sp-pl")), "c-other", true},
		{"Program Lead, a cluster of another country", inUganda(as(roleProgramLead, "u-pl", "sp-pl")), "c-kenya", false},
		{"Program Lead working in no Active country", as(roleProgramLead, "u-pl", "sp-pl"), "c-other", false},
		{"Admin, a cluster of any country", as(roleAdmin, "u-admin", ""), "c-kenya", true},
		{"CCEO, a cluster they are responsible for", as(roleCCEO, "u-cceo", "sp-cceo"), "c-mine", true},
		{"CCEO, someone else's cluster", as(roleCCEO, "u-cceo", "sp-cceo"), "c-other", false},
		{"Cluster Leader", as(RoleClusterLeader, "u-leader", ""), "c-mine", false},
		{"Accountant", as("Accountant", "u-acc", "sp-acc"), "c-mine", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := service(newFake()).ListLeaders(tc.ctx, connect.NewRequest(&clustersv1.ListLeadersRequest{ClusterId: tc.cluster}))
			if tc.allowed && err != nil {
				t.Fatalf("want allowed, got %v", err)
			}
			if !tc.allowed && codeOf(err) != connect.CodePermissionDenied {
				t.Fatalf("want PermissionDenied, got %v", err)
			}
		})
	}
}

func TestAssigningNeedsAnExistingLeaderAccountAndGrantsNoRole(t *testing.T) {
	svc := service(newFake())
	admin := as(roleAdmin, "u-admin", "")
	assign := func(user, starts, ends string) error {
		_, err := svc.AssignLeader(admin, connect.NewRequest(&clustersv1.AssignLeaderRequest{
			ClusterId: "c-mine", UserId: user, StartsOn: starts, EndsOn: ends,
		}))
		return err
	}
	if err := assign("u-staff", "", ""); codeOf(err) != connect.CodeFailedPrecondition {
		t.Fatalf("an account without the role must be refused, got %v", err)
	}
	if err := assign("u-nobody", "", ""); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a missing account must be refused, got %v", err)
	}
	if err := assign("u-leader", "2026-12-01", "2026-11-01"); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("an end before the start must be refused, got %v", err)
	}
	if err := assign("u-leader", "", ""); err != nil {
		t.Fatalf("assigning a Cluster Leader: %v", err)
	}
	if err := assign("u-leader", "", ""); codeOf(err) != connect.CodeAlreadyExists {
		t.Fatalf("a second live assignment must be refused, got %v", err)
	}
}

func TestReplacingALeaderKeepsTheOldAssignmentAndItsHistory(t *testing.T) {
	data := newFake()
	data.assignments = []Assignment{live("a1", "c-mine", "u-leader", day.AddDate(0, -3, 0), nil, "active")}
	svc := service(data)
	got, err := svc.ReplaceLeader(as(roleCCEO, "u-cceo", "sp-cceo"), connect.NewRequest(&clustersv1.ReplaceLeaderRequest{
		AssignmentId: "a1", NewUserId: "u-leader2", Reason: "moved school",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if got.Msg.GetEnded().GetStatus() != "ended" || got.Msg.GetEnded().GetHistory()[0].GetEvent() != "replaced" {
		t.Fatalf("the old assignment must end and say it was replaced: %v", got.Msg.GetEnded())
	}
	if got.Msg.GetAssignment().GetReplacesAssignmentId() != "a1" || got.Msg.GetAssignment().GetUserId() != "u-leader2" {
		t.Fatalf("the new assignment must name the one it replaced: %v", got.Msg.GetAssignment())
	}
	if len(data.assignments) != 2 {
		t.Fatalf("nothing is deleted: want 2 assignments, have %d", len(data.assignments))
	}
	// The old leader loses the cluster; the new one has it.
	if _, err := svc.GetClusterHome(as(RoleClusterLeader, "u-leader", ""), connect.NewRequest(&clustersv1.GetClusterHomeRequest{ClusterId: "c-mine"})); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("the replaced leader must lose the cluster, got %v", err)
	}
	if _, err := svc.GetClusterHome(as(RoleClusterLeader, "u-leader2", ""), connect.NewRequest(&clustersv1.GetClusterHomeRequest{ClusterId: "c-mine"})); err != nil {
		t.Fatalf("the new leader must have the cluster: %v", err)
	}
}

func TestTheHomeCountsRealRecordsAndSaysWhatIsNotBuiltYet(t *testing.T) {
	data := newFake()
	data.assignments = []Assignment{live("a1", "c-mine", "u-leader", day, nil, "active")}
	when := day.AddDate(0, 0, 5)
	data.upcoming["c-mine"] = []Activity{{ID: "act1", Kind: "only_meeting", Status: "scheduled", Date: &when, Venue: "Kasawo P/S", Invited: 6}}
	got, err := service(data).GetClusterHome(as(RoleClusterLeader, "u-leader", ""), connect.NewRequest(&clustersv1.GetClusterHomeRequest{ClusterId: "c-mine"}))
	if err != nil {
		t.Fatal(err)
	}
	counts := map[string]int32{}
	for _, count := range got.Msg.GetOverview() {
		counts[count.GetKey()] = count.GetValue()
		if count.GetHref() == "" {
			t.Fatalf("every count opens its records: %v", count)
		}
	}
	if counts["member_schools"] != 2 || counts["upcoming_meetings"] != 1 {
		t.Fatalf("counts: %v", counts)
	}
	activity := got.Msg.GetUpcoming()[0]
	if activity.GetId() != "act1" || activity.GetType() != "Only Meeting" || activity.GetDate() != "2026-11-15" {
		t.Fatalf("the activity keeps its id, kind and date: %v", activity)
	}
	for _, action := range got.Msg.GetQuickActions() {
		if !action.GetEnabled() && action.GetReason() == "" {
			t.Fatalf("an action not built yet says why: %v", action)
		}
	}
}

func TestManagedClustersFollowTheAssignmentPolicy(t *testing.T) {
	svc := service(newFake())
	count := func(ctx context.Context) (int, error) {
		got, err := svc.ListManagedClusters(ctx, connect.NewRequest(&clustersv1.ListManagedClustersRequest{}))
		if err != nil {
			return 0, err
		}
		return len(got.Msg.GetClusters()), nil
	}
	if n, err := count(as(roleAdmin, "u-admin", "")); err != nil || n != 3 {
		t.Fatalf("Admin manages every cluster: %d %v", n, err)
	}
	if n, err := count(inUganda(as(roleProgramLead, "u-pl", "sp-pl"))); err != nil || n != 2 {
		t.Fatalf("a Programme Lead manages their country's clusters: %d %v", n, err)
	}
	if n, err := count(as(roleCCEO, "u-cceo", "sp-cceo")); err != nil || n != 1 {
		t.Fatalf("a CCEO manages only their own clusters: %d %v", n, err)
	}
	if _, err := count(as(RoleClusterLeader, "u-leader", "")); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("a Cluster Leader manages no cluster, got %v", err)
	}
}

// A cluster's responsible_staff_id is a user id when the web's edit drawer
// saved it and a staff-profile id otherwise (apps/core/scoping.py
// cluster_owner_ids): the CCEO is responsible either way.
func TestACCEOManagesTheirClusterFiledUnderEitherId(t *testing.T) {
	f := newFake()
	mine := f.clusters["c-mine"]
	mine.ResponsibleStaffID = "u-cceo"
	f.clusters["c-mine"] = mine
	svc := service(f)
	ctx := as(roleCCEO, "u-cceo", "sp-cceo")
	if _, err := svc.ListLeaders(ctx, connect.NewRequest(&clustersv1.ListLeadersRequest{ClusterId: "c-mine"})); err != nil {
		t.Fatalf("a cluster filed under the CCEO's user id: %v", err)
	}
	got, err := svc.ListManagedClusters(ctx, connect.NewRequest(&clustersv1.ListManagedClustersRequest{}))
	if err != nil || len(got.Msg.GetClusters()) != 1 {
		t.Fatalf("their managed clusters: %v %v", got, err)
	}
	if _, err := svc.ListLeaders(as(roleCCEO, "u-other", "sp-other"), connect.NewRequest(&clustersv1.ListLeadersRequest{ClusterId: "c-mine"})); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("another CCEO, got %v", err)
	}
}
