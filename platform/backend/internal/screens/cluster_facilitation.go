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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterfacilitation"
)

// The cluster's "Partner to Facilitate" drawer (clusterpage's row menu,
// /clusters/<id>/facilitator-drawer) and its save, in Go with Django absent.

var facilitatorDrawerPath = regexp.MustCompile(`^/clusters/([A-Za-z0-9]{1,30})/facilitator-drawer/?$`)

// ClusterFacilitator draws and saves the facilitator (internal/clusterfacilitation.Service).
type ClusterFacilitator interface {
	Drawer(ctx context.Context, p auth.Principal, clusterID string) (*screensv1.PageDrawer, string, error)
	Assign(ctx context.Context, p auth.Principal, clusterID, partnerID string, origin activities.Origin) (string, string, error)
}

// WithClusterFacilitation makes the facilitator drawer and save Go's with Django absent.
func (s *Service) WithClusterFacilitation(f ClusterFacilitator) *Service {
	s.facilitation = f
	return s
}

func (s *Service) facilitatorCluster(path string) (string, bool) {
	if s.facilitation == nil || s.existingApp != nil {
		return "", false
	}
	m := facilitatorDrawerPath.FindStringSubmatch(strings.SplitN(path, "?", 2)[0])
	if m == nil {
		return "", false
	}
	return m[1], true
}

func (s *Service) facilitatorDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	id, ok := s.facilitatorCluster(path)
	if !ok {
		return nil, false, nil
	}
	d, refusal, err := s.facilitation.Drawer(ctx, p, id)
	switch {
	case errors.Is(err, clusterfacilitation.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	case refusal != "":
		return &screensv1.GetDrawerResponse{Refusal: refusal}, true, nil
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

func (s *Service) facilitatorSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (*screensv1.SaveDrawerResponse, bool, error) {
	id, ok := s.facilitatorCluster(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed {
		return nil, false, nil
	}
	said, refusal, err := s.facilitation.Assign(ctx, p, id, message.GetValues()["facilitating_partner_id"], from)
	switch {
	case errors.Is(err, clusterfacilitation.ErrHandOn):
		return nil, false, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go facilitator save failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	case refusal != "":
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal)}, true, nil
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(said)}, true, nil
}
