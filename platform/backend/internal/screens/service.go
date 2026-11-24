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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/home"
	"log/slog"
	"net/url"
	"strconv"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5/pgxpool"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fieldops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/financeops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workforceops"
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

// Home builds Home in Go (internal/home). served is false for a reader the
// existing application still answers.
type Home interface {
	Build(ctx context.Context, p auth.Principal) (*screensv1.GetHomeResponse, bool, error)
	BuildQueue(ctx context.Context, p auth.Principal) (*screensv1.GetHomeQueueResponse, bool, error)
	BuildTodoFigures(ctx context.Context, p auth.Principal) (*screensv1.GetHomeTodoFiguresResponse, bool, error)
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
	home        Home // nil unless Home is built in Go (internal/home)
	pages       []Pages
	navigation  Navigation     // nil unless the navigation is built in Go (internal/navigation)
	visits      VisitSaver     // nil unless EDIFY_GO_SAVES names schedule_visit or schedule_training_pair
	visitsInGo  bool           // schedule_visit: 27.3's visits
	coreVisits  CoreVisitSaver // the Core Schools visit form, with Django absent
	// visitDecisions is a school owner's decision on a visit request, with Django absent.
	visitDecisions VisitDecider
	// starter is Start activity, with Django absent.
	starter ActivityStarter
	// weekOwner is the owner's weekly request buttons, with Django absent.
	weekOwner WeekOwner
	// accountant is the officer's accountability drawer, with Django absent.
	accountant Accountant
	// reimburser is Confirm reimbursement receipt, with Django absent.
	reimburser Reimburser
	// dailyDebrief is the Daily Debrief's form, with Django absent.
	dailyDebrief DailyDebriefer
	// extraWork is Extra Assigned Work's saves, with Django absent.
	extraWork ExtraWorker
	// enroller is Add to Project's save, with Django absent.
	enroller Enroller
	// clientAssign is the Planning drawer's Assign to Partner, with Django absent.
	clientAssign ClientAssigner
	// bulkSchedule is a list's tick-bar Schedule, with Django absent.
	bulkSchedule BulkScheduler
	// bulkAssign is a list's tick-bar Assign to partner, with Django absent.
	bulkAssign BulkAssigner
	pairsInGo  bool // schedule_training_pair: 32's In-school Training
	// groupTrainings is nil unless EDIFY_GO_SAVES names schedule_group_training (38).
	groupTrainings GroupTrainingSaver
	// clusterMeetings is nil unless EDIFY_GO_SAVES names schedule_cluster_meeting (49).
	clusterMeetings ClusterMeetingSaver
	moves           MoveSaver     // nil unless EDIFY_GO_SAVES names reschedule_visit
	cancels         CancelSaver   // nil unless EDIFY_GO_SAVES names cancel_visit
	edits           EditSaver     // nil unless EDIFY_GO_SAVES names edit_visit
	completions     CompleteSaver // nil unless EDIFY_GO_SAVES names complete_visit (183)
	plReviews       PLReviewer    // nil unless EDIFY_GO_SAVES names pl_review (M9)
	// groupMoves and groupCancels: nil unless EDIFY_GO_SAVES names
	// group_reschedule or group_cancel (docs/migration/33).
	groupMoves   GroupMoveSaver
	groupCancels GroupCancelSaver
	logger       *slog.Logger
	// presence stamps a save when no existing application is there to do it.
	presence PresenceStamper
	// trustProxy reads a page reader's address from X-Forwarded-For, for an
	// audited read behind the platform's load balancer.
	trustProxy bool
	// strictReads refuses handing reads back to the existing application even
	// when existingApp is configured (for saves).
	strictReads bool
	// fallbacks counts every attempted call to the existing application.
	fallbacks *FallbackTracker
	// exports serves ExportService.GetExport natively from Go.
	exports ExportStore
	// Native Go operational domain writers wired into SaveDrawer (Batch 21).
	fieldOps     *fieldops.Service
	financeOps   *financeops.Service
	workforceOps *workforceops.Service
	// Direct PostgreSQL pool + clock for native Go school actions & drawers (Batches 22-23).
	db  *pgxpool.Pool
	now func() time.Time
}

// NewService wires the service. existingApp may be nil.
func NewService(existingApp Fetcher) *Service {
	return &Service{existingApp: existingApp, fallbacks: NewFallbackTracker()}
}

// WithFallbackTracker installs a custom fallback tracker (for tests and
// acceptance rehearsals).
func (s *Service) WithFallbackTracker(tracker *FallbackTracker) *Service {
	s.fallbacks = tracker
	return s
}

// FallbackCounts returns a snapshot of all attempted Django calls recorded on
// this service.
func (s *Service) FallbackCounts() map[FallbackKey]int64 {
	return s.fallbacks.Counts()
}

// WithStrictReads refuses any read hand-on to the existing application when
// strict is true. Saves still forward through existingApp as before.
func (s *Service) WithStrictReads(strict bool) *Service {
	s.strictReads = strict
	return s
}

// TrustProxyHeaders reads a page reader's address from X-Forwarded-For (the
// platform's load balancer sets it), as sign-in does.
func (s *Service) TrustProxyHeaders(trust bool) *Service {
	s.trustProxy = trust
	return s
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

// WithHome answers Home in Go for the readers internal/home serves; anyone
// else's Home is passed to the existing application.
func (s *Service) WithHome(home Home, logger *slog.Logger) *Service {
	s.home, s.logger = home, logger
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
	if s.strictReads || s.existingApp == nil {
		s.fallbacks.Record(ctx, s.logger, "GET", path, FallbackBlocked)
		return nil, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"This screen is not available here yet. Use the Edify web app.")
	}
	message := new(T)
	if err := s.existingApp.Get(ctx, path, M(message)); err != nil {
		s.fallbacks.Record(ctx, s.logger, "GET", path, FallbackFailed)
		return nil, err
	}
	s.fallbacks.Record(ctx, s.logger, "GET", path, FallbackForwarded)
	return connect.NewResponse(message), nil
}

// GetHome returns Home without its queue: from Go for a reader it serves
// (internal/home), else from the existing application.
func (s *Service) GetHome(
	ctx context.Context, _ *connect.Request[screensv1.GetHomeRequest],
) (*connect.Response[screensv1.GetHomeResponse], error) {
	if principal, ok := auth.PrincipalFrom(ctx); ok && s.home != nil {
		response, served, err := s.home.Build(ctx, principal)
		if errors.Is(err, home.ErrForbidden) {
			// require_page's refusal, as the existing feed gives it.
			return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
				"Your role does not have permission to view this.")
		}
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
		if served {
			return connect.NewResponse(response), nil
		}
	}
	return fetch[screensv1.GetHomeResponse](ctx, s, pathHome)
}

// GetHomeQueue returns Home's Priority actions: from Go for a reader it
// serves (internal/home), else from the existing application.
func (s *Service) GetHomeQueue(
	ctx context.Context, _ *connect.Request[screensv1.GetHomeQueueRequest],
) (*connect.Response[screensv1.GetHomeQueueResponse], error) {
	if principal, ok := auth.PrincipalFrom(ctx); ok && s.home != nil {
		response, served, err := s.home.BuildQueue(ctx, principal)
		if errors.Is(err, home.ErrForbidden) {
			// require_page's refusal, as the existing feed gives it.
			return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
				"Your role does not have permission to view this.")
		}
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
		if served {
			return connect.NewResponse(response), nil
		}
	}
	return fetch[screensv1.GetHomeQueueResponse](ctx, s, pathHomeQueue)
}

// GetHomeTodoFigures returns Home's To-Do figures: from Go for a reader it
// serves (internal/home), else from the existing application.
func (s *Service) GetHomeTodoFigures(
	ctx context.Context, _ *connect.Request[screensv1.GetHomeTodoFiguresRequest],
) (*connect.Response[screensv1.GetHomeTodoFiguresResponse], error) {
	if principal, ok := auth.PrincipalFrom(ctx); ok && s.home != nil {
		response, served, err := s.home.BuildTodoFigures(ctx, principal)
		if errors.Is(err, home.ErrForbidden) {
			// require_page's refusal, as the existing feed gives it.
			return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
				"Your role does not have permission to view this.")
		}
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
		if served {
			return connect.NewResponse(response), nil
		}
	}
	return fetch[screensv1.GetHomeTodoFiguresResponse](ctx, s, pathHomeTodoFigures)
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
		s.fallbacks.Record(ctx, s.logger, "POST", path, FallbackBlocked)
		return nil, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"This action is not available here yet. Use the Edify web app.")
	}
	message := new(T)
	if err := s.existingApp.Post(ctx, path, in, M(message)); err != nil {
		s.fallbacks.Record(ctx, s.logger, "POST", path, FallbackFailed)
		return nil, err
	}
	s.fallbacks.Record(ctx, s.logger, "POST", path, FallbackForwarded)
	return connect.NewResponse(message), nil
}

// GetAddToCluster returns the Add to Cluster form for a school.
func (s *Service) GetAddToCluster(
	ctx context.Context, request *connect.Request[screensv1.GetAddToClusterRequest],
) (*connect.Response[screensv1.GetAddToClusterResponse], error) {
	if err := requireSchool(ctx, request.Msg.GetSchoolId()); err != nil {
		return nil, err
	}
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.getAddToClusterInGo(ctx, p, request.Msg.GetSchoolId()); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
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
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.addToClusterInGo(ctx, p, request.Msg); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
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
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.getAddToProjectInGo(ctx, p, request.Msg.GetSchoolId()); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
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
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.addToProjectInGo(ctx, p, request.Msg); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
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
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.bulkAssignClusterInGo(ctx, p, request.Msg); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
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
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.bulkAssignProjectInGo(ctx, p, request.Msg); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
	}
	return send[screensv1.BulkAssignProjectResponse](ctx, s, "/api/mobile/v1/schools/bulk-assign-project", request.Msg)
}
