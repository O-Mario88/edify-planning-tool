package screens

import (
	"context"
	"net/url"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The profile's planning drawers (Schedule visit, Assign to Partner), read
// and saved by the existing application's own views (apps.mobile_feed
// PlanningDrawerFeedView). Only these two drawers exist.

const pathTrainingCapacity = "/api/mobile/v1/planning/training-capacity"

var (
	planningKinds = map[string]bool{
		"schedule":        true,
		"assign":          true,
		"group-training":  true,
		"cluster-meeting": true,
	}
	isoDate  = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)
	recordID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)
)

func requirePlanningDrawer(ctx context.Context, schoolID, kind string) error {
	if err := requireSchool(ctx, schoolID); err != nil {
		return err
	}
	if !planningKinds[kind] {
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This drawer does not exist.")
	}
	return nil
}

// GetPlanningDrawer returns a school's Schedule visit or Assign to Partner
// drawer as the web draws it.
func (s *Service) GetPlanningDrawer(
	ctx context.Context, request *connect.Request[screensv1.GetPlanningDrawerRequest],
) (*connect.Response[screensv1.GetPlanningDrawerResponse], error) {
	message := request.Msg
	if err := requirePlanningDrawer(ctx, message.GetSchoolId(), message.GetKind()); err != nil {
		return nil, err
	}
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.getPlanningDrawerInGo(ctx, p, message.GetSchoolId(), message.GetKind()); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
	}
	return fetch[screensv1.GetPlanningDrawerResponse](ctx, s, schoolPath(message.GetSchoolId(), "planning/"+message.GetKind()))
}

// SavePlanningDrawer saves a planning drawer natively in Go (Schedule visit
// and Assign to Partner).
func (s *Service) SavePlanningDrawer(
	ctx context.Context, request *connect.Request[screensv1.SavePlanningDrawerRequest],
) (*connect.Response[screensv1.SavePlanningDrawerResponse], error) {
	message := request.Msg
	if err := requirePlanningDrawer(ctx, message.GetSchoolId(), message.GetKind()); err != nil {
		return nil, err
	}
	for name := range message.GetValues() {
		if !fieldName.MatchString(name) {
			return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This drawer has no such field.")
		}
	}
	s.stampSave(ctx, schoolPath(message.GetSchoolId(), "planning/"+message.GetKind()))
	if message.GetKind() == "group-training" {
		form := url.Values{}
		for name, val := range message.GetValues() {
			form.Add(name, val)
		}
		if answer, served, err := s.ScheduleGroupTrainingInGo(ctx, form, activities.Origin{}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
	}
	if message.GetKind() == "cluster-meeting" {
		form := url.Values{}
		for name, val := range message.GetValues() {
			form.Add(name, val)
		}
		if answer, served, err := s.ScheduleClusterMeetingInGo(ctx, form, activities.Origin{}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
	}
	if answer, served, err := s.scheduleInGo(ctx, message); served {
		if err != nil {
			return nil, err
		}
		return connect.NewResponse(answer), nil
	}
	return send[screensv1.SavePlanningDrawerResponse](ctx, s, schoolPath(message.GetSchoolId(), "planning/"+message.GetKind()), message)
}

// GetTrainingCapacity returns the officer's training ceiling for a training.
func (s *Service) GetTrainingCapacity(
	ctx context.Context, request *connect.Request[screensv1.GetTrainingCapacityRequest],
) (*connect.Response[screensv1.GetTrainingCapacityResponse], error) {
	message := request.Msg
	if (message.GetTraining() != "" && !recordID.MatchString(message.GetTraining())) ||
		(message.GetDate() != "" && !isoDate.MatchString(message.GetDate())) ||
		(message.GetSchool() != "" && !recordID.MatchString(message.GetSchool())) {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This training ceiling cannot be read.")
	}
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.getTrainingCapacityInGo(ctx, p, message); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
	}
	query := url.Values{
		"training": {message.GetTraining()},
		"date":     {message.GetDate()},
		"school":   {message.GetSchool()},
	}
	return fetch[screensv1.GetTrainingCapacityResponse](ctx, s, pathTrainingCapacity+"?"+query.Encode())
}
