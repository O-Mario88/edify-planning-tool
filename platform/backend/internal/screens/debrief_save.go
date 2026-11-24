package screens

import (
	"context"
	"errors"
	"log/slog"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/debriefs"
)

// DailyDebriefer is the Go save behind the Daily Debrief's page form
// (internal/debriefs.Service).
type DailyDebriefer interface {
	SaveDaily(ctx context.Context, p auth.Principal, f debriefs.DailyForm, origin activities.Origin) (string, error)
}

// WithDailyDebrief makes the Daily Debrief's form Go's, with Django absent.
func (s *Service) WithDailyDebrief(d DailyDebriefer) *Service {
	s.dailyDebrief = d
	return s
}

// dailyDebriefInGo saves the form posted from /debriefs/submit.
func (s *Service) dailyDebriefInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.dailyDebrief == nil || s.existingApp != nil || message.GetForm() != debriefs.DailyFormKey {
		return nil, false, nil
	}
	path, _, _ := strings.Cut(message.GetPath(), "?")
	if strings.TrimSuffix(path, "/") != debriefs.SubmitPath {
		return nil, false, nil
	}
	v := message.GetValues()
	said, err := s.dailyDebrief.SaveDaily(ctx, principal, debriefs.DailyForm{
		ActivityIDs: debriefs.ActivityIDs(v["activity_ids"]), WentWell: v["what_went_well"], NotWell: v["what_did_not_go_well"],
		Challenges: v["challenges_faced"], Advice: v["recommendations"], OtherWork: v["other_work_description"],
		Autosave: v["intent"] == "autosave",
	}, from)
	var refusal *debriefs.Refusal
	switch {
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go daily debrief failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: said}, true, nil
}
