package screens

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clustermembership"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// A school's own Add to Cluster (the profile's and the directory row's
// GetAddToCluster and AddToCluster), in Go with Django absent, through the
// one membership service. It answers before the Batch-22 path
// (getAddToClusterInGo, addToClusterInGo), which wrote its own audit action.

// SchoolClusterer draws and saves a school's Add to Cluster
// (internal/clustermembership.Service).
type SchoolClusterer interface {
	SchoolForm(ctx context.Context, p auth.Principal, schoolID string) (*screensv1.AddToClusterForm, error)
	SchoolSave(ctx context.Context, p auth.Principal, req *screensv1.AddToClusterRequest, origin activities.Origin) (*screensv1.SchoolActionResult, error)
}

func (s *Service) schoolClusterer() (SchoolClusterer, bool) {
	if s.existingApp != nil {
		return nil, false
	}
	c, ok := s.membership.(SchoolClusterer)
	return c, ok
}

func (s *Service) schoolClusterFormInGo(ctx context.Context, p auth.Principal, schoolID string) (*screensv1.GetAddToClusterResponse, bool, error) {
	c, ok := s.schoolClusterer()
	if !ok {
		return nil, false, nil
	}
	form, err := c.SchoolForm(ctx, p, schoolID)
	switch {
	case errors.Is(err, clustermembership.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetAddToClusterResponse{Form: form}, true, nil
}

func (s *Service) schoolClusterSaveInGo(ctx context.Context, p auth.Principal, request *connect.Request[screensv1.AddToClusterRequest]) (*screensv1.AddToClusterResponse, bool, error) {
	c, ok := s.schoolClusterer()
	if !ok {
		return nil, false, nil
	}
	read := origin.Read(request.Peer().Addr, request.Header(), s.trustProxy, trace.FromContext(ctx).RequestID)
	result, err := c.SchoolSave(ctx, p, request.Msg, activities.Origin{IP: read.IP, UserAgent: read.UserAgent, CorrelationID: read.CorrelationID})
	switch {
	case errors.Is(err, clustermembership.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.AddToClusterResponse{Result: result}, true, nil
}
