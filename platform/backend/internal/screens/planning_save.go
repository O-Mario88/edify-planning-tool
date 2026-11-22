package screens

import (
	"context"
	"errors"
	"log/slog"
	"net/url"
	"strings"
	"unicode"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/structpb"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The app's Schedule save through Go (docs/migration/27 §27.10), behind
// EDIFY_GO_SAVES=schedule_visit. The existing application still opens the
// drawer and composes the form exactly as its own save would post it
// (PlanningDrawerFeedView, ?form_only=1, which saves nothing); Go makes the
// save when the form is 27.3's case, and answers in the words the existing
// feed gives (_saved_outcome, toast_message). Anything else is forwarded
// unchanged, so a save is never made by both.

// VisitSaver is the Go visit save (internal/activities.Service).
type VisitSaver interface {
	Schedule(ctx context.Context, p auth.Principal, req activities.Request, origin activities.Origin) (activities.Answer, error)
}

// WithVisitSave makes the Schedule drawer's visit saves (27.3) Go's where
// Go takes them.
func (s *Service) WithVisitSave(saver VisitSaver, logger *slog.Logger) *Service {
	s.visits, s.logger, s.visitsInGo = saver, logger, true
	return s
}

// WithTrainingPairSave makes the Schedule drawer's In-school Training saves
// (docs/migration/32) Go's where Go takes them, behind its own switch
// (EDIFY_GO_SAVES=schedule_training_pair).
func (s *Service) WithTrainingPairSave(saver VisitSaver, logger *slog.Logger) *Service {
	s.visits, s.logger, s.pairsInGo = saver, logger, true
	return s
}

// switchedOn is whether the switch for this save is on: the pair's and the
// visit's are separate, so naming one never moves the other.
func (s *Service) switchedOn(req activities.Request) bool {
	if activities.IsPairPurpose(req.Purpose) {
		return s.pairsInGo
	}
	return s.visitsInGo
}

const scheduleKind = "schedule"

// scheduleInGo makes the save in Go; served is false when the request is
// to be forwarded to the existing application as before.
func (s *Service) scheduleInGo(
	ctx context.Context, message *screensv1.SavePlanningDrawerRequest,
) (*screensv1.SavePlanningDrawerResponse, bool, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.visits == nil || message.GetKind() != scheduleKind ||
		principal.InActingAppointment {
		return nil, false, nil
	}
	var form url.Values
	var origin activities.Origin
	if s.existingApp != nil {
		var answer structpb.Struct
		path := schoolPath(message.GetSchoolId(), "planning/"+scheduleKind) + "?form_only=1"
		if err := s.existingApp.Post(ctx, path, message, &answer); err != nil {
			// The drawer's own refusal (_open): the same the forwarded save meets.
			return nil, true, err
		}
		var okForm bool
		form, origin, okForm = formOf(&answer)
		if !okForm {
			return nil, false, nil
		}
	} else {
		form = url.Values{}
		if sid := strings.TrimSpace(message.GetSchoolId()); sid != "" {
			form.Set("school_id", sid)
		}
		for name, val := range message.GetValues() {
			if n := strings.TrimSpace(name); n != "" {
				form.Add(n, val)
			}
		}
		if form.Get("require_catalogue") == "" {
			form.Set("require_catalogue", "yes")
		}
	}
	req, taken := activities.RequestFromForm(form)
	if !taken || !s.switchedOn(req) {
		return nil, false, nil
	}
	saved, err := s.visits.Schedule(ctx, principal, req, origin)
	return outcomeOf(ctx, s.logger, saved, err)
}

// outcomeOf is the existing feed's answer for Go's result.
func outcomeOf(ctx context.Context, logger *slog.Logger, saved activities.Answer, err error) (
	*screensv1.SavePlanningDrawerResponse, bool, error,
) {
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		// error_fragment's words, read back as the feed reads them.
		return &screensv1.SavePlanningDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if logger != nil {
			logger.ErrorContext(ctx, "the Go visit save failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	// toast_message: the toast's own sentence, then the ceiling notice.
	words := collapse(saved.Message)
	if notice := collapse(saved.Notice); notice != "" {
		words += " " + notice
	}
	return &screensv1.SavePlanningDrawerResponse{Saved: true, Message: words}, true, nil
}

// formOf reads the form-only answer: {"form": {name: value}, "origin":
// {"ip", "agent", "correlation"}}. false for anything else.
func formOf(answer *structpb.Struct) (url.Values, activities.Origin, bool) {
	fields := answer.GetFields()
	posted := fields["form"].GetStructValue()
	if posted == nil {
		return nil, activities.Origin{}, false
	}
	form := url.Values{}
	for name, value := range posted.GetFields() {
		text, ok := value.GetKind().(*structpb.Value_StringValue)
		if !ok {
			return nil, activities.Origin{}, false
		}
		form.Set(name, text.StringValue)
	}
	said := fields["origin"].GetStructValue().GetFields()
	return form, activities.Origin{
		IP:            said["ip"].GetStringValue(),
		UserAgent:     said["agent"].GetStringValue(),
		CorrelationID: said["correlation"].GetStringValue(),
	}, true
}

// collapse is Python's " ".join(text.split()), as page_blocks reads text.
func collapse(text string) string {
	return strings.Join(strings.FieldsFunc(text, pythonSpace), " ")
}

// pythonSpace is str.isspace: Go's unicode.IsSpace and the four
// separators (U+001C–U+001F) Python also splits on.
func pythonSpace(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}
