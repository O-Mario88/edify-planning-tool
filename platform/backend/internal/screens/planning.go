package screens

import (
	"context"
	"net/url"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// The profile's planning drawers (Schedule visit, Assign to Partner), read
// and saved by the existing application's own views (apps.mobile_feed
// PlanningDrawerFeedView). Only these two drawers exist.

const pathTrainingCapacity = "/api/mobile/v1/planning/training-capacity"

var (
	planningKinds = map[string]bool{"schedule": true, "assign": true}
	isoDate       = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)
	recordID      = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)
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
	return fetch[screensv1.GetPlanningDrawerResponse](ctx, s, schoolPath(message.GetSchoolId(), "planning/"+message.GetKind()))
}

// SavePlanningDrawer saves a planning drawer through the web view its form
// posts to.
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
	query := url.Values{
		"training": {message.GetTraining()},
		"date":     {message.GetDate()},
		"school":   {message.GetSchool()},
	}
	return fetch[screensv1.GetTrainingCapacityResponse](ctx, s, pathTrainingCapacity+"?"+query.Encode())
}
