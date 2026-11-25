package screens

// Partner Oversight's hand-over drawer (oversight_views.partner_oversight_
// detail_view), drawn by internal/partneroversight, and its save
// (partner_oversight_send_action_view): the drawer's first form, sent.

import (
	"context"
	"errors"
	"net/url"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/escalations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
)

func (s *Service) partnerOversightDetailInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	if strings.TrimSuffix(path, "/") != partneroversight.DetailPath || s.db == nil {
		return nil, false, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This link is not valid.")
	}
	d, refusal, err := partneroversight.NewService(s.db, s.clock).Detail(ctx, p, strings.TrimSpace(query.Get("assignment_id")),
		escalations.NewService(s.db, s.clock).AddresseeLabel)
	switch {
	case errors.Is(err, partneroversight.ErrDetailHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	case refusal != "":
		return &screensv1.GetDrawerResponse{Refusal: refusal}, true, nil
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

// WithPartnerOversightSend makes the hand-over drawer's save Go's.
func (s *Service) WithPartnerOversightSend(deps partneroversight.SendDeps) *Service {
	s.partnerSend = &deps
	return s
}

// partnerOversightSendInGo saves the hand-over drawer; served is false for
// another drawer, or a save Go hands on.
func (s *Service) partnerOversightSendInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, o activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(message.GetPath(), "?")
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || strings.TrimSuffix(path, "/") != partneroversight.DetailPath || !s.nativeForms() || s.partnerSend == nil {
		return nil, false, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This link is not valid.")
	}
	answer, err := partneroversight.NewService(s.db, s.clock).Send(ctx, s.db, *s.partnerSend, p, query.Get("assignment_id"),
		message.GetValues()["note"], o)
	var refused *partneroversight.SendError
	switch {
	case errors.Is(err, partneroversight.ErrDetailHandOn):
		return nil, false, nil
	case errors.As(err, &refused):
		return &screensv1.SaveDrawerResponse{Error: refused.Message}, true, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: answer}, true, nil
}
