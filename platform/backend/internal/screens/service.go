// Package screens serves the screens whose rules still live in the existing
// application: it asks that application for the page's view-model, with the
// caller's own token, and returns it through the contract.
//
// The app never sees the difference. When a screen's rules are ported, its
// handler here is replaced by a Go module and the contract stays the same.
package screens

import (
	"context"
	"errors"
	"log/slog"
	"net/url"
	"strconv"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

const (
	pathHome            = "/api/mobile/v1/home"
	pathHomeQueue       = "/api/mobile/v1/home/queue"
	pathHomeTodoFigures = "/api/mobile/v1/home/todo-figures"
	pathNavigation      = "/api/mobile/v1/navigation"
	pathSchoolDirectory = "/api/mobile/v1/school-directory"
)

// Fetcher reads one screen's view-model from the existing application into
// out. Its errors are already structured API errors.
type Fetcher interface {
	Get(ctx context.Context, path string, out proto.Message) error
	Post(ctx context.Context, path string, in, out proto.Message) error
}

// Directory builds the School Directory in Go (internal/schooldirectory).
type Directory interface {
	Build(ctx context.Context, p auth.Principal, req *screensv1.GetSchoolDirectoryRequest) (*screensv1.GetSchoolDirectoryResponse, error)
}

// Profile builds school profiles in Go (internal/schoolprofile). served is
// false for what the existing application still answers.
type Profile interface {
	Build(ctx context.Context, p auth.Principal, req *screensv1.GetSchoolProfileRequest) (*screensv1.GetSchoolProfileResponse, bool, error)
}

// Pages builds pages in Go (internal/clusterpage and the ones beside it).
// served is false for a path the builder does not answer; a page refused to
// the reader is pagegate.ErrNotAvailable.
type Pages interface {
	Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error)
}

// Service implements HomeScreenService, NavigationService,
// SchoolDirectoryScreenService and SchoolProfileService.
type Service struct {
	existingApp Fetcher // nil when no existing application is configured
	directory   Directory
	profile     Profile
	pages       []Pages
	visits      VisitSaver  // nil unless EDIFY_GO_SAVES names schedule_visit or schedule_training_pair
	visitsInGo  bool        // schedule_visit: 27.3's visits
	pairsInGo   bool        // schedule_training_pair: 32's In-school Training
	moves       MoveSaver   // nil unless EDIFY_GO_SAVES names reschedule_visit
	cancels     CancelSaver // nil unless EDIFY_GO_SAVES names cancel_visit
	edits       EditSaver   // nil unless EDIFY_GO_SAVES names edit_visit
	logger      *slog.Logger
}

// NewService wires the service. existingApp may be nil.
func NewService(existingApp Fetcher) *Service {
	return &Service{existingApp: existingApp}
}

// WithDirectory answers the School Directory in Go for anyone working in
// their own role. Someone working in an acting capacity is still answered by
// the existing application, which presents them in the acting seat.
func (s *Service) WithDirectory(directory Directory, logger *slog.Logger) *Service {
	s.directory, s.logger = directory, logger
	return s
}

// WithProfile answers what Go has taken over of school profiles, for anyone
// working in their own role; the rest is passed to the existing application.
func (s *Service) WithProfile(profile Profile, logger *slog.Logger) *Service {
	s.profile, s.logger = profile, logger
	return s
}

// WithPages answers the pages Go has taken over, for anyone working in
// their own role: each builder is asked in turn, and a path none of them
// answers is passed to the existing application.
func (s *Service) WithPages(logger *slog.Logger, pages ...Pages) *Service {
	s.pages, s.logger = append(s.pages, pages...), logger
	return s
}

func fetch[T any, M interface {
	*T
	proto.Message
}](ctx context.Context, s *Service, path string) (*connect.Response[T], error) {
	if s.existingApp == nil {
		return nil, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"This screen is not available here yet. Use the Edify web app.")
	}
	message := new(T)
	if err := s.existingApp.Get(ctx, path, M(message)); err != nil {
		return nil, err
	}
	return connect.NewResponse(message), nil
}

// GetHome returns Home without its queue.
func (s *Service) GetHome(
	ctx context.Context, _ *connect.Request[screensv1.GetHomeRequest],
) (*connect.Response[screensv1.GetHomeResponse], error) {
	return fetch[screensv1.GetHomeResponse](ctx, s, pathHome)
}

// GetHomeQueue returns Home's Priority actions.
func (s *Service) GetHomeQueue(
	ctx context.Context, _ *connect.Request[screensv1.GetHomeQueueRequest],
) (*connect.Response[screensv1.GetHomeQueueResponse], error) {
	return fetch[screensv1.GetHomeQueueResponse](ctx, s, pathHomeQueue)
}

// GetHomeTodoFigures returns Home's To-Do figures.
func (s *Service) GetHomeTodoFigures(
	ctx context.Context, _ *connect.Request[screensv1.GetHomeTodoFiguresRequest],
) (*connect.Response[screensv1.GetHomeTodoFiguresResponse], error) {
	return fetch[screensv1.GetHomeTodoFiguresResponse](ctx, s, pathHomeTodoFigures)
}

// GetNavigation returns the caller's bottom bar and menu.
func (s *Service) GetNavigation(
	ctx context.Context, _ *connect.Request[screensv1.GetNavigationRequest],
) (*connect.Response[screensv1.GetNavigationResponse], error) {
	return fetch[screensv1.GetNavigationResponse](ctx, s, pathNavigation)
}

// GetSchoolDirectory returns the School Directory for the page's own query.
func (s *Service) GetSchoolDirectory(
	ctx context.Context, request *connect.Request[screensv1.GetSchoolDirectoryRequest],
) (*connect.Response[screensv1.GetSchoolDirectoryResponse], error) {
	if principal, ok := auth.PrincipalFrom(ctx); ok && s.directory != nil && !principal.InActingAppointment {
		response, err := s.directory.Build(ctx, principal, request.Msg)
		if errors.Is(err, schooldirectory.ErrForbidden) {
			return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, err.Error())
		}
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
		return connect.NewResponse(response), nil
	}
	message := request.Msg
	query := url.Values{}
	for key, value := range map[string]string{
		"q":              message.GetQ(),
		"fy":             message.GetFy(),
		"district":       message.GetDistrict(),
		"sub_county":     message.GetSubCounty(),
		"school_type":    message.GetSchoolType(),
		"cluster_status": message.GetClusterStatus(),
		"project_status": message.GetProjectStatus(),
		"gap":            message.GetGap(),
		"tab":            message.GetTab(),
	} {
		if value != "" {
			query.Set(key, value)
		}
	}
	if message.GetPage() > 0 {
		query.Set("page", strconv.Itoa(int(message.GetPage())))
	}
	path := pathSchoolDirectory
	if len(query) > 0 {
		path += "?" + query.Encode()
	}
	return fetch[screensv1.GetSchoolDirectoryResponse](ctx, s, path)
}

// GetSchoolProfile returns a school's profile for the page's own query.
func (s *Service) GetSchoolProfile(
	ctx context.Context, request *connect.Request[screensv1.GetSchoolProfileRequest],
) (*connect.Response[screensv1.GetSchoolProfileResponse], error) {
	message := request.Msg
	if err := requireSchool(ctx, message.GetSchoolId()); err != nil {
		return nil, err
	}
	if principal, ok := auth.PrincipalFrom(ctx); ok && s.profile != nil && !principal.InActingAppointment {
		response, served, err := s.profile.Build(ctx, principal, message)
		switch {
		case errors.Is(err, schoolprofile.ErrForbidden):
			return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
				"Your role does not have permission to view this.")
		case errors.Is(err, schoolprofile.ErrNotFound):
			return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound,
				"This was not found, or it is not yours to view.")
		case err != nil:
			return nil, apierr.Internal(ctx, s.logger, err)
		case served:
			return connect.NewResponse(response), nil
		}
	}
	query := url.Values{}
	for key, value := range map[string]string{
		"tab":    message.GetTab(),
		"fy":     message.GetFy(),
		"period": message.GetPeriod(),
	} {
		if value != "" {
			query.Set(key, value)
		}
	}
	path := schoolPath(message.GetSchoolId(), "profile")
	if len(query) > 0 {
		path += "?" + query.Encode()
	}
	return fetch[screensv1.GetSchoolProfileResponse](ctx, s, path)
}

// schoolPath is the feed path of one action on one school.
func schoolPath(schoolID, action string) string {
	return "/api/mobile/v1/schools/" + url.PathEscape(schoolID) + "/" + action
}

func requireSchool(ctx context.Context, schoolID string) error {
	if schoolID == "" || len(schoolID) > maxSchoolIDLength {
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "A school is required.")
	}
	return nil
}

const maxSchoolIDLength = 64

func send[T any, M interface {
	*T
	proto.Message
}](ctx context.Context, s *Service, path string, in proto.Message) (*connect.Response[T], error) {
	if s.existingApp == nil {
		return nil, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"This action is not available here yet. Use the Edify web app.")
	}
	message := new(T)
	if err := s.existingApp.Post(ctx, path, in, M(message)); err != nil {
		return nil, err
	}
	return connect.NewResponse(message), nil
}

// GetAddToCluster returns the Add to Cluster form for a school.
func (s *Service) GetAddToCluster(
	ctx context.Context, request *connect.Request[screensv1.GetAddToClusterRequest],
) (*connect.Response[screensv1.GetAddToClusterResponse], error) {
	if err := requireSchool(ctx, request.Msg.GetSchoolId()); err != nil {
		return nil, err
	}
	return fetch[screensv1.GetAddToClusterResponse](ctx, s, schoolPath(request.Msg.GetSchoolId(), "add-to-cluster"))
}

// AddToCluster adds the school to a cluster, or moves it.
func (s *Service) AddToCluster(
	ctx context.Context, request *connect.Request[screensv1.AddToClusterRequest],
) (*connect.Response[screensv1.AddToClusterResponse], error) {
	if err := requireSchool(ctx, request.Msg.GetSchoolId()); err != nil {
		return nil, err
	}
	return send[screensv1.AddToClusterResponse](ctx, s, schoolPath(request.Msg.GetSchoolId(), "add-to-cluster"), request.Msg)
}

// GetAddToProject returns the Add to Project form for a school.
func (s *Service) GetAddToProject(
	ctx context.Context, request *connect.Request[screensv1.GetAddToProjectRequest],
) (*connect.Response[screensv1.GetAddToProjectResponse], error) {
	if err := requireSchool(ctx, request.Msg.GetSchoolId()); err != nil {
		return nil, err
	}
	return fetch[screensv1.GetAddToProjectResponse](ctx, s, schoolPath(request.Msg.GetSchoolId(), "add-to-project"))
}

// AddToProject adds the school to a project.
func (s *Service) AddToProject(
	ctx context.Context, request *connect.Request[screensv1.AddToProjectRequest],
) (*connect.Response[screensv1.AddToProjectResponse], error) {
	if err := requireSchool(ctx, request.Msg.GetSchoolId()); err != nil {
		return nil, err
	}
	return send[screensv1.AddToProjectResponse](ctx, s, schoolPath(request.Msg.GetSchoolId(), "add-to-project"), request.Msg)
}

// maxBulkSchools bounds one bulk save; a directory page holds 50.
const maxBulkSchools = 500

func requireTicked(ctx context.Context, ids []string) error {
	if len(ids) > maxBulkSchools {
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			"Too many schools are ticked for one save.")
	}
	return nil
}

// BulkAssignCluster assigns the ticked schools to one cluster.
func (s *Service) BulkAssignCluster(
	ctx context.Context, request *connect.Request[screensv1.BulkAssignClusterRequest],
) (*connect.Response[screensv1.BulkAssignClusterResponse], error) {
	if err := requireTicked(ctx, request.Msg.GetSchoolIds()); err != nil {
		return nil, err
	}
	return send[screensv1.BulkAssignClusterResponse](ctx, s, "/api/mobile/v1/schools/bulk-assign-cluster", request.Msg)
}

// BulkAssignProject adds the ticked schools to one project.
func (s *Service) BulkAssignProject(
	ctx context.Context, request *connect.Request[screensv1.BulkAssignProjectRequest],
) (*connect.Response[screensv1.BulkAssignProjectResponse], error) {
	if err := requireTicked(ctx, request.Msg.GetSchoolIds()); err != nil {
		return nil, err
	}
	return send[screensv1.BulkAssignProjectResponse](ctx, s, "/api/mobile/v1/schools/bulk-assign-project", request.Msg)
}
