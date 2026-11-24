package screens

import (
	"context"
	"net/url"
	"regexp"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// The profile's drawers, read and saved by the existing application's own
// drawer views (apps.mobile_feed SchoolDrawerFeedView). The feed decides
// which drawers exist; the gateway only refuses a name that is not a plain
// word, so nothing else of the existing application can be reached.

const pathDrawerOptions = "/api/mobile/v1/drawers/options"

var (
	drawerKind = regexp.MustCompile(`^[a-z][a-z-]{0,31}$`)
	fieldName  = regexp.MustCompile(`^[a-z][a-z0-9_]{0,63}$`)
	// A page form's key: the action it sends, its id, or the path it posts to.
	formKey      = regexp.MustCompile(`^/?[A-Za-z0-9][A-Za-z0-9_/.-]{0,127}$`)
	optionSource = regexp.MustCompile(`^/[a-z0-9/-]{1,63}$`)
)

func requireDrawer(ctx context.Context, schoolID, kind string) error {
	if err := requireSchool(ctx, schoolID); err != nil {
		return err
	}
	if !drawerKind.MatchString(kind) {
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This drawer does not exist.")
	}
	return nil
}

// GetSchoolDrawer returns one of a school's drawers natively from Go.
func (s *Service) GetSchoolDrawer(
	ctx context.Context, request *connect.Request[screensv1.GetSchoolDrawerRequest],
) (*connect.Response[screensv1.GetSchoolDrawerResponse], error) {
	message := request.Msg
	if err := requireDrawer(ctx, message.GetSchoolId(), message.GetKind()); err != nil {
		return nil, err
	}
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.getSchoolDrawerInGo(ctx, p, message.GetSchoolId(), message.GetKind()); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
	}
	return fetch[screensv1.GetSchoolDrawerResponse](ctx, s, schoolPath(message.GetSchoolId(), "drawers/"+message.GetKind()))
}

// SaveSchoolDrawer saves a school drawer natively in Go.
func (s *Service) SaveSchoolDrawer(
	ctx context.Context, request *connect.Request[screensv1.SaveSchoolDrawerRequest],
) (*connect.Response[screensv1.SaveSchoolDrawerResponse], error) {
	message := request.Msg
	if err := requireDrawer(ctx, message.GetSchoolId(), message.GetKind()); err != nil {
		return nil, err
	}
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.saveSchoolDrawerInGo(ctx, p, message); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
	}
	return send[screensv1.SaveSchoolDrawerResponse](ctx, s, schoolPath(message.GetSchoolId(), "drawers/"+message.GetKind()), message)
}

// GetDrawerOptions returns the choices a field reloads when another changes.
func (s *Service) GetDrawerOptions(
	ctx context.Context, request *connect.Request[screensv1.GetDrawerOptionsRequest],
) (*connect.Response[screensv1.GetDrawerOptionsResponse], error) {
	message := request.Msg
	if !optionSource.MatchString(message.GetSource()) || !fieldName.MatchString(message.GetName()) ||
		message.GetName() == "source" || len(message.GetValue()) > maxSchoolIDLength {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "These choices do not exist.")
	}
	if resp, served, err := s.eligibleStaffInGo(ctx, message.GetSource(), message.GetValue()); served {
		if err != nil {
			return nil, err
		}
		return connect.NewResponse(resp), nil
	}
	if resp, served, err := s.getDrawerOptionsInGo(ctx, message.GetSource(), message.GetName(), message.GetValue()); served {
		if err != nil {
			return nil, err
		}
		return connect.NewResponse(resp), nil
	}
	query := url.Values{"source": {message.GetSource()}, message.GetName(): {message.GetValue()}}
	return fetch[screensv1.GetDrawerOptionsResponse](ctx, s, pathDrawerOptions+"?"+query.Encode())
}

// Any drawer a page opens, read and saved by the existing application's own
// views (apps.mobile_feed DrawerFeedView). The feed names the drawers and
// saves that are reachable; the gateway only refuses a path that is not
// plain.

const pathPageDrawer = "/api/mobile/v1/drawer"

// drawerPath checks a drawer's web path and query and returns them as one
// plain path the feed reads.
func drawerPath(ctx context.Context, raw string) (string, error) {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme != "" || parsed.Host != "" || !pagePath.MatchString(parsed.Path) {
		return "", apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This drawer cannot be opened.")
	}
	given := map[string]string{}
	for key, values := range parsed.Query() {
		if len(values) != 1 {
			return "", apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This drawer cannot be opened.")
		}
		given[key] = values[0]
	}
	query, err := pageQuery(ctx, given)
	if err != nil {
		return "", err
	}
	if len(query) == 0 {
		return parsed.Path, nil
	}
	return parsed.Path + "?" + query.Encode(), nil
}

// GetDrawer returns a drawer natively from Go when handled, else legacy feed.
func (s *Service) GetDrawer(
	ctx context.Context, request *connect.Request[screensv1.GetDrawerRequest],
) (*connect.Response[screensv1.GetDrawerResponse], error) {
	path, err := drawerPath(ctx, request.Msg.GetPath())
	if err != nil {
		return nil, err
	}
	if p, ok := auth.PrincipalFrom(ctx); ok {
		if resp, served, err := s.getPageDrawerInGo(ctx, p, path); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(resp), nil
		}
	}
	return fetch[screensv1.GetDrawerResponse](ctx, s, pathPageDrawer+"?"+url.Values{"path": {path}}.Encode())
}

// SaveDrawer saves a drawer through the view its form posts to.
func (s *Service) SaveDrawer(
	ctx context.Context, request *connect.Request[screensv1.SaveDrawerRequest],
) (*connect.Response[screensv1.SaveDrawerResponse], error) {
	message := request.Msg
	path, err := drawerPath(ctx, message.GetPath())
	if err != nil {
		return nil, err
	}
	for name := range message.GetValues() {
		if !fieldName.MatchString(name) {
			return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This drawer has no such field.")
		}
	}
	form := message.GetForm()
	if form != "" && (!formKey.MatchString(form) || strings.Contains(form, "..")) {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This form cannot be saved.")
	}
	s.stampSave(ctx, pathPageDrawer)
	forwarded := &screensv1.SaveDrawerRequest{Path: path, Values: message.GetValues(), Form: form}
	if m := schoolEditDrawer.FindStringSubmatch(strings.SplitN(path, "?", 2)[0]); m != nil && form == "" && s.nativeForms() {
		if p, ok := auth.PrincipalFrom(ctx); ok {
			saved, served, err := s.saveSchoolDrawerInGo(ctx, p, &screensv1.SaveSchoolDrawerRequest{
				SchoolId: m[1], Kind: "edit", Values: message.GetValues(),
			})
			if err != nil {
				return nil, err
			}
			if served {
				return connect.NewResponse(&screensv1.SaveDrawerResponse{
					Saved: saved.GetSaved(), Message: saved.GetMessage(), Error: saved.GetError(),
				}), nil
			}
		}
	}
	if form == "" {
		from := origin.Read(request.Peer().Addr, request.Header(), s.trustProxy, trace.FromContext(ctx).RequestID)
		if answer, served, err := s.coreVisitInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.facilitatorSaveInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.bulkProjectSaveInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.createClusterSaveInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.addSchoolsSaveInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.addToProjectSaveInGo(ctx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.bulkAssignInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.bulkScheduleInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.weekOwnerInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.extraWorkInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.reimbursementInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.accountabilityInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.takeSchoolInGo(ctx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.lifecycleInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.visitDecisionInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.rescheduleInGo(ctx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.cancelInGo(ctx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.groupInGo(ctx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.editInGo(ctx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.completeInGo(ctx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		// A decision's audit rows record where it was made from.
		reviewCtx := origin.With(ctx, origin.Read(request.Peer().Addr, request.Header(), s.trustProxy, trace.FromContext(ctx).RequestID))
		if answer, served, err := s.plReviewInGo(reviewCtx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
		if answer, served, err := s.opsInGo(ctx, forwarded); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
	}
	if form != "" {
		from := origin.Read(request.Peer().Addr, request.Header(), s.trustProxy, trace.FromContext(ctx).RequestID)
		if answer, served, err := s.dailyDebriefInGo(ctx, forwarded, activities.Origin{
			IP: from.IP, UserAgent: from.UserAgent, CorrelationID: from.CorrelationID,
		}); served {
			if err != nil {
				return nil, err
			}
			return connect.NewResponse(answer), nil
		}
	}
	return send[screensv1.SaveDrawerResponse](ctx, s, pathPageDrawer, forwarded)
}
