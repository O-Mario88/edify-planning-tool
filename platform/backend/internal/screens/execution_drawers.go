package screens

// Country Oversight's Execution & Completion drill-down (country_execution
// _views.drawer_view): the records behind a figure, drawn by Go through
// planningmonitor.CountryExecutionDrawer. It only reads.

import (
	"context"
	"errors"
	"net/url"
	"regexp"
	"slices"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
)

var executionDrawerPath = regexp.MustCompile(`^/country-planning-oversight/execution/drawer/?$`)

// executionDrawerDenied is render_access_denied for the page's permission.
const executionDrawerDenied = "Access Denied: Your active role does not have permission to view Country Planning Oversight."

func (s *Service) executionDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	if !executionDrawerPath.MatchString(path) || s.db == nil {
		return nil, false, nil
	}
	if !slices.Contains(exportPages["country_planning_oversight"], p.ActiveRole) {
		return &screensv1.GetDrawerResponse{Refusal: executionDrawerDenied}, true, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This link is not valid.")
	}
	d, err := planningmonitor.CountryExecutionDrawer(ctx, s.db, p, query, s.clock())
	if errors.Is(err, planningmonitor.ErrNoSuchDrawer) {
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This was not found, or it is not yours to view.")
	}
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}
