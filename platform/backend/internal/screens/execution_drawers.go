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
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5/pgxpool"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
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

// followUpForms are the two stages' Follow Up with PL: the drawer and the
// send each path answers.
var followUpForms = []struct {
	path   *regexp.Regexp
	drawer func(context.Context, schooldirectory.Querier, auth.Principal, map[string]string, time.Time) (*screensv1.PageDrawer, error)
	send   func(context.Context, *pgxpool.Pool, planningmonitor.CEXSendDeps, auth.Principal, map[string]string, activities.Origin,
		time.Time) (string, error)
}{
	{regexp.MustCompile(`^/country-planning-oversight/execution/follow-up/?$`), planningmonitor.CountryExecutionFollowUpDrawer,
		planningmonitor.SendExecutionFollowUp},
	{regexp.MustCompile(`^/country-planning-oversight/follow-up/?$`), planningmonitor.CountryOversightFollowUpDrawer,
		planningmonitor.SendPlanningFollowUp},
}

// WithExecutionFollowUps makes Follow Up with PL Go's on both stages: its
// drawer and its send, with the notice's phone copy.
func (s *Service) WithExecutionFollowUps(deps planningmonitor.CEXSendDeps) *Service {
	s.executionFollowUps = &deps
	return s
}

// followUpValues is the drawer's query with the posted values over it, as
// the form posts its hidden fields.
func followUpValues(rawQuery string, posted map[string]string) map[string]string {
	out := map[string]string{}
	query, _ := url.ParseQuery(rawQuery)
	for k, v := range query {
		if len(v) > 0 {
			out[k] = v[len(v)-1]
		}
	}
	for k, v := range posted {
		out[k] = v
	}
	return out
}

func (s *Service) executionFollowUpDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	if s.db == nil || s.executionFollowUps == nil {
		return nil, false, nil
	}
	for _, form := range followUpForms {
		if !form.path.MatchString(path) {
			continue
		}
		if !slices.Contains(exportPages["country_planning_oversight"], p.ActiveRole) {
			return &screensv1.GetDrawerResponse{Refusal: executionDrawerDenied}, true, nil
		}
		if p.ActiveRole != roleCD {
			return &screensv1.GetDrawerResponse{Refusal: planningmonitor.CEXFollowUpRefusal}, true, nil
		}
		d, err := form.drawer(ctx, s.db, p, followUpValues(rawQuery, nil), s.clock())
		if err != nil {
			return nil, true, apierr.Internal(ctx, s.logger, err)
		}
		return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
	}
	return nil, false, nil
}

func (s *Service) executionFollowUpSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest,
	o activities.Origin) (*screensv1.SaveDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(message.GetPath(), "?")
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || !s.nativeForms() || s.executionFollowUps == nil {
		return nil, false, nil
	}
	for _, form := range followUpForms {
		if !form.path.MatchString(path) {
			continue
		}
		if !slices.Contains(exportPages["country_planning_oversight"], p.ActiveRole) {
			return &screensv1.SaveDrawerResponse{Error: executionDrawerDenied}, true, nil
		}
		sent, err := form.send(ctx, s.db, *s.executionFollowUps, p, followUpValues(rawQuery, message.GetValues()), o, s.clock())
		var refused *planningmonitor.CEXFollowUpError
		switch {
		case errors.Is(err, planningmonitor.ErrCEXFollowUpHandOn):
			return nil, false, nil
		case errors.As(err, &refused):
			return &screensv1.SaveDrawerResponse{Error: refused.Message}, true, nil
		case err != nil:
			return nil, true, apierr.Internal(ctx, s.logger, err)
		}
		return &screensv1.SaveDrawerResponse{Saved: true, Message: sent}, true, nil
	}
	return nil, false, nil
}
