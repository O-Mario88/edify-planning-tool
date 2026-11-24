package screens

import (
	"context"
	"errors"
	"log/slog"
	"regexp"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// An activity's "Facilitated by" drawer (/activities/<id>/facilitator, the
// Change link in its detail drawer) and its save, in Go with Django absent.

var activityFacilitatorPath = regexp.MustCompile(`^/activities/([A-Za-z0-9]{1,30})/facilitator/?$`)

// ActivityFacilitator draws and saves it (internal/activities.Service).
type ActivityFacilitator interface {
	FacilitatorDrawer(ctx context.Context, p auth.Principal, id string) (activities.FacilitatorFacts, error)
	SetFacilitator(ctx context.Context, p auth.Principal, id, partnerID string, origin activities.Origin) (string, error)
}

// WithActivityFacilitator makes the drawer and its save Go's with Django absent.
func (s *Service) WithActivityFacilitator(f ActivityFacilitator) *Service {
	s.activityFacilitator = f
	return s
}

func (s *Service) activityFacilitatorID(path string) (string, bool) {
	if s.activityFacilitator == nil || s.existingApp != nil {
		return "", false
	}
	m := activityFacilitatorPath.FindStringSubmatch(strings.SplitN(path, "?", 2)[0])
	if m == nil {
		return "", false
	}
	return m[1], true
}

func (s *Service) activityFacilitatorDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	id, ok := s.activityFacilitatorID(path)
	if !ok {
		return nil, false, nil
	}
	f, err := s.activityFacilitator.FacilitatorDrawer(ctx, p, id)
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: facilitatorDrawer(f)}, true, nil
}

// facilitatorDrawer is partials/my_plan/facilitator_drawer.html as the feed
// reads it.
func facilitatorDrawer(f activities.FacilitatorFacts) *screensv1.PageDrawer {
	options := []*screensv1.DrawerOption{{Value: "", Label: "Staff"}}
	for _, p := range f.Partners {
		options = append(options, &screensv1.DrawerOption{Value: p.ID, Label: p.Name})
	}
	return &screensv1.PageDrawer{
		Title: "Facilitated by", Subtitle: f.Subtitle, HasRequired: true,
		Items: []*screensv1.DrawerItem{
			drawerText("Now facilitated by " + f.Current + ". Staff still run the " + f.Noun +
				" and complete it; a partner facilitator is told the date and invoices the facilitation fee."),
			drawerField(&screensv1.DrawerField{
				Name: "facilitating_partner_id", Label: "Facilitated by", Kind: "select", Value: f.Selected,
				Help:    "A partner facilitating this " + f.Noun + " is not assigned the school. Assign the school to a partner separately for follow-ups and other support.",
				Options: options,
			}),
		},
		SubmitLabel: "Save", CancelLabel: "Cancel", CanSubmit: true,
	}
}

func (s *Service) activityFacilitatorSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (*screensv1.SaveDrawerResponse, bool, error) {
	id, ok := s.activityFacilitatorID(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed {
		return nil, false, nil
	}
	said, err := s.activityFacilitator.SetFacilitator(ctx, p, id, message.GetValues()["facilitating_partner_id"], from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go facilitator change failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(said)}, true, nil
}
