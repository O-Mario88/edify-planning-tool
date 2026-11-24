package screens

import (
	"context"
	"errors"
	"log/slog"
	"net/url"
	"regexp"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

var (
	// startActivityPath is my_plan_views.start_activity_action's route.
	startActivityPath = regexp.MustCompile(`^/activities/([A-Za-z0-9]{1,30})/start/action/?$`)
	// salesforceEntryPath is my_plan_views.salesforce_id_action's route.
	salesforceEntryPath = regexp.MustCompile(`^/activities/([A-Za-z0-9]{1,30})/salesforce-id/action/?$`)
	// submitReviewPath is my_plan_views.submit_for_review_action's route.
	submitReviewPath = regexp.MustCompile(`^/activities/([A-Za-z0-9]{1,30})/submit/action/?$`)
	// attendancePath is my_plan_views.attendance_upload_action's route.
	attendancePath = regexp.MustCompile(`^/activities/([A-Za-z0-9]{1,30})/attendance/action/?$`)
)

// attendanceErrorTitle is error_fragment(exc, action="Attendance Error").
const attendanceErrorTitle = "Attendance Error: "

// ActivityStarter is the Go save behind Start activity (internal/activities.Service).
type ActivityStarter interface {
	StartActivity(ctx context.Context, p auth.Principal, activityID, notes string, origin activities.Origin) (activities.Answer, error)
	EnterSalesforceID(ctx context.Context, p auth.Principal, activityID string, form url.Values, origin activities.Origin) (activities.CompleteAnswer, error)
	SubmitForReview(ctx context.Context, p auth.Principal, activityID string, origin activities.Origin) (activities.Answer, error)
	RecordAttendance(ctx context.Context, p auth.Principal, activityID string, form url.Values, origin activities.Origin) (activities.Answer, error)
}

// WithActivityLifecycle makes an activity's lifecycle buttons Go's where Go
// takes them. While Django is present its own views keep them.
func (s *Service) WithActivityLifecycle(starter ActivityStarter) *Service {
	s.starter = starter
	return s
}

// lifecycleInGo makes the save in Go; served is false when it is forwarded.
func (s *Service) lifecycleInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.starter == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, _, _ := strings.Cut(message.GetPath(), "?")
	var said, refusedAs string
	var err error
	if m := startActivityPath.FindStringSubmatch(path); m != nil {
		var saved activities.Answer
		saved, err = s.starter.StartActivity(ctx, principal, m[1], message.GetValues()["notes"], from)
		said = saved.Message
	} else if m := salesforceEntryPath.FindStringSubmatch(path); m != nil {
		var saved activities.CompleteAnswer
		saved, err = s.starter.EnterSalesforceID(ctx, principal, m[1], directDrawerForm(message), from)
		said = saved.Message
	} else if m := submitReviewPath.FindStringSubmatch(path); m != nil {
		var saved activities.Answer
		saved, err = s.starter.SubmitForReview(ctx, principal, m[1], from)
		// error_fragment(exc, action="Submission Error").
		said, refusedAs = saved.Message, completeErrorTitle
	} else if m := attendancePath.FindStringSubmatch(path); m != nil {
		var saved activities.Answer
		saved, err = s.starter.RecordAttendance(ctx, principal, m[1], directDrawerForm(message), from)
		said, refusedAs = saved.Message, attendanceErrorTitle
	} else {
		return nil, false, nil
	}
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusedAs + refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go start failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(said)}, true, nil
}
