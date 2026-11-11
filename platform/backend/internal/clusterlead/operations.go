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

// OpsData is what cluster operations read and write; *Store implements it.
type OpsData interface {
	Data
	ActivityFor(ctx context.Context, id string) (ActivityRecord, error)
	Plans(ctx context.Context, clusterID string) ([]Plan, error)
	Plan(ctx context.Context, id string) (Plan, error)
	Courses(ctx context.Context) ([]Course, error)
	SavePlan(ctx context.Context, p Plan, isNew bool, actorID, event string) error
	MovePlan(ctx context.Context, id string, from []string, status, event, actorID, note, activityID string) error
	Invitations(ctx context.Context, activityID string) ([]Invitation, error)
	Invitation(ctx context.Context, id string) (Invitation, error)
	Invite(ctx context.Context, clusterID, activityID string, schoolIDs, ids []string, channel, actorID string) (int, error)
	RespondInvitation(ctx context.Context, id, status, note, actorID string) error
	FollowUpInvitation(ctx context.Context, id, note, actorID string) error
	Attendance(ctx context.Context, activityID string) ([]AttendanceRecord, error)
	RecordAttendance(ctx context.Context, clusterID, activityID string, entries []AttendanceRecord, ids []string, actorID string) error
	MinutesOf(ctx context.Context, activityID string) (*MinutesRecord, error)
	SaveMinutes(ctx context.Context, id, clusterID, activityID, discussion, decisions string, submit bool, actorID string) error
	Items(ctx context.Context, clusterID string, openOnly bool) ([]Item, error)
	ItemByID(ctx context.Context, id string) (Item, error)
	SaveItem(ctx context.Context, i Item, ownerName string, isNew bool, actorID string) error
	CloseItem(ctx context.Context, id, status, note, actorID string) error
	Requests(ctx context.Context, clusterID string) ([]Request, error)
	RequestByID(ctx context.Context, id string) (Request, error)
	CreateRequest(ctx context.Context, id, clusterID, subject, body, actorID string) error
	AnswerRequestRecord(ctx context.Context, id, answer, actorID string) error
	OperationsOf(ctx context.Context, clusterID, next string, day time.Time) (Operations, error)
	Report(ctx context.Context, clusterID string, start, end time.Time) (ReportData, error)
	InvitePlan(ctx context.Context, clusterID, planID string, schoolIDs, ids []string, channel, actorID string) (int, error)
	PlanInvitees(ctx context.Context, planID string) ([]PlanInvitee, error)
	SSAPerformance(ctx context.Context, clusterID string, fy int) (SSAAverages, error)
}

// NewOperations wires the operations service onto the leadership service's
// clock, readiness and logger.
func NewOperations(lead *Service, ops OpsData) *OperationsService {
	return &OperationsService{Service: lead, ops: ops}
}

// OperationsService implements ClusterMobilizationService.
type OperationsService struct {
	*Service
	ops OpsData
}

const (
	maxTitleLength = 200
	maxTextLength  = 4000
	maxSchoolsOnce = 500
)

// side is who the caller is to a cluster.
type side struct {
	principal auth.Principal
	isLeader  bool
}

// access is the caller's side of the cluster: its leader (a live
// assignment) or its staff (who may manage its leaders); anyone else is
// refused.
func (o *OperationsService) access(ctx context.Context, clusterID string) (side, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return side{}, err
	}
	if err := o.checkReady(ctx); err != nil {
		return side{}, err
	}
	if principal.ActiveRole == RoleClusterLeader {
		if _, err := o.liveFor(ctx, principal.UserID, clusterID); err != nil {
			return side{}, err
		}
		return side{principal: principal, isLeader: true}, nil
	}
	if err := validID(ctx, "cluster", clusterID); err != nil {
		return side{}, err
	}
	cluster, err := o.data.Cluster(ctx, clusterID)
	if errors.Is(err, ErrNotFound) {
		return side{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such cluster.")
	}
	if err != nil {
		return side{}, o.internal(ctx, err)
	}
	if !mayAdminister(principal, cluster) {
		return side{}, notYours(ctx)
	}
	return side{principal: principal}, nil
}

func (o *OperationsService) leaderOf(ctx context.Context, clusterID string) (side, error) {
	who, err := o.access(ctx, clusterID)
	if err == nil && !who.isLeader {
		err = apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Only the cluster's leader does this.")
	}
	return who, err
}

func (o *OperationsService) staffOf(ctx context.Context, clusterID string) (side, error) {
	who, err := o.access(ctx, clusterID)
	if err == nil && who.isLeader {
		err = apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"The cluster's staff do this; a leader cannot approve their own plans.")
	}
	return who, err
}

// activityOf is an existing cluster activity the caller may reach.
func (o *OperationsService) activityOf(ctx context.Context, activityID string) (ActivityRecord, side, error) {
	if err := validID(ctx, "activity", activityID); err != nil {
		return ActivityRecord{}, side{}, err
	}
	activity, err := o.ops.ActivityFor(ctx, activityID)
	if errors.Is(err, ErrNotFound) {
		return ActivityRecord{}, side{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "No such cluster activity.")
	}
	if err != nil {
		return ActivityRecord{}, side{}, o.internal(ctx, err)
	}
	who, err := o.access(ctx, activity.ClusterID)
	return activity, who, err
}

func invalid(ctx context.Context, message string) error {
	return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, message)
}

func textOf(ctx context.Context, what, raw string, limit int, required bool) (string, error) {
	text := strings.TrimSpace(raw)
	if required && text == "" {
		return "", invalid(ctx, what+" is required.")
	}
	if len(text) > limit {
		return "", invalid(ctx, what+" is too long.")
	}
	return text, nil
}

func isoOrNil(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.UTC().Format(time.RFC3339)
}

func toEvents(events []Event) []*clustersv1.PlanEvent {
	out := make([]*clustersv1.PlanEvent, 0, len(events))
	for _, e := range events {
		out = append(out, &clustersv1.PlanEvent{Event: e.Event, Actor: e.Actor, Note: e.Reason, At: e.At.UTC().Format(time.RFC3339)})
	}
	return out
}

// fiscalYear is Edify's financial year holding day: 1 October to
// 30 September, named by the year it ends ("FY 2027" is Oct 2026-Sep 2027).
func fiscalYear(day time.Time) (start, end time.Time, name int) {
	year := day.Year()
	if day.Month() >= time.October {
		year++
	}
	start = time.Date(year-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	return start, start.AddDate(1, 0, 0), year
}
