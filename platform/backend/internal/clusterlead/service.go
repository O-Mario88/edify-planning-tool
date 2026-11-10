package clusterlead

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"sync/atomic"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

const (
	// zoneName is the existing application's day (settings TIME_ZONE): an
	// assignment is live, and an activity upcoming, by the local date.
	zoneName        = "Africa/Kampala"
	defaultPageSize = 50
	maxPageSize     = 200
	maxSearchLength = 100
	maxIDLength     = 64
	maxReasonLength = 500
	upcomingLimit   = 10
	isoDate         = "2006-01-02"
)

// Data is what the service reads and writes; *Store implements it.
type Data interface {
	LiveAssignments(ctx context.Context, userID string, day time.Time) ([]Assignment, error)
	Cluster(ctx context.Context, clusterID string) (Cluster, error)
	MemberSchools(ctx context.Context, clusterID, search string, limit, offset int) ([]School, int64, error)
	UpcomingActivities(ctx context.Context, clusterID string, day time.Time, limit int) ([]Activity, error)
	ManagedClusters(ctx context.Context, staffID, search string, day time.Time, limit, offset int) ([]ManagedCluster, int64, error)
	ClusterAssignments(ctx context.Context, clusterID string) ([]Assignment, error)
	Assignment(ctx context.Context, id string) (Assignment, error)
	Candidates(ctx context.Context) ([]Account, error)
	Account(ctx context.Context, userID string) (Account, error)
	CreateAssignment(ctx context.Context, a NewAssignment) error
	EndAssignment(ctx context.Context, id, actorID, reason string, day time.Time) error
	ReplaceAssignment(ctx context.Context, id string, next NewAssignment, day time.Time) error
}

// Service implements ClusterLeadershipService.
type Service struct {
	data     Data
	now      func() time.Time
	location *time.Location
	// ready reports whether the portal's schema is at this build's version;
	// nil skips the check (tests). Once ready, it is not asked again.
	ready   func(context.Context) error
	isReady atomic.Bool
	logger  *slog.Logger
}

// NewService wires the service. ready may be nil.
func NewService(data Data, now func() time.Time, ready func(context.Context) error, logger *slog.Logger) *Service {
	if now == nil {
		now = time.Now
	}
	location, err := time.LoadLocation(zoneName)
	if err != nil {
		// No zone database on the host: Uganda keeps UTC+3 all year.
		location = time.FixedZone(zoneName, 3*60*60)
	}
	return &Service{data: data, now: now, location: location, ready: ready, logger: logger}
}

// today is the local calendar day, as a date at midnight UTC.
func (s *Service) today() time.Time {
	local := s.now().In(s.location)
	return time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
}

func (s *Service) checkReady(ctx context.Context) error {
	if s.ready == nil || s.isReady.Load() {
		return nil
	}
	if err := s.ready(ctx); err != nil {
		s.logger.Warn("cluster leadership schema not ready", slog.String("error", err.Error()))
		return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"The Cluster Leader Portal is not set up on this server yet.")
	}
	s.isReady.Store(true)
	return nil
}

// liveFor is the caller's live assignment for clusterID, or the refusal.
func (s *Service) liveFor(ctx context.Context, userID, clusterID string) (Assignment, error) {
	if err := validID(ctx, "cluster", clusterID); err != nil {
		return Assignment{}, err
	}
	live, err := s.data.LiveAssignments(ctx, userID, s.today())
	if err != nil {
		return Assignment{}, s.internal(ctx, err)
	}
	for _, assignment := range live {
		if assignment.ClusterID == clusterID {
			return assignment, nil
		}
	}
	return Assignment{}, notYours(ctx)
}

// GetMyClusters returns the caller's live assignments.
func (s *Service) GetMyClusters(
	ctx context.Context, _ *connect.Request[clustersv1.GetMyClustersRequest],
) (*connect.Response[clustersv1.GetMyClustersResponse], error) {
	principal, err := leader(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.checkReady(ctx); err != nil {
		return nil, err
	}
	live, err := s.data.LiveAssignments(ctx, principal.UserID, s.today())
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &clustersv1.GetMyClustersResponse{}
	for _, assignment := range live {
		summary, err := s.summary(ctx, assignment.ClusterID, &assignment)
		if errors.Is(err, ErrNotFound) {
			continue // the cluster was deleted; the assignment stays as history
		}
		if err != nil {
			return nil, s.internal(ctx, err)
		}
		response.Clusters = append(response.Clusters, summary)
	}
	return connect.NewResponse(response), nil
}

// ListMemberSchools returns one page of the cluster's member schools.
func (s *Service) ListMemberSchools(
	ctx context.Context, request *connect.Request[clustersv1.ListMemberSchoolsRequest],
) (*connect.Response[clustersv1.ListMemberSchoolsResponse], error) {
	principal, err := leader(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.checkReady(ctx); err != nil {
		return nil, err
	}
	if _, err := s.liveFor(ctx, principal.UserID, request.Msg.GetClusterId()); err != nil {
		return nil, err
	}
	search := strings.TrimSpace(request.Msg.GetSearch())
	if len(search) > maxSearchLength {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "The search text is too long.")
	}
	page, size, err := pageOf(ctx, request.Msg.GetPage())
	if err != nil {
		return nil, err
	}
	schools, total, err := s.data.MemberSchools(ctx, request.Msg.GetClusterId(), search, int(size), int((page-1)*size))
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &clustersv1.ListMemberSchoolsResponse{Page: pageInfo(page, size, total)}
	for _, school := range schools {
		response.Schools = append(response.Schools, &clustersv1.MemberSchool{
			Id: school.ID, SchoolId: school.SchoolID, Name: school.Name, SchoolType: school.Type,
			District: school.District, SubCounty: school.SubCounty,
			OperationalStatus: school.OperationalStatus, CurrentFySsaStatus: school.SSAStatus,
		})
	}
	return connect.NewResponse(response), nil
}

// summary is the cluster as a ClusterSummary, with the caller's assignment.
func (s *Service) summary(ctx context.Context, clusterID string, mine *Assignment) (*clustersv1.ClusterSummary, error) {
	cluster, err := s.data.Cluster(ctx, clusterID)
	if err != nil {
		return nil, err
	}
	_, members, err := s.data.MemberSchools(ctx, clusterID, "", 0, 0)
	if err != nil {
		return nil, err
	}
	summary := &clustersv1.ClusterSummary{
		Id: cluster.ID, Name: cluster.Name, Status: cluster.Status, ClusterType: cluster.Type,
		District: cluster.District, SubCounty: cluster.SubCounty,
		MemberSchoolCount: int32(min(members, int64(1<<31-1))), // #nosec G115 -- clamped above
		ResponsibleStaff:  cluster.ResponsibleStaff,
	}
	if mine != nil {
		summary.MyAssignment = toAssignment(*mine)
	}
	return summary, nil
}

func toAssignment(a Assignment) *clustersv1.LeaderAssignment {
	out := &clustersv1.LeaderAssignment{
		Id: a.ID, ClusterId: a.ClusterID, UserId: a.UserID, LeaderName: a.LeaderName,
		LeaderEmail: a.LeaderEmail, StartsOn: a.StartsOn.Format(isoDate), Status: a.Status,
		AssignedBy: a.AssignedBy, Reason: a.Reason, EndedReason: a.EndedReason,
		ReplacesAssignmentId: a.ReplacesID,
	}
	if a.EndsOn != nil {
		out.EndsOn = a.EndsOn.Format(isoDate)
	}
	for _, event := range a.History {
		out.History = append(out.History, &clustersv1.AssignmentEvent{
			Event: event.Event, Actor: event.Actor, Reason: event.Reason, At: event.At.UTC().Format(time.RFC3339),
		})
	}
	return out
}

func pageInfo(page, size int32, total int64) *commonv1.PageInfo {
	pages := int32(0)
	if total > 0 {
		pages = int32(min((total+int64(size)-1)/int64(size), int64(1<<31-1))) // #nosec G115 -- clamped
	}
	return &commonv1.PageInfo{Page: page, PageSize: size, Total: total, TotalPages: pages}
}

func pageOf(ctx context.Context, request *commonv1.PageRequest) (int32, int32, error) {
	page, size := request.GetPage(), request.GetPageSize()
	if page == 0 {
		page = 1
	}
	if size == 0 {
		size = defaultPageSize
	}
	if page < 1 || size < 1 || size > maxPageSize {
		return 0, 0, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			fmt.Sprintf("Pages are numbered from 1 and hold 1 to %d rows.", maxPageSize))
	}
	return page, size, nil
}

func validID(ctx context.Context, what, id string) error {
	if id == "" || len(id) > maxIDLength {
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			fmt.Sprintf("A %s id is required.", what))
	}
	return nil
}

func (s *Service) internal(ctx context.Context, err error) error {
	s.logger.Error("cluster leadership request failed", slog.String("error", err.Error()))
	return apierr.New(ctx, connect.CodeInternal, apierr.ReasonInternal, "Something went wrong. Try again.")
}

// newID is a random (version 4) UUID.
func newID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	h := hex.EncodeToString(b[:])
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:], nil
}
