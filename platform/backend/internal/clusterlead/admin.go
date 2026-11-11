package clusterlead

import (
	"context"
	"errors"
	"strings"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// administered is the cluster when the caller may manage its leaders.
func (s *Service) administered(ctx context.Context, clusterID string) (auth.Principal, Cluster, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return auth.Principal{}, Cluster{}, err
	}
	if err := s.checkReady(ctx); err != nil {
		return auth.Principal{}, Cluster{}, err
	}
	if err := validID(ctx, "cluster", clusterID); err != nil {
		return auth.Principal{}, Cluster{}, err
	}
	cluster, err := s.data.Cluster(ctx, clusterID)
	if errors.Is(err, ErrNotFound) {
		return auth.Principal{}, Cluster{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such cluster.")
	}
	if err != nil {
		return auth.Principal{}, Cluster{}, s.internal(ctx, err)
	}
	if !mayAdminister(principal, cluster) {
		return auth.Principal{}, Cluster{}, notAdministrator(ctx)
	}
	return principal, cluster, nil
}

// ListManagedClusters returns the clusters whose leaders the caller may
// manage: all of them for Admin and Program Lead, a CCEO's own.
func (s *Service) ListManagedClusters(
	ctx context.Context, request *connect.Request[clustersv1.ListManagedClustersRequest],
) (*connect.Response[clustersv1.ListManagedClustersResponse], error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.checkReady(ctx); err != nil {
		return nil, err
	}
	var ownerIDs []string
	switch {
	case anyClusterAdministrators[principal.ActiveRole]:
	case principal.ActiveRole == roleCCEO && principal.StaffProfileID != "":
		ownerIDs = ownIDs(principal)
	default:
		return nil, notAdministrator(ctx)
	}
	search := strings.TrimSpace(request.Msg.GetSearch())
	if len(search) > maxSearchLength {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "The search text is too long.")
	}
	page, size, err := pageOf(ctx, request.Msg.GetPage())
	if err != nil {
		return nil, err
	}
	clusters, total, err := s.data.ManagedClusters(ctx, ownerIDs, search, s.today(), int(size), int((page-1)*size))
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &clustersv1.ListManagedClustersResponse{Page: pageInfo(page, size, total)}
	for _, m := range clusters {
		response.Clusters = append(response.Clusters, &clustersv1.ManagedCluster{
			Cluster: &clustersv1.ClusterSummary{
				Id: m.ID, Name: m.Name, Status: m.Status, ClusterType: m.Type, District: m.District,
				SubCounty: m.SubCounty, ResponsibleStaff: m.ResponsibleStaff,
				MemberSchoolCount: int32(min(m.Members, int64(1<<31-1))), // #nosec G115 -- clamped
			},
			LiveLeaders: m.Leaders,
		})
	}
	return connect.NewResponse(response), nil
}

// ListLeaders returns the cluster's assignments, live and past.
func (s *Service) ListLeaders(
	ctx context.Context, request *connect.Request[clustersv1.ListLeadersRequest],
) (*connect.Response[clustersv1.ListLeadersResponse], error) {
	_, cluster, err := s.administered(ctx, request.Msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	summary, err := s.summary(ctx, cluster.ID, nil)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	assignments, err := s.data.ClusterAssignments(ctx, cluster.ID)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	candidates, err := s.data.Candidates(ctx)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &clustersv1.ListLeadersResponse{Cluster: summary}
	for _, assignment := range assignments {
		response.Assignments = append(response.Assignments, toAssignment(assignment))
	}
	for _, candidate := range candidates {
		response.Candidates = append(response.Candidates, &clustersv1.LeaderCandidate{
			UserId: candidate.UserID, Name: candidate.Name, Email: candidate.Email,
		})
	}
	return connect.NewResponse(response), nil
}

// AssignLeader gives the cluster to an existing Cluster Leader account.
func (s *Service) AssignLeader(
	ctx context.Context, request *connect.Request[clustersv1.AssignLeaderRequest],
) (*connect.Response[clustersv1.AssignLeaderResponse], error) {
	principal, cluster, err := s.administered(ctx, request.Msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	if err := s.requireLeaderAccount(ctx, request.Msg.GetUserId()); err != nil {
		return nil, err
	}
	startsOn, endsOn, err := s.span(ctx, request.Msg.GetStartsOn(), request.Msg.GetEndsOn())
	if err != nil {
		return nil, err
	}
	reason, err := reasonOf(ctx, request.Msg.GetReason())
	if err != nil {
		return nil, err
	}
	id, err := newID()
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	err = s.data.CreateAssignment(ctx, NewAssignment{
		ID: id, ClusterID: cluster.ID, UserID: request.Msg.GetUserId(),
		StartsOn: startsOn, EndsOn: endsOn, ActorID: principal.UserID, Reason: reason,
	})
	if errors.Is(err, ErrAlreadyAssigned) {
		return nil, apierr.New(ctx, connect.CodeAlreadyExists, apierr.ReasonInvalidArgument,
			"This person already leads this cluster.")
	}
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	created, err := s.data.Assignment(ctx, id)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.AssignLeaderResponse{Assignment: toAssignment(created)}), nil
}

// EndAssignment ends a live assignment, keeping it and its history.
func (s *Service) EndAssignment(
	ctx context.Context, request *connect.Request[clustersv1.EndAssignmentRequest],
) (*connect.Response[clustersv1.EndAssignmentResponse], error) {
	assignment, principal, err := s.administeredAssignment(ctx, request.Msg.GetAssignmentId())
	if err != nil {
		return nil, err
	}
	reason, err := reasonOf(ctx, request.Msg.GetReason())
	if err != nil {
		return nil, err
	}
	if err := s.data.EndAssignment(ctx, assignment.ID, principal.UserID, reason, s.today()); err != nil {
		return nil, s.writeError(ctx, err)
	}
	ended, err := s.data.Assignment(ctx, assignment.ID)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.EndAssignmentResponse{Assignment: toAssignment(ended)}), nil
}

// ReplaceLeader ends one assignment and gives the cluster to another leader.
func (s *Service) ReplaceLeader(
	ctx context.Context, request *connect.Request[clustersv1.ReplaceLeaderRequest],
) (*connect.Response[clustersv1.ReplaceLeaderResponse], error) {
	old, principal, err := s.administeredAssignment(ctx, request.Msg.GetAssignmentId())
	if err != nil {
		return nil, err
	}
	newUserID := request.Msg.GetNewUserId()
	if newUserID == old.UserID {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			"Choose a different person to take over the cluster.")
	}
	if err := s.requireLeaderAccount(ctx, newUserID); err != nil {
		return nil, err
	}
	reason, err := reasonOf(ctx, request.Msg.GetReason())
	if err != nil {
		return nil, err
	}
	id, err := newID()
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	today := s.today()
	next := NewAssignment{ID: id, ClusterID: old.ClusterID, UserID: newUserID, StartsOn: today,
		ActorID: principal.UserID, Reason: reason}
	if err := s.data.ReplaceAssignment(ctx, old.ID, next, today); err != nil {
		return nil, s.writeError(ctx, err)
	}
	ended, err := s.data.Assignment(ctx, old.ID)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	created, err := s.data.Assignment(ctx, id)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	return connect.NewResponse(&clustersv1.ReplaceLeaderResponse{
		Ended: toAssignment(ended), Assignment: toAssignment(created),
	}), nil
}

func (s *Service) administeredAssignment(ctx context.Context, id string) (Assignment, auth.Principal, error) {
	if err := validID(ctx, "assignment", id); err != nil {
		return Assignment{}, auth.Principal{}, err
	}
	if _, err := principalOf(ctx); err != nil {
		return Assignment{}, auth.Principal{}, err
	}
	assignment, err := s.data.Assignment(ctx, id)
	if errors.Is(err, ErrNotFound) {
		return Assignment{}, auth.Principal{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such assignment.")
	}
	if err != nil {
		return Assignment{}, auth.Principal{}, s.internal(ctx, err)
	}
	principal, _, err := s.administered(ctx, assignment.ClusterID)
	if err != nil {
		return Assignment{}, auth.Principal{}, err
	}
	return assignment, principal, nil
}

// requireLeaderAccount refuses an account that is missing, inactive or not a
// Cluster Leader. The portal never gives the role itself.
func (s *Service) requireLeaderAccount(ctx context.Context, userID string) error {
	if err := validID(ctx, "account", userID); err != nil {
		return err
	}
	account, err := s.data.Account(ctx, userID)
	if errors.Is(err, ErrNotFound) {
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			"No active account has that id.")
	}
	if err != nil {
		return s.internal(ctx, err)
	}
	if !account.IsLeader {
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonPermissionDenied,
			"This account does not hold the Cluster Leader role. Use Onboard a new Cluster Leader to make one.")
	}
	return nil
}

// span reads an assignment's dates: starts today unless given, open-ended
// unless an end is given, and never ending before it starts.
func (s *Service) span(ctx context.Context, starts, ends string) (time.Time, *time.Time, error) {
	invalid := func(message string) (time.Time, *time.Time, error) {
		return time.Time{}, nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, message)
	}
	startsOn := s.today()
	if starts = strings.TrimSpace(starts); starts != "" {
		parsed, err := time.Parse(isoDate, starts)
		if err != nil {
			return invalid("The start date must be a date (YYYY-MM-DD).")
		}
		startsOn = parsed
	}
	if ends = strings.TrimSpace(ends); ends == "" {
		return startsOn, nil, nil
	}
	endsOn, err := time.Parse(isoDate, ends)
	if err != nil {
		return invalid("The end date must be a date (YYYY-MM-DD).")
	}
	if endsOn.Before(startsOn) {
		return invalid("The end date cannot be before the start date.")
	}
	return startsOn, &endsOn, nil
}

func reasonOf(ctx context.Context, raw string) (string, error) {
	reason := strings.TrimSpace(raw)
	if len(reason) > maxReasonLength {
		return "", apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument,
			"The reason is too long (500 characters at most).")
	}
	return reason, nil
}

func (s *Service) writeError(ctx context.Context, err error) error {
	switch {
	case errors.Is(err, ErrNotLive):
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"This assignment has already ended.")
	case errors.Is(err, ErrAlreadyAssigned):
		return apierr.New(ctx, connect.CodeAlreadyExists, apierr.ReasonInvalidArgument,
			"This person already leads this cluster.")
	default:
		return s.internal(ctx, err)
	}
}
