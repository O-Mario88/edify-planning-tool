package screens

import (
	"context"
	"errors"
	"log/slog"
	"net/url"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clustercreate"
)

// The Clusters page's Create cluster drawer (/clusters/create-drawer), its
// staff refill (/clusters/eligible-staff) and its save, in Go with Django
// absent.

var createClusterDrawerPath = regexp.MustCompile(`^/clusters/create-drawer/?$`)

const eligibleStaffSource = "/clusters/eligible-staff"

// ClusterCreator draws, refills and saves the create form (internal/clustercreate.Service).
type ClusterCreator interface {
	Drawer(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.PageDrawer, error)
	StaffChoices(ctx context.Context, p auth.Principal, district string) ([]*screensv1.DrawerOption, error)
	Create(ctx context.Context, p auth.Principal, values map[string]string, query url.Values, origin activities.Origin) (string, string, error)
}

// WithClusterCreate makes Create cluster Go's with Django absent.
func (s *Service) WithClusterCreate(c ClusterCreator) *Service {
	s.creator = c
	return s
}

func (s *Service) createClusterQuery(raw string) (url.Values, bool) {
	if s.creator == nil || s.existingApp != nil {
		return nil, false
	}
	parsed, err := url.Parse(raw)
	if err != nil || !createClusterDrawerPath.MatchString(parsed.Path) {
		return nil, false
	}
	return parsed.Query(), true
}

func (s *Service) createClusterDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	query, ok := s.createClusterQuery(rawPath)
	if !ok {
		return nil, false, nil
	}
	d, err := s.creator.Drawer(ctx, p, query)
	switch {
	case errors.Is(err, clustercreate.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

func (s *Service) eligibleStaffInGo(ctx context.Context, source, value string) (*screensv1.GetDrawerOptionsResponse, bool, error) {
	if s.creator == nil || s.existingApp != nil || source != eligibleStaffSource {
		return nil, false, nil
	}
	p, signed := auth.PrincipalFrom(ctx)
	if !signed {
		return nil, false, nil
	}
	options, err := s.creator.StaffChoices(ctx, p, value)
	switch {
	case errors.Is(err, clustercreate.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerOptionsResponse{Options: options}, true, nil
}

func (s *Service) createClusterSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (*screensv1.SaveDrawerResponse, bool, error) {
	query, ok := s.createClusterQuery(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed {
		return nil, false, nil
	}
	said, refusal, err := s.creator.Create(ctx, p, message.GetValues(), query, from)
	switch {
	case errors.Is(err, clustercreate.ErrHandOn):
		return nil, false, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go Create cluster save failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	case refusal != "":
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal)}, true, nil
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(said)}, true, nil
}
