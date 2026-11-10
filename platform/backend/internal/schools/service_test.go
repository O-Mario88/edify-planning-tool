package schools

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"

	"connectrpc.com/connect"

	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	schoolsv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

type fakeReader struct {
	schools []School
	facts   []PortfolioFact
	err     error

	gotStaff, gotSearch string
	gotLimit, gotOffset int
	calls               int
}

func (f *fakeReader) List(_ context.Context, staff, search string, limit, offset int) ([]School, int64, error) {
	f.calls++
	f.gotStaff, f.gotSearch, f.gotLimit, f.gotOffset = staff, search, limit, offset
	return f.schools, int64(len(f.schools)), f.err
}

func (f *fakeReader) Get(_ context.Context, staff, ref string) (School, error) {
	f.calls++
	f.gotStaff = staff
	for _, school := range f.schools {
		if school.SchoolID == ref || school.ID == ref {
			return school, f.err
		}
	}
	return School{}, ErrNotFound
}

func (f *fakeReader) Facts(context.Context, string) ([]PortfolioFact, error) {
	f.calls++
	return f.facts, f.err
}

type fakeSummarizer struct {
	summary Summary
	err     error
}

func (f fakeSummarizer) Summarize(context.Context, []PortfolioFact) (Summary, error) {
	return f.summary, f.err
}

func quietLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func as(role, staffProfileID string, acting bool) context.Context {
	return auth.WithPrincipal(context.Background(), auth.Principal{Account: auth.Account{
		UserID: "user-1", ActiveRole: role, Status: "active",
		StaffProfileID: staffProfileID, InActingAppointment: acting,
	}})
}

func enrollment(value int32) *int32 { return &value }

func TestAuthorizationDecidesBeforeAnyRead(t *testing.T) {
	tests := []struct {
		name       string
		ctx        context.Context
		wantCode   connect.Code
		wantReason string
	}{
		{name: "no principal", ctx: context.Background(), wantCode: connect.CodeUnauthenticated, wantReason: apierr.ReasonAuthMissing},
		{name: "Country Director", ctx: as("CountryDirector", "staff-1", false), wantCode: connect.CodePermissionDenied, wantReason: apierr.ReasonRoleNotMigrated},
		{name: "Admin", ctx: as("Admin", "", false), wantCode: connect.CodePermissionDenied, wantReason: apierr.ReasonRoleNotMigrated},
		{name: "Impact Assessment", ctx: as("ImpactAssessment", "staff-1", false), wantCode: connect.CodePermissionDenied, wantReason: apierr.ReasonRoleNotMigrated},
		{name: "Partner Admin", ctx: as("PartnerAdmin", "", false), wantCode: connect.CodePermissionDenied, wantReason: apierr.ReasonRoleNotMigrated},
		{name: "role names are exact", ctx: as("cceo", "staff-1", false), wantCode: connect.CodePermissionDenied, wantReason: apierr.ReasonRoleNotMigrated},
		{name: "CCEO in an acting appointment", ctx: as("CCEO", "staff-1", true), wantCode: connect.CodeFailedPrecondition, wantReason: apierr.ReasonActingNotSupported},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			reader := &fakeReader{schools: []School{{ID: "s1", SchoolID: "EDU-1"}}}
			service := NewService(reader, nil, quietLogger())

			_, listErr := service.ListMySchools(test.ctx, connect.NewRequest(&schoolsv1.ListMySchoolsRequest{}))
			_, getErr := service.GetMySchool(test.ctx, connect.NewRequest(&schoolsv1.GetMySchoolRequest{SchoolRef: "EDU-1"}))
			_, sumErr := service.GetMyPortfolioSummary(test.ctx, connect.NewRequest(&schoolsv1.GetMyPortfolioSummaryRequest{}))

			for _, err := range []error{listErr, getErr, sumErr} {
				if connect.CodeOf(err) != test.wantCode || apierr.Reason(err) != test.wantReason {
					t.Fatalf("got %v / %q, want %v / %q", connect.CodeOf(err), apierr.Reason(err), test.wantCode, test.wantReason)
				}
			}
			if reader.calls != 0 {
				t.Fatalf("a refused caller reached the database %d time(s)", reader.calls)
			}
		})
	}
}

func TestListMySchools(t *testing.T) {
	reader := &fakeReader{schools: []School{
		{ID: "s1", SchoolID: "EDU-1", Name: "Alpha", SchoolType: "client", Enrollment: enrollment(120)},
		{ID: "s2", SchoolID: "EDU-2", Name: "Beta", SchoolType: "core"},
	}}
	service := NewService(reader, nil, quietLogger())

	response, err := service.ListMySchools(as("CCEO", "staff-9", false), connect.NewRequest(&schoolsv1.ListMySchoolsRequest{
		Page:   &commonv1.PageRequest{Page: 3, PageSize: 5000},
		Search: "  alp  ",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if reader.gotStaff != "staff-9" || reader.gotSearch != "alp" {
		t.Errorf("read for staff %q search %q", reader.gotStaff, reader.gotSearch)
	}
	if reader.gotLimit != maxPageSize || reader.gotOffset != 2*maxPageSize {
		t.Errorf("limit %d offset %d: the page size must be capped", reader.gotLimit, reader.gotOffset)
	}
	if got := response.Msg.GetSchools(); len(got) != 2 || got[0].GetSchoolId() != "EDU-1" || got[0].GetEnrollment() != 120 {
		t.Errorf("schools: %v", got)
	}
	if response.Msg.GetSchools()[1].Enrollment != nil {
		t.Error("a school without an enrolment figure must not report 0")
	}
	if page := response.Msg.GetPage(); page.GetTotal() != 2 || page.GetTotalPages() != 1 || page.GetPageSize() != maxPageSize {
		t.Errorf("page: %v", page)
	}
}

func TestListMySchoolsDefaultsAndValidation(t *testing.T) {
	reader := &fakeReader{}
	service := NewService(reader, nil, quietLogger())
	ctx := as("Program Lead", "staff-9", false)

	if _, err := service.ListMySchools(ctx, connect.NewRequest(&schoolsv1.ListMySchoolsRequest{})); err != nil {
		t.Fatal(err)
	}
	if reader.gotLimit != defaultPageSize || reader.gotOffset != 0 {
		t.Errorf("defaults: limit %d offset %d", reader.gotLimit, reader.gotOffset)
	}

	_, err := service.ListMySchools(ctx, connect.NewRequest(&schoolsv1.ListMySchoolsRequest{
		Page: &commonv1.PageRequest{Page: -1},
	}))
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Errorf("negative page: %v", err)
	}
	_, err = service.ListMySchools(ctx, connect.NewRequest(&schoolsv1.ListMySchoolsRequest{
		Search: string(make([]byte, maxSearchLength+1)),
	}))
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Errorf("long search: %v", err)
	}
}

func TestAccountWithoutStaffProfileHasAnEmptyPortfolio(t *testing.T) {
	reader := &fakeReader{schools: []School{{ID: "s1", SchoolID: "EDU-1"}}}
	service := NewService(reader, nil, quietLogger())
	ctx := as("CCEO", "", false)

	list, err := service.ListMySchools(ctx, connect.NewRequest(&schoolsv1.ListMySchoolsRequest{}))
	if err != nil || len(list.Msg.GetSchools()) != 0 {
		t.Fatalf("want an empty list, got %v / %v", list, err)
	}
	_, err = service.GetMySchool(ctx, connect.NewRequest(&schoolsv1.GetMySchoolRequest{SchoolRef: "EDU-1"}))
	if connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("want not found, got %v", err)
	}
	if reader.calls != 0 {
		t.Fatalf("no staff profile must not query with an empty id (%d calls)", reader.calls)
	}
}

func TestGetMySchool(t *testing.T) {
	reader := &fakeReader{schools: []School{{ID: "s1", SchoolID: "EDU-1", Name: "Alpha"}}}
	service := NewService(reader, nil, quietLogger())
	ctx := as("CCEO", "staff-9", false)

	found, err := service.GetMySchool(ctx, connect.NewRequest(&schoolsv1.GetMySchoolRequest{SchoolRef: " EDU-1 "}))
	if err != nil || found.Msg.GetSchool().GetName() != "Alpha" {
		t.Fatalf("got %v / %v", found, err)
	}

	_, err = service.GetMySchool(ctx, connect.NewRequest(&schoolsv1.GetMySchoolRequest{SchoolRef: "EDU-OTHER"}))
	if connect.CodeOf(err) != connect.CodeNotFound || apierr.Reason(err) != apierr.ReasonSchoolNotFound {
		t.Fatalf("another person's school must be not found, got %v", err)
	}
	_, err = service.GetMySchool(ctx, connect.NewRequest(&schoolsv1.GetMySchoolRequest{}))
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("empty reference: %v", err)
	}
}

func TestStoreFailuresAreHidden(t *testing.T) {
	reader := &fakeReader{err: errors.New(`pq: relation "school" at 10.0.0.5 unreachable`)}
	service := NewService(reader, nil, quietLogger())

	_, err := service.ListMySchools(as("CCEO", "staff-9", false), connect.NewRequest(&schoolsv1.ListMySchoolsRequest{}))
	if connect.CodeOf(err) != connect.CodeInternal || apierr.Reason(err) != apierr.ReasonInternal {
		t.Fatalf("got %v", err)
	}
	var connectErr *connect.Error
	if errors.As(err, &connectErr); connectErr.Message() == reader.err.Error() {
		t.Fatal("the database error reached the client")
	}
}

func TestPortfolioSummary(t *testing.T) {
	facts := []PortfolioFact{
		{SchoolType: "client", Enrollment: enrollment(100)},
		{SchoolType: "client"},
		{SchoolType: "core", Enrollment: enrollment(300)},
	}
	ctx := as("CCEO", "staff-9", false)
	request := connect.NewRequest(&schoolsv1.GetMyPortfolioSummaryRequest{})

	t.Run("worker answers", func(t *testing.T) {
		worker := fakeSummarizer{summary: Summary{SchoolCount: 3, MedianEnrollment: 200, TotalEnrollment: 400}}
		response, err := NewService(&fakeReader{facts: facts}, worker, quietLogger()).GetMyPortfolioSummary(ctx, request)
		if err != nil {
			t.Fatal(err)
		}
		if !response.Msg.GetAnalyticsAvailable() || response.Msg.GetMedianEnrollment() != 200 {
			t.Fatalf("got %v", response.Msg)
		}
	})

	for name, summarizer := range map[string]Summarizer{
		"worker down":          fakeSummarizer{err: errors.New("unavailable")},
		"no worker configured": nil,
	} {
		t.Run(name, func(t *testing.T) {
			response, err := NewService(&fakeReader{facts: facts}, summarizer, quietLogger()).GetMyPortfolioSummary(ctx, request)
			if err != nil {
				t.Fatalf("the gateway must still answer: %v", err)
			}
			message := response.Msg
			if message.GetAnalyticsAvailable() || message.GetSchoolCount() != 3 ||
				message.GetSchoolsByType()["client"] != 2 || message.GetSchoolsWithEnrollment() != 2 ||
				message.GetTotalEnrollment() != 400 || message.GetMedianEnrollment() != 0 {
				t.Fatalf("got %v", message)
			}
		})
	}
}

func TestLikePattern(t *testing.T) {
	tests := map[string]string{
		"":         "",
		"   ":      "",
		"st mary":  "%st mary%",
		"50%":      `%50\%%`,
		"a_b":      `%a\_b%`,
		`back\sla`: `%back\\sla%`,
	}
	for input, want := range tests {
		if got := likePattern(input); got != want {
			t.Errorf("likePattern(%q) = %q, want %q", input, got, want)
		}
	}
}
