package screens

import (
	"context"
	"net/url"
	"strings"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

type recordingFetcher struct{ paths []string }

func (f *recordingFetcher) Get(_ context.Context, path string, _ proto.Message) error {
	f.paths = append(f.paths, path)
	return nil
}

func (f *recordingFetcher) Post(_ context.Context, path string, _, _ proto.Message) error {
	f.paths = append(f.paths, "POST "+path)
	return nil
}

func TestDirectoryForwardsOnlyThePagesOwnParameters(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)

	_, err := service.GetSchoolDirectory(context.Background(), connect.NewRequest(&screensv1.GetSchoolDirectoryRequest{
		Q: "st mary & co", Tab: "unclustered", Page: 3, District: "d1",
	}))
	if err != nil {
		t.Fatal(err)
	}
	path, rawQuery, _ := strings.Cut(fetcher.paths[0], "?")
	if path != pathSchoolDirectory {
		t.Fatalf("path %q", path)
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		t.Fatal(err)
	}
	want := url.Values{"q": {"st mary & co"}, "tab": {"unclustered"}, "page": {"3"}, "district": {"d1"}}
	if query.Encode() != want.Encode() {
		t.Fatalf("query %q, want %q", query.Encode(), want.Encode())
	}
}

func TestDirectoryWithNoParametersAsksForThePageDefault(t *testing.T) {
	fetcher := &recordingFetcher{}

	if _, err := NewService(fetcher).GetSchoolDirectory(context.Background(),
		connect.NewRequest(&screensv1.GetSchoolDirectoryRequest{})); err != nil {
		t.Fatal(err)
	}
	if fetcher.paths[0] != pathSchoolDirectory {
		t.Fatalf("path %q", fetcher.paths[0])
	}
}

func TestScreensWithoutTheExistingApplicationAreUnavailable(t *testing.T) {
	_, err := NewService(nil).GetHome(context.Background(), connect.NewRequest(&screensv1.GetHomeRequest{}))

	if connect.CodeOf(err) != connect.CodeUnavailable || apierr.Reason(err) != apierr.ReasonScreenUnavailable {
		t.Fatalf("got %v", err)
	}
}

func TestActionsGoToTheirSchoolsPathWithTheIDEscaped(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)
	ctx := context.Background()

	_, _ = service.AddToCluster(ctx, connect.NewRequest(&screensv1.AddToClusterRequest{SchoolId: "a/b"}))
	_, _ = service.GetAddToProject(ctx, connect.NewRequest(&screensv1.GetAddToProjectRequest{SchoolId: "s1"}))

	want := []string{"POST /api/mobile/v1/schools/a%2Fb/add-to-cluster", "/api/mobile/v1/schools/s1/add-to-project"}
	if strings.Join(fetcher.paths, "|") != strings.Join(want, "|") {
		t.Fatalf("paths %v", fetcher.paths)
	}
}

func TestAnActionNeedsASchool(t *testing.T) {
	fetcher := &recordingFetcher{}

	_, err := NewService(fetcher).AddToProject(context.Background(), connect.NewRequest(&screensv1.AddToProjectRequest{}))

	if connect.CodeOf(err) != connect.CodeInvalidArgument || len(fetcher.paths) != 0 {
		t.Fatalf("got %v, %v", err, fetcher.paths)
	}
}

func TestBulkSavesAreBounded(t *testing.T) {
	fetcher := &recordingFetcher{}
	ids := make([]string, maxBulkSchools+1)

	_, err := NewService(fetcher).BulkAssignCluster(context.Background(),
		connect.NewRequest(&screensv1.BulkAssignClusterRequest{SchoolIds: ids, ClusterId: "c1"}))

	if connect.CodeOf(err) != connect.CodeInvalidArgument || len(fetcher.paths) != 0 {
		t.Fatalf("got %v, %v", err, fetcher.paths)
	}
}

func TestBulkSavesGoToTheirFeed(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)

	_, _ = service.BulkAssignCluster(context.Background(),
		connect.NewRequest(&screensv1.BulkAssignClusterRequest{SchoolIds: []string{"a"}}))
	_, _ = service.BulkAssignProject(context.Background(),
		connect.NewRequest(&screensv1.BulkAssignProjectRequest{SchoolIds: []string{"a"}}))

	want := "POST /api/mobile/v1/schools/bulk-assign-cluster|POST /api/mobile/v1/schools/bulk-assign-project"
	if strings.Join(fetcher.paths, "|") != want {
		t.Fatalf("paths %v", fetcher.paths)
	}
}

func TestProfileForwardsOnlyThePagesOwnParameters(t *testing.T) {
	fetcher := &recordingFetcher{}

	_, err := NewService(fetcher).GetSchoolProfile(context.Background(), connect.NewRequest(&screensv1.GetSchoolProfileRequest{
		SchoolId: "s/1", Tab: "details", Fy: "2027",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if fetcher.paths[0] != "/api/mobile/v1/schools/s%2F1/profile?fy=2027&tab=details" {
		t.Fatalf("path %q", fetcher.paths[0])
	}
}

func TestProfileWithNoQueryAsksForThePageDefault(t *testing.T) {
	fetcher := &recordingFetcher{}

	_, err := NewService(fetcher).GetSchoolProfile(context.Background(),
		connect.NewRequest(&screensv1.GetSchoolProfileRequest{SchoolId: "s1"}))
	if err != nil {
		t.Fatal(err)
	}
	if fetcher.paths[0] != "/api/mobile/v1/schools/s1/profile" {
		t.Fatalf("path %q", fetcher.paths[0])
	}
}

func TestProfileNeedsASchool(t *testing.T) {
	fetcher := &recordingFetcher{}

	_, err := NewService(fetcher).GetSchoolProfile(context.Background(),
		connect.NewRequest(&screensv1.GetSchoolProfileRequest{}))

	if connect.CodeOf(err) != connect.CodeInvalidArgument || len(fetcher.paths) != 0 {
		t.Fatalf("got %v, %v", err, fetcher.paths)
	}
}

func TestDrawersGoToTheirSchoolsPath(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)
	ctx := context.Background()

	_, _ = service.GetSchoolDrawer(ctx, connect.NewRequest(&screensv1.GetSchoolDrawerRequest{SchoolId: "s/1", Kind: "edit"}))
	_, _ = service.SaveSchoolDrawer(ctx, connect.NewRequest(&screensv1.SaveSchoolDrawerRequest{SchoolId: "s1", Kind: "ssa-entry"}))
	_, _ = service.GetDrawerOptions(ctx, connect.NewRequest(&screensv1.GetDrawerOptionsRequest{
		Source: "/schools/sub-counties", Name: "district_id", Value: "d 1",
	}))

	want := []string{
		"/api/mobile/v1/schools/s%2F1/drawers/edit",
		"POST /api/mobile/v1/schools/s1/drawers/ssa-entry",
		"/api/mobile/v1/drawers/options?district_id=d+1&source=%2Fschools%2Fsub-counties",
	}
	if strings.Join(fetcher.paths, "|") != strings.Join(want, "|") {
		t.Fatalf("paths %v", fetcher.paths)
	}
}

func TestADrawerIsNamedPlainly(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)
	ctx := context.Background()

	for _, kind := range []string{"", "../users", "edit?x=1", strings.Repeat("a", 40)} {
		_, err := service.GetSchoolDrawer(ctx, connect.NewRequest(&screensv1.GetSchoolDrawerRequest{SchoolId: "s1", Kind: kind}))
		if connect.CodeOf(err) != connect.CodeInvalidArgument {
			t.Fatalf("%q: got %v", kind, err)
		}
	}
	for _, request := range []*screensv1.GetDrawerOptionsRequest{
		{Source: "https://elsewhere.example/x", Name: "district_id"},
		{Source: "/schools/sub-counties", Name: "source"},
		{Source: "/schools/sub-counties", Name: "a b"},
	} {
		_, err := service.GetDrawerOptions(ctx, connect.NewRequest(request))
		if connect.CodeOf(err) != connect.CodeInvalidArgument {
			t.Fatalf("%v: got %v", request, err)
		}
	}
	if len(fetcher.paths) != 0 {
		t.Fatalf("called the existing application: %v", fetcher.paths)
	}
}

func TestPlanningDrawersGoToTheirSchoolsPath(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)
	ctx := context.Background()

	_, _ = service.GetPlanningDrawer(ctx, connect.NewRequest(&screensv1.GetPlanningDrawerRequest{SchoolId: "s1", Kind: "schedule"}))
	_, _ = service.SavePlanningDrawer(ctx, connect.NewRequest(&screensv1.SavePlanningDrawerRequest{
		SchoolId: "s1", Kind: "assign", Values: map[string]string{"partner_id": "p1"},
	}))
	_, _ = service.GetTrainingCapacity(ctx, connect.NewRequest(&screensv1.GetTrainingCapacityRequest{
		Training: "t1", Date: "2026-11-24", School: "1286",
	}))

	want := []string{
		"/api/mobile/v1/schools/s1/planning/schedule",
		"POST /api/mobile/v1/schools/s1/planning/assign",
		"/api/mobile/v1/planning/training-capacity?date=2026-11-24&school=1286&training=t1",
	}
	if strings.Join(fetcher.paths, "|") != strings.Join(want, "|") {
		t.Fatalf("paths %v", fetcher.paths)
	}
}

func TestOnlyThePlanningDrawersAndPlainValuesPass(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)
	ctx := context.Background()

	for _, kind := range []string{"", "edit", "../users", "schedule/x"} {
		_, err := service.GetPlanningDrawer(ctx, connect.NewRequest(&screensv1.GetPlanningDrawerRequest{SchoolId: "s1", Kind: kind}))
		if connect.CodeOf(err) != connect.CodeInvalidArgument {
			t.Fatalf("%q: got %v", kind, err)
		}
	}
	_, err := service.SavePlanningDrawer(ctx, connect.NewRequest(&screensv1.SavePlanningDrawerRequest{
		SchoolId: "s1", Kind: "assign", Values: map[string]string{"school id": "x"},
	}))
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("field name: got %v", err)
	}
	for _, request := range []*screensv1.GetTrainingCapacityRequest{
		{Training: "t1&x=1"},
		{Date: "24/11/2026"},
		{School: "../1286"},
	} {
		_, err := service.GetTrainingCapacity(ctx, connect.NewRequest(request))
		if connect.CodeOf(err) != connect.CodeInvalidArgument {
			t.Fatalf("%v: got %v", request, err)
		}
	}
	if len(fetcher.paths) != 0 {
		t.Fatalf("reached the feed: %v", fetcher.paths)
	}
}

func TestMyPlanPassesItsQueryToTheFeed(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)

	_, _ = service.GetMyPlan(context.Background(), connect.NewRequest(&screensv1.GetMyPlanRequest{
		Query: map[string]string{"fy": "2026", "period": "week", "school_visits_page": "2", "month": ""},
	}))

	want := "/api/mobile/v1/my-plan?fy=2026&period=week&school_visits_page=2"
	if strings.Join(fetcher.paths, "|") != want {
		t.Fatalf("paths %v", fetcher.paths)
	}
}

func TestMyPlanRefusesAQueryThatIsNotPlain(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)

	for _, query := range []map[string]string{
		{"fy&x": "1"},
		{"Export": "xlsx"},
		{"fy": strings.Repeat("9", 129)},
	} {
		_, err := service.GetMyPlan(context.Background(), connect.NewRequest(&screensv1.GetMyPlanRequest{Query: query}))
		if connect.CodeOf(err) != connect.CodeInvalidArgument {
			t.Fatalf("%v: got %v", query, err)
		}
	}
	if len(fetcher.paths) != 0 {
		t.Fatalf("reached the feed: %v", fetcher.paths)
	}
}

func TestAPageGoesToTheFeedWithItsQuery(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)

	_, _ = service.GetPage(context.Background(), connect.NewRequest(&screensv1.GetPageRequest{
		Path: "/clusters", Query: map[string]string{"status": "active"},
	}))

	if strings.Join(fetcher.paths, "|") != "/api/mobile/v1/page?path=%2Fclusters&status=active" {
		t.Fatalf("paths %v", fetcher.paths)
	}
}

func TestAPagePathMustBePlain(t *testing.T) {
	fetcher := &recordingFetcher{}
	service := NewService(fetcher)

	for _, path := range []string{"", "todos", "/../admin", "/todos?x=1", "https://elsewhere.example/x", "/a/b/c/d/e", "/Todos"} {
		_, err := service.GetPage(context.Background(), connect.NewRequest(&screensv1.GetPageRequest{Path: path}))
		if connect.CodeOf(err) != connect.CodeInvalidArgument {
			t.Fatalf("%q: got %v", path, err)
		}
	}
	_, err := service.GetPage(context.Background(), connect.NewRequest(&screensv1.GetPageRequest{
		Path: "/todos", Query: map[string]string{"path": "/users"},
	}))
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("path in query: got %v", err)
	}
	if len(fetcher.paths) != 0 {
		t.Fatalf("reached the feed: %v", fetcher.paths)
	}
}
