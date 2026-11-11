package clusterlead

import (
	"context"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
)

// fakeOps adds the operations records to fakeData, in memory.
type fakeOps struct {
	*fakeData
	activities  map[string]ActivityRecord
	plans       map[string]Plan
	invitations []Invitation
	attendance  map[string][]AttendanceRecord
	planInvited map[string][]PlanInvitee
	ssa         SSAAverages
}

func newOps() *fakeOps {
	data := newFake()
	data.assignments = []Assignment{live("a1", "c-mine", "u-leader", day.AddDate(0, -1, 0), nil, "active")}
	soon, past := day.AddDate(0, 0, 5), day.AddDate(0, 0, -3)
	return &fakeOps{
		fakeData: data,
		activities: map[string]ActivityRecord{
			"act-soon":     {Activity: Activity{ID: "act-soon", Kind: "only_meeting", Status: "scheduled", Date: &soon}, ClusterID: "c-mine"},
			"act-training": {Activity: Activity{ID: "act-training", Kind: "training", Status: "scheduled", Date: &soon}, ClusterID: "c-mine"},
			"act-past":     {Activity: Activity{ID: "act-past", Kind: "only_meeting", Status: "scheduled", Date: &past}, ClusterID: "c-mine"},
			"act-other":    {Activity: Activity{ID: "act-other", Kind: "only_meeting", Status: "scheduled", Date: &soon}, ClusterID: "c-other"},
		},
		plans:       map[string]Plan{},
		attendance:  map[string][]AttendanceRecord{},
		planInvited: map[string][]PlanInvitee{},
	}
}

func (f *fakeOps) ActivityFor(_ context.Context, id string) (ActivityRecord, error) {
	a, ok := f.activities[id]
	if !ok {
		return ActivityRecord{}, ErrNotFound
	}
	return a, nil
}
func (f *fakeOps) Plans(_ context.Context, clusterID string) ([]Plan, error) {
	var out []Plan
	for _, p := range f.plans {
		if p.ClusterID == clusterID {
			out = append(out, p)
		}
	}
	return out, nil
}
func (f *fakeOps) Plan(_ context.Context, id string) (Plan, error) {
	p, ok := f.plans[id]
	if !ok {
		return Plan{}, ErrNotFound
	}
	p.InvitedCount = int32(len(f.planInvited[id])) // #nosec G115 -- a test's handful
	return p, nil
}
func (f *fakeOps) InvitePlan(_ context.Context, _, plan string, schools, _ []string, channel, _ string) (int, error) {
	if p := f.plans[plan]; p.Status == "scheduled" || p.Status == "cancelled" {
		return 0, nil
	}
	n := 0
	for _, school := range schools {
		known := false
		for _, inv := range f.planInvited[plan] {
			known = known || inv.SchoolID == school
		}
		if !known {
			f.planInvited[plan] = append(f.planInvited[plan], PlanInvitee{SchoolID: school, Name: school, Channel: channel, InvitedAt: day})
			n++
		}
	}
	return n, nil
}
func (f *fakeOps) PlanInvitees(_ context.Context, plan string) ([]PlanInvitee, error) {
	return f.planInvited[plan], nil
}
func (f *fakeOps) SSAPerformance(context.Context, string, int) (SSAAverages, error) {
	return f.ssa, nil
}
func (f *fakeOps) Courses(context.Context) ([]Course, error) {
	return []Course{{ID: "course-tam", Name: "Teaching as Mission (TAM)"}}, nil
}
func (f *fakeOps) SavePlan(_ context.Context, p Plan, _ bool, actor, _ string) error {
	if old, ok := f.plans[p.ID]; ok && (old.Status == "scheduled" || old.Status == "cancelled") {
		return ErrNotLive
	}
	p.CreatedBy = actor
	f.plans[p.ID] = p
	return nil
}
func (f *fakeOps) MovePlan(_ context.Context, id string, from []string, status, _, _, note, activity string) error {
	p, ok := f.plans[id]
	if !ok {
		return ErrNotLive
	}
	for _, s := range from {
		if p.Status == s {
			p.Status, p.ReviewNote = status, note
			if activity != "" {
				p.ActivityID = activity
			}
			f.plans[id] = p
			return nil
		}
	}
	return ErrNotLive
}
func (f *fakeOps) Invitations(_ context.Context, activity string) ([]Invitation, error) {
	var out []Invitation
	for _, i := range f.invitations {
		if i.ActivityID == activity {
			out = append(out, i)
		}
	}
	return out, nil
}
func (f *fakeOps) Invitation(_ context.Context, id string) (Invitation, error) {
	for _, i := range f.invitations {
		if i.ID == id {
			return i, nil
		}
	}
	return Invitation{}, ErrNotFound
}
func (f *fakeOps) Invite(_ context.Context, cluster, activity string, schools, ids []string, channel, _ string) (int, error) {
	n := 0
	for i, school := range schools {
		known := false
		for _, inv := range f.invitations {
			known = known || (inv.ActivityID == activity && inv.SchoolID == school)
		}
		if !known {
			f.invitations = append(f.invitations, Invitation{ID: ids[i], ClusterID: cluster, ActivityID: activity,
				SchoolID: school, Status: "invited", Channel: channel, DeliveryStatus: "recorded"})
			n++
		}
	}
	return n, nil
}
func (f *fakeOps) RespondInvitation(_ context.Context, id, status, note, _ string) error {
	for i := range f.invitations {
		if f.invitations[i].ID == id {
			f.invitations[i].Status, f.invitations[i].ResponseNote = status, note
		}
	}
	return nil
}
func (f *fakeOps) FollowUpInvitation(context.Context, string, string, string) error { return nil }
func (f *fakeOps) Attendance(_ context.Context, activity string) ([]AttendanceRecord, error) {
	return f.attendance[activity], nil
}
func (f *fakeOps) RecordAttendance(_ context.Context, _, activity string, entries []AttendanceRecord, _ []string, _ string) error {
	f.attendance[activity] = entries
	return nil
}
func (f *fakeOps) MinutesOf(context.Context, string) (*MinutesRecord, error) { return nil, nil }
func (f *fakeOps) SaveMinutes(context.Context, string, string, string, string, string, bool, string) error {
	return nil
}
func (f *fakeOps) Items(context.Context, string, bool) ([]Item, error)             { return nil, nil }
func (f *fakeOps) ItemByID(context.Context, string) (Item, error)                  { return Item{}, ErrNotFound }
func (f *fakeOps) SaveItem(context.Context, Item, string, bool, string) error      { return nil }
func (f *fakeOps) CloseItem(context.Context, string, string, string, string) error { return nil }
func (f *fakeOps) Requests(context.Context, string) ([]Request, error)             { return nil, nil }
func (f *fakeOps) RequestByID(context.Context, string) (Request, error) {
	return Request{}, ErrNotFound
}
func (f *fakeOps) CreateRequest(context.Context, string, string, string, string, string) error {
	return nil
}
func (f *fakeOps) AnswerRequestRecord(context.Context, string, string, string) error { return nil }
func (f *fakeOps) Report(context.Context, string, time.Time, time.Time) (ReportData, error) {
	return ReportData{}, nil
}

func operations(f *fakeOps) *OperationsService {
	return NewOperations(service(f), f)
}

var leaderCtx = func() context.Context { return as(RoleClusterLeader, "u-leader", "") }
var cceoCtx = func() context.Context { return as(roleCCEO, "u-cceo", "sp-cceo") }

func TestAnAnswerIsNeverAttendance(t *testing.T) {
	confirmed := &Invitation{Status: "confirmed"}
	cases := []struct {
		name                        string
		invitation                  *Invitation
		record                      *AttendanceRecord
		official, isHeld, hasPassed bool
		want, source                string
	}{
		{"confirmed, nothing recorded yet", confirmed, nil, false, false, true, "confirmed", ""},
		{"no answer once the day passed", &Invitation{Status: "invited"}, nil, false, false, true, "no_response", ""},
		{"the leader saw them come", confirmed, &AttendanceRecord{Attended: true}, false, false, true, "attended", "leader"},
		{"the leader saw them miss it", confirmed, &AttendanceRecord{Attended: false}, false, false, true, "absent", "leader"},
		{"staff recorded them", nil, nil, true, true, true, "attended", "official"},
		{"staff completed it without them", confirmed, &AttendanceRecord{Attended: true}, false, true, true, "absent", "official"},
		{"never invited", nil, nil, false, false, false, "not_invited", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			state, source := stateOf(tc.invitation, tc.record, tc.official, tc.isHeld, tc.hasPassed)
			if state != tc.want || source != tc.source {
				t.Fatalf("want %s/%s, got %s/%s", tc.want, tc.source, state, source)
			}
		})
	}
}

func TestAPlanMeetsTheBriefsRules(t *testing.T) {
	svc := operations(newOps())
	save := func(category, course, date string) error {
		_, err := svc.SavePlan(leaderCtx(), connect.NewRequest(&clustersv1.SavePlanRequest{
			ClusterId: "c-mine", Category: category, Title: "Term planning", TrainingCourseId: course, PlannedOn: date,
		}))
		return err
	}
	if err := save("training", "", "2026-11-20"); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a training must name a governed course, got %v", err)
	}
	if err := save("training", "course-unknown", "2026-11-20"); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("an ungoverned course must be refused, got %v", err)
	}
	if err := save("only_meeting", "course-tam", "2026-11-20"); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a meeting names no course, got %v", err)
	}
	if err := save("only_meeting", "", "2026-11-01"); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a plan cannot be dated in the past, got %v", err)
	}
	if err := save("training", "course-tam", "2026-11-20"); err != nil {
		t.Fatalf("a valid training plan: %v", err)
	}
	if _, err := svc.SavePlan(cceoCtx(), connect.NewRequest(&clustersv1.SavePlanRequest{
		ClusterId: "c-mine", Category: "only_meeting", Title: "x", PlannedOn: "2026-11-20",
	})); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("staff do not write the leader's plans, got %v", err)
	}
}

func TestALeaderCannotApproveTheirOwnPlan(t *testing.T) {
	f := newOps()
	svc := operations(f)
	saved, err := svc.SavePlan(leaderCtx(), connect.NewRequest(&clustersv1.SavePlanRequest{
		ClusterId: "c-mine", Category: "only_meeting", Title: "Term planning", PlannedOn: "2026-11-20", Submit: true,
	}))
	if err != nil {
		t.Fatal(err)
	}
	id := saved.Msg.GetPlan().GetId()
	if _, err := svc.ReviewPlan(leaderCtx(), connect.NewRequest(&clustersv1.ReviewPlanRequest{Id: id, Approve: true})); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("a leader approving their own plan must be refused, got %v", err)
	}
	if _, err := svc.ReviewPlan(cceoCtx(), connect.NewRequest(&clustersv1.ReviewPlanRequest{Id: id, Approve: false})); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("returning a plan needs a note, got %v", err)
	}
	if _, err := svc.ReviewPlan(cceoCtx(), connect.NewRequest(&clustersv1.ReviewPlanRequest{Id: id, Approve: true})); err != nil {
		t.Fatalf("the responsible CCEO approves: %v", err)
	}
	// Linking: the activity must be this cluster's and of the plan's kind.
	if _, err := svc.LinkPlan(cceoCtx(), connect.NewRequest(&clustersv1.LinkPlanRequest{Id: id, ActivityId: "act-other"})); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("another cluster's activity must be refused, got %v", err)
	}
	if _, err := svc.LinkPlan(cceoCtx(), connect.NewRequest(&clustersv1.LinkPlanRequest{Id: id, ActivityId: "act-training"})); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a meeting plan does not link to a training, got %v", err)
	}
	linked, err := svc.LinkPlan(cceoCtx(), connect.NewRequest(&clustersv1.LinkPlanRequest{Id: id, ActivityId: "act-soon"}))
	if err != nil || linked.Msg.GetPlan().GetStatus() != "scheduled" || linked.Msg.GetPlan().GetActivityId() != "act-soon" {
		t.Fatalf("the plan keeps the official activity's id: %v %v", linked, err)
	}
}

func TestMobilisationReachesOnlyMemberSchoolsOfLiveActivities(t *testing.T) {
	f := newOps()
	svc := operations(f)
	invite := func(ctx context.Context, activity string, schools ...string) error {
		_, err := svc.InviteSchools(ctx, connect.NewRequest(&clustersv1.InviteSchoolsRequest{
			ActivityId: activity, SchoolIds: schools, Channel: "phone",
		}))
		return err
	}
	if err := invite(leaderCtx(), "act-soon", "s1", "not-a-member"); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a school outside the cluster must be refused, got %v", err)
	}
	if err := invite(leaderCtx(), "act-past", "s1"); codeOf(err) != connect.CodeFailedPrecondition {
		t.Fatalf("an activity already held takes no invitations, got %v", err)
	}
	if err := invite(leaderCtx(), "act-other", "s1"); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("another cluster's activity must be refused, got %v", err)
	}
	if err := invite(cceoCtx(), "act-soon", "s1"); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("staff do not mobilise for the leader, got %v", err)
	}
	// Cross-district: s2 is in Kayunga, the cluster's other district.
	if err := invite(leaderCtx(), "act-soon", "s1", "s2"); err != nil {
		t.Fatalf("both member schools, across districts: %v", err)
	}
	got, err := svc.GetMobilization(leaderCtx(), connect.NewRequest(&clustersv1.GetMobilizationRequest{ActivityId: "act-soon"}))
	if err != nil {
		t.Fatal(err)
	}
	if got.Msg.GetCounts()["invited"] != 2 {
		t.Fatalf("both invited: %v", got.Msg.GetCounts())
	}
	for _, school := range got.Msg.GetSchools() {
		if school.GetDeliveryStatus() != "recorded" {
			t.Fatalf("no delivery is claimed without a messaging integration: %v", school)
		}
	}
}

func TestAttendanceWaitsForTheActivitysDay(t *testing.T) {
	svc := operations(newOps())
	record := func(activity string) error {
		_, err := svc.RecordAttendance(leaderCtx(), connect.NewRequest(&clustersv1.RecordAttendanceRequest{
			ActivityId: activity, Entries: []*clustersv1.AttendanceEntry{{SchoolId: "s1", Attended: true, Participants: 3}},
		}))
		return err
	}
	if err := record("act-soon"); codeOf(err) != connect.CodeFailedPrecondition {
		t.Fatalf("attendance before the day must be refused, got %v", err)
	}
	if err := record("act-past"); err != nil {
		t.Fatalf("attendance after the day: %v", err)
	}
}

func TestALeaderInvitesMemberSchoolsWhilePlanning(t *testing.T) {
	f := newOps()
	svc := operations(f)
	saved, err := svc.SavePlan(leaderCtx(), connect.NewRequest(&clustersv1.SavePlanRequest{
		ClusterId: "c-mine", Category: "only_meeting", Title: "Term 1 Cluster Meeting", PlannedOn: "2026-11-20", Submit: true,
	}))
	if err != nil {
		t.Fatal(err)
	}
	plan := saved.Msg.GetPlan().GetId()
	invite := func(ctx context.Context, schools ...string) (*clustersv1.InvitePlanSchoolsResponse, error) {
		answer, err := svc.InvitePlanSchools(ctx, connect.NewRequest(&clustersv1.InvitePlanSchoolsRequest{
			PlanId: plan, SchoolIds: schools, Channel: "phone",
		}))
		if err != nil {
			return nil, err
		}
		return answer.Msg, nil
	}
	if _, err := invite(leaderCtx(), "s1", "not-a-member"); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a school outside the cluster must be refused, got %v", err)
	}
	if _, err := invite(cceoCtx(), "s1"); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("staff do not invite for the leader, got %v", err)
	}
	if got, err := invite(leaderCtx(), "s1", "s2"); err != nil || got.GetInvited() != 2 {
		t.Fatalf("both member schools: %v %v", got, err)
	}
	if got, err := invite(leaderCtx(), "s1"); err != nil || got.GetAlreadyInvited() != 1 {
		t.Fatalf("an invited school is left as it was: %v %v", got, err)
	}
	shown, err := svc.GetPlan(leaderCtx(), connect.NewRequest(&clustersv1.GetPlanRequest{Id: plan}))
	if err != nil {
		t.Fatal(err)
	}
	if len(shown.Msg.GetInvited()) != 2 || shown.Msg.GetPlan().GetInvitedCount() != 2 || !shown.Msg.GetCanInvite() ||
		!shown.Msg.GetPlan().GetCanCancel() {
		t.Fatalf("plan page: %v", shown.Msg)
	}
	if _, err := svc.CancelPlan(leaderCtx(), connect.NewRequest(&clustersv1.CancelPlanRequest{Id: plan})); err != nil {
		t.Fatal(err)
	}
	if _, err := invite(leaderCtx(), "s1"); codeOf(err) != connect.CodeFailedPrecondition {
		t.Fatalf("a cancelled plan takes no invitations, got %v", err)
	}
}

func TestSSAPerformanceComparesThisYearWithTheLast(t *testing.T) {
	f := newOps()
	f.ssa = SSAAverages{Current: 5.91, Previous: 4.96, SchoolsCurrent: 306, SchoolsPrevious: 700,
		PairedCurrent: 6.0, PairedPrevious: 5.0, SchoolsPaired: 300}
	got, err := operations(f).GetClusterReport(leaderCtx(), connect.NewRequest(&clustersv1.GetClusterReportRequest{ClusterId: "c-mine"}))
	if err != nil {
		t.Fatal(err)
	}
	ssa := got.Msg.GetSsaPerformance()
	// The change is the paired schools' (6.0 against 5.0), never the two
	// years' different school sets (5.91 against 4.96).
	if ssa.GetCurrentAverage() != "5.91" || ssa.GetPreviousAverage() != "4.96" || ssa.GetChange() != "+20%" || ssa.GetSchoolsCompared() != 300 ||
		ssa.GetCurrentPeriod() != "FY 2027" || ssa.GetPreviousPeriod() != "FY 2026" {
		t.Fatalf("ssa performance %v", ssa)
	}
	f.ssa = SSAAverages{Current: 5.2, Previous: 4.9, SchoolsCurrent: 2, SchoolsPrevious: 3}
	got, _ = operations(f).GetClusterReport(leaderCtx(), connect.NewRequest(&clustersv1.GetClusterReportRequest{ClusterId: "c-mine"}))
	if got.Msg.GetSsaPerformance().GetChange() != "" {
		t.Fatalf("no change is claimed when no school was assessed in both years: %v", got.Msg.GetSsaPerformance())
	}
}

func TestTheClusterReportIsAPDFForItsOwnClusterOnly(t *testing.T) {
	f := newOps()
	f.ssa = SSAAverages{Current: 5.91, Previous: 4.96, SchoolsCurrent: 3, SchoolsPrevious: 3,
		PairedCurrent: 5.91, PairedPrevious: 4.96, SchoolsPaired: 3}
	svc := operations(f)
	got, err := svc.GetClusterReportPdf(leaderCtx(), connect.NewRequest(&clustersv1.GetClusterReportPdfRequest{ClusterId: "c-mine"}))
	if err != nil {
		t.Fatal(err)
	}
	pdf := string(got.Msg.GetPdf())
	if !strings.HasPrefix(pdf, "%PDF-") || !strings.Contains(pdf, "%%EOF") || !strings.Contains(pdf, "Participation rate") ||
		!strings.Contains(pdf, "+19%") || !strings.HasSuffix(got.Msg.GetFileName(), ".pdf") {
		t.Fatalf("not the report as a PDF: %q (%d bytes)", got.Msg.GetFileName(), len(pdf))
	}
	if _, err := svc.GetClusterReportPdf(leaderCtx(), connect.NewRequest(&clustersv1.GetClusterReportPdfRequest{ClusterId: "c-other"})); codeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("another cluster's report must be refused, got %v", err)
	}
}

func TestAnEditedApprovedPlanGoesBackToStaff(t *testing.T) {
	f := newOps()
	svc := operations(f)
	save := func(id string) (*clustersv1.MeetingPlan, error) {
		got, err := svc.SavePlan(leaderCtx(), connect.NewRequest(&clustersv1.SavePlanRequest{
			Id: id, ClusterId: "c-mine", Category: "only_meeting", Title: "Term 1 Cluster Meeting", PlannedOn: "2026-11-20", Submit: true,
		}))
		if err != nil {
			return nil, err
		}
		return got.Msg.GetPlan(), nil
	}
	plan, err := save("")
	if err != nil || !plan.GetCanEdit() {
		t.Fatalf("a submitted plan is still the leader's to edit: %v %v", plan, err)
	}
	if plan, err = save(plan.GetId()); err != nil || plan.GetStatus() != "submitted" {
		t.Fatalf("editing while staff review it: %v %v", plan, err)
	}
	if _, err := svc.ReviewPlan(cceoCtx(), connect.NewRequest(&clustersv1.ReviewPlanRequest{Id: plan.GetId(), Approve: true})); err != nil {
		t.Fatal(err)
	}
	if plan, err = save(plan.GetId()); err != nil || plan.GetStatus() != "submitted" {
		t.Fatalf("an edited approved plan goes back to staff: %v %v", plan, err)
	}
	if _, err := svc.CancelPlan(leaderCtx(), connect.NewRequest(&clustersv1.CancelPlanRequest{Id: plan.GetId()})); err != nil {
		t.Fatal(err)
	}
	if _, err := save(plan.GetId()); codeOf(err) != connect.CodeFailedPrecondition {
		t.Fatalf("a cancelled plan cannot be edited, got %v", err)
	}
}

func TestSSAStatusesReadAsTheApplicationWordsThem(t *testing.T) {
	for status, want := range map[string]string{"not_done": "Not Done", "partner_assigned": "Partner Assigned", "done": "Done", "odd": "odd"} {
		if got := ssaStatusLabel(status); got != want {
			t.Errorf("%s: %q, want %q", status, got, want)
		}
	}
}
