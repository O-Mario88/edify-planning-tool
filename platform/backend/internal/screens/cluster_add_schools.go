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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clustermembership"
)

// The cluster's Add Schools drawer (/clusters/<id>/bulk-assign-drawer, the
// Cluster Profile's and the cluster card's "Add Schools") and its save, in Go
// with Django absent.

var addSchoolsDrawerPath = regexp.MustCompile(`^/clusters/([A-Za-z0-9]{1,30})/bulk-assign-drawer/?$`)

// ClusterMembership draws and saves Add Schools (internal/clustermembership.Service).
type ClusterMembership interface {
	Drawer(ctx context.Context, p auth.Principal, clusterID string) (*screensv1.PageDrawer, error)
	AddSchools(ctx context.Context, p auth.Principal, clusterID string, schoolIDs []string, origin activities.Origin) (string, string, error)
}

// WithClusterMembership makes Add Schools Go's with Django absent.
func (s *Service) WithClusterMembership(m ClusterMembership) *Service {
	s.membership = m
	return s
}

func (s *Service) addSchoolsCluster(path string) (string, bool) {
	if s.membership == nil || s.existingApp != nil {
		return "", false
	}
	m := addSchoolsDrawerPath.FindStringSubmatch(strings.SplitN(path, "?", 2)[0])
	if m == nil {
		return "", false
	}
	return m[1], true
}

func (s *Service) addSchoolsDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	id, ok := s.addSchoolsCluster(path)
	if !ok {
		return nil, false, nil
	}
	d, err := s.membership.Drawer(ctx, p, id)
	switch {
	case errors.Is(err, clustermembership.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

// tickedIDs is a checklist's value: the ticked ids, comma-separated in the
// list's order.
func tickedIDs(raw string) []string {
	ids := []string{}
	for _, id := range strings.Split(raw, ",") {
		if id = strings.TrimSpace(id); id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}

func (s *Service) addSchoolsSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (*screensv1.SaveDrawerResponse, bool, error) {
	id, ok := s.addSchoolsCluster(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed {
		return nil, false, nil
	}
	said, refusal, err := s.membership.AddSchools(ctx, p, id, tickedIDs(message.GetValues()["school_ids"]), from)
	switch {
	case errors.Is(err, clustermembership.ErrHandOn):
		return nil, false, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go Add Schools save failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	case refusal != "":
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal)}, true, nil
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(said)}, true, nil
}
