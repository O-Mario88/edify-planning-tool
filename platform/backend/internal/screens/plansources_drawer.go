package screens

import (
	"context"
	"errors"
	"net/url"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// planSourcesDrawerInGo is the General Budget's View Plan Sources drawer
// (budgetpage.PlanSources).
func (s *Service) planSourcesDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	if strings.TrimSuffix(path, "/") != budgetpage.PlanSourcesPath || s.db == nil {
		return nil, false, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This link is not valid.")
	}
	resp, served, err := budgetpage.PlanSources(ctx, s.db, p, query, s.clock())
	if errors.Is(err, pagegate.ErrNotAvailable) {
		return &screensv1.GetDrawerResponse{Refusal: planSourcesDenied}, true, nil
	}
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return resp, served, nil
}

// planSourcesDenied is require_page_permission("country_budget")'s refusal.
const planSourcesDenied = "Access Denied: Your active role does not have permission to view Country Budget."
