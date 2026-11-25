package screens

// The Partner's "who delivers this work" drawer and its save
// (partner_views.partner_delivery_member_view), drawn and saved by
// internal/partnerassigned.

import (
	"context"
	"errors"
	"regexp"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
)

var partnerDeliveryPath = regexp.MustCompile(`^/partner/activities/([A-Za-z0-9]{1,30})/delivered-by/?$`)

const partnerActivitiesRefusal = "Access Denied: Your active role does not have permission to view Partner Activities."

// partnerDeliveryGate is the page gate: served false for a path that is not
// the drawer's, or a reader Go hands on; refused for a role without the page.
func (s *Service) partnerDeliveryGate(ctx context.Context, p auth.Principal, rawPath string) (string, bool, bool, error) {
	path, _, _ := strings.Cut(rawPath, "?")
	m := partnerDeliveryPath.FindStringSubmatch(path)
	if m == nil || s.db == nil || p.InActingAppointment || p.Acting != nil {
		return "", false, false, nil
	}
	member, err := partnerassigned.IsTeamMember(ctx, s.db, p)
	if err != nil {
		return "", true, false, err
	}
	return m[1], true, pageaccess.CanOpen(p.ActiveRole, member, path), nil
}

func (s *Service) partnerDeliveryDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	id, served, open, err := s.partnerDeliveryGate(ctx, p, rawPath)
	switch {
	case !served:
		return nil, false, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	case !open:
		return &screensv1.GetDrawerResponse{Refusal: partnerActivitiesRefusal}, true, nil
	}
	d, err := partnerassigned.DeliveryDrawer(ctx, s.db, p, id)
	switch {
	case errors.Is(err, partnerassigned.ErrDeliveryNotFound):
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This drawer is not available.")
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

// partnerDeliverySaveInGo saves the drawer as the feed does: the drawer is
// read first (its refusal drawn as the drawer has no form to save).
func (s *Service) partnerDeliverySaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, o activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || !s.nativeForms() {
		return nil, false, nil
	}
	id, served, open, err := s.partnerDeliveryGate(ctx, p, message.GetPath())
	switch {
	case !served:
		return nil, false, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	case !open:
		return &screensv1.SaveDrawerResponse{Error: "This drawer is not available."}, true, nil
	}
	d, err := partnerassigned.DeliveryDrawer(ctx, s.db, p, id)
	switch {
	case errors.Is(err, partnerassigned.ErrDeliveryNotFound):
		return &screensv1.SaveDrawerResponse{Error: "This drawer is not available."}, true, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	case !d.GetCanSubmit():
		return &screensv1.SaveDrawerResponse{Error: "This drawer cannot be saved here."}, true, nil
	}
	said, err := partnerassigned.NameMember(ctx, s.db, p, id, message.GetValues()["delivery_contact_name"], o, s.clock())
	var refused *partnerassigned.DeliveryError
	switch {
	case errors.Is(err, partnerassigned.ErrDeliveryHandOn):
		return nil, false, nil
	case errors.As(err, &refused):
		return &screensv1.SaveDrawerResponse{Error: refused.Message}, true, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: said}, true, nil
}
