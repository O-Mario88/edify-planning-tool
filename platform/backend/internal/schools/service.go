// Package schools serves edify.schools.v1.SchoolService: the caller's direct
// portfolio, read from the existing `school` table.
package schools

import (
	"context"
	"errors"
	"log/slog"
	"strings"

	"connectrpc.com/connect"

	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	schoolsv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

const (
	// defaultPageSize matches the existing application's table page size.
	defaultPageSize = 50
	maxPageSize     = 200
	maxSearchLength = 100
	maxRefLength    = 64
)

// Reader is the portfolio access the service needs.
type Reader interface {
	List(ctx context.Context, staffProfileID, search string, limit, offset int) ([]School, int64, error)
	Get(ctx context.Context, staffProfileID, ref string) (School, error)
	Facts(ctx context.Context, staffProfileID string) ([]PortfolioFact, error)
}

// Summary is what the analytics worker returns for a portfolio.
type Summary struct {
	SchoolCount           int32
	SchoolsByType         map[string]int32
	SchoolsWithEnrollment int32
	TotalEnrollment       int64
	MedianEnrollment      float64
}

// Summarizer computes descriptive statistics over authorised rows.
type Summarizer interface {
	Summarize(ctx context.Context, facts []PortfolioFact) (Summary, error)
}

// Service implements SchoolService.
type Service struct {
	reader     Reader
	summarizer Summarizer // nil when no analytics worker is configured
	logger     *slog.Logger
}

// NewService wires the service. summarizer may be nil.
func NewService(reader Reader, summarizer Summarizer, logger *slog.Logger) *Service {
	return &Service{reader: reader, summarizer: summarizer, logger: logger}
}

// ListMySchools returns one page of the caller's direct portfolio.
func (s *Service) ListMySchools(
	ctx context.Context, request *connect.Request[schoolsv1.ListMySchoolsRequest],
) (*connect.Response[schoolsv1.ListMySchoolsResponse], error) {
	principal, err := authorize(ctx)
	if err != nil {
		return nil, err
	}
	search := strings.TrimSpace(request.Msg.GetSearch())
	if len(search) > maxSearchLength {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			"The search text is too long.")
	}
	page, pageSize, err := pageOf(ctx, request.Msg.GetPage())
	if err != nil {
		return nil, err
	}

	response := &schoolsv1.ListMySchoolsResponse{
		Page: &commonv1.PageInfo{Page: page, PageSize: pageSize},
	}
	// No staff profile means no assigned schools: an empty portfolio, as in
	// the existing application, not an error.
	if principal.StaffProfileID == "" {
		return connect.NewResponse(response), nil
	}

	offset := int(page-1) * int(pageSize)
	schools, total, err := s.reader.List(ctx, principal.StaffProfileID, search, int(pageSize), offset)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	response.Page.Total = total
	response.Page.TotalPages = int32((total + int64(pageSize) - 1) / int64(pageSize))
	for _, school := range schools {
		response.Schools = append(response.Schools, toProto(school))
	}
	return connect.NewResponse(response), nil
}

// GetMySchool returns one school of the caller's direct portfolio.
func (s *Service) GetMySchool(
	ctx context.Context, request *connect.Request[schoolsv1.GetMySchoolRequest],
) (*connect.Response[schoolsv1.GetMySchoolResponse], error) {
	principal, err := authorize(ctx)
	if err != nil {
		return nil, err
	}
	ref := strings.TrimSpace(request.Msg.GetSchoolRef())
	if ref == "" || len(ref) > maxRefLength {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			"A School ID is required.")
	}
	// "Not yours" and "does not exist" are the same answer, so the gateway
	// never confirms that a school outside the portfolio exists.
	notFound := apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound, "School not found.")
	if principal.StaffProfileID == "" {
		return nil, notFound
	}
	school, err := s.reader.Get(ctx, principal.StaffProfileID, ref)
	if errors.Is(err, ErrNotFound) {
		return nil, notFound
	}
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	return connect.NewResponse(&schoolsv1.GetMySchoolResponse{School: toProto(school)}), nil
}

// GetMyPortfolioSummary returns descriptive statistics of the portfolio. The
// analytics worker computes them; when it cannot be reached the gateway still
// answers with the plain counts and says the analytics were unavailable.
func (s *Service) GetMyPortfolioSummary(
	ctx context.Context, _ *connect.Request[schoolsv1.GetMyPortfolioSummaryRequest],
) (*connect.Response[schoolsv1.GetMyPortfolioSummaryResponse], error) {
	principal, err := authorize(ctx)
	if err != nil {
		return nil, err
	}
	var facts []PortfolioFact
	if principal.StaffProfileID != "" {
		facts, err = s.reader.Facts(ctx, principal.StaffProfileID)
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
	}

	if s.summarizer != nil {
		summary, summarizeErr := s.summarizer.Summarize(ctx, facts)
		if summarizeErr == nil {
			return connect.NewResponse(&schoolsv1.GetMyPortfolioSummaryResponse{
				SchoolCount:           summary.SchoolCount,
				SchoolsByType:         summary.SchoolsByType,
				SchoolsWithEnrollment: summary.SchoolsWithEnrollment,
				TotalEnrollment:       summary.TotalEnrollment,
				MedianEnrollment:      summary.MedianEnrollment,
				AnalyticsAvailable:    true,
			}), nil
		}
		s.logger.WarnContext(ctx, "analytics worker unavailable; answering with plain counts",
			slog.String("error", summarizeErr.Error()))
	}
	return connect.NewResponse(plainCounts(facts)), nil
}

func plainCounts(facts []PortfolioFact) *schoolsv1.GetMyPortfolioSummaryResponse {
	response := &schoolsv1.GetMyPortfolioSummaryResponse{
		SchoolCount:   int32(len(facts)),
		SchoolsByType: map[string]int32{},
	}
	for _, fact := range facts {
		response.SchoolsByType[fact.SchoolType]++
		if fact.Enrollment != nil {
			response.SchoolsWithEnrollment++
			response.TotalEnrollment += int64(*fact.Enrollment)
		}
	}
	return response
}

func pageOf(ctx context.Context, request *commonv1.PageRequest) (page, pageSize int32, err error) {
	page, pageSize = request.GetPage(), request.GetPageSize()
	if page < 0 || pageSize < 0 {
		return 0, 0, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			"The page and page size cannot be negative.")
	}
	if page == 0 {
		page = 1
	}
	if pageSize == 0 {
		pageSize = defaultPageSize
	}
	if pageSize > maxPageSize {
		pageSize = maxPageSize
	}
	return page, pageSize, nil
}

func toProto(school School) *schoolsv1.School {
	return &schoolsv1.School{
		Id:                  school.ID,
		SchoolId:            school.SchoolID,
		Name:                school.Name,
		SchoolType:          school.SchoolType,
		OperationalStatus:   school.OperationalStatus,
		ClusterStatus:       school.ClusterStatus,
		CurrentFySsaStatus:  school.CurrentFYSSAStatus,
		PlanningReadiness:   school.PlanningReadiness,
		Region:              school.Region,
		District:            school.District,
		SubCounty:           school.SubCounty,
		Parish:              school.Parish,
		ClusterId:           school.ClusterID,
		Enrollment:          school.Enrollment,
		SalesforceAccountId: school.SalesforceAccountID,
	}
}
