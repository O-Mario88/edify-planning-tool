package screens

// A partner organisation's login setup drawer and its save
// (partner_user_setup_drawer_view → configure_partner_user): link an
// existing partner account, invite a new Partner Admin, or record that no
// login is needed yet.

import (
	"context"
	"errors"
	"regexp"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accounts"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminusers"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

var partnerLoginPath = regexp.MustCompile(`^/partners/([A-Za-z0-9_-]{1,40})/user-setup/?$`)

// partnerLoginTarget is the organisation the drawer is about, when the path
// is the drawer's.
func partnerLoginTarget(rawPath string) (string, bool) {
	path, _, _ := strings.Cut(rawPath, "?")
	m := partnerLoginPath.FindStringSubmatch(path)
	if m == nil {
		return "", false
	}
	return m[1], true
}

func (s *Service) partnerLoginDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	id, ok := partnerLoginTarget(rawPath)
	if !ok || s.db == nil || p.InActingAppointment {
		return nil, false, nil
	}
	if !adminusers.MayManagePartnerLogins(p) {
		return &screensv1.GetDrawerResponse{Refusal: adminusers.PartnerLoginRefusal}, true, nil
	}
	d, err := adminusers.PartnerLoginDrawer(ctx, s.db, p, id)
	switch {
	case errors.Is(err, adminusers.ErrNoPartner):
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This drawer is not available.")
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

func (s *Service) partnerLoginSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, signed := auth.PrincipalFrom(ctx)
	id, ok := partnerLoginTarget(message.GetPath())
	if !ok || !signed || !s.nativeForms() || s.accountCreation == nil || p.InActingAppointment {
		return nil, false, nil
	}
	if !adminusers.MayManagePartnerLogins(p) {
		return &screensv1.SaveDrawerResponse{Error: "This drawer is not available."}, true, nil
	}
	if _, err := adminusers.PartnerLoginDrawer(ctx, s.db, p, id); err != nil {
		if errors.Is(err, adminusers.ErrNoPartner) {
			return &screensv1.SaveDrawerResponse{Error: "This drawer is not available."}, true, nil
		}
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	values := message.GetValues()
	choice := adminusers.PartnerLoginChoice{Mode: values["mode"], Email: values["email"], Name: values["login_name"],
		Password: values["password"]}
	now := time.Now()
	if s.now != nil {
		now = s.now()
	}
	var created struct{ name, email, invitation string }
	create := func(ctx context.Context, tx pgx.Tx, email, name, password string) (string, error) {
		userID, invitation, err := s.accountCreation.CreateInTx(ctx, tx, p, accounts.NewAccount{
			Name: name, Email: email, Role: "PartnerAdmin", Password: password})
		created.name, created.email, created.invitation = name, email, invitation
		return userID, err
	}
	var saved adminusers.PartnerLoginSaved
	err := pgx.BeginTxFunc(ctx, s.db, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		saved, err = adminusers.ConfigurePartnerLogin(ctx, tx, p, id, choice, create, now)
		return err
	})
	var refused *adminusers.LoginRefused
	var accountRefused *accounts.Refused
	switch {
	case errors.As(err, &refused):
		return s.partnerLoginAgain(ctx, p, id, refused.Message)
	case errors.As(err, &accountRefused):
		return s.partnerLoginAgain(ctx, p, id, accountRefused.Message)
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	if created.email != "" {
		s.accountCreation.StaffChanged()
		s.accountCreation.NotifyCreated(p, created.name, created.email, created.invitation)
	}
	label := map[string]string{"configured": "login linked", "not_required": "marked as needing no login yet"}[saved.Status]
	return &screensv1.SaveDrawerResponse{Saved: true, Message: saved.PartnerName + ": " + label + "."}, true, nil
}

// partnerLoginAgain is the drawer drawn again with the refusal at its top,
// as the view renders it with its validation error.
func (s *Service) partnerLoginAgain(ctx context.Context, p auth.Principal, id, refusal string) (*screensv1.SaveDrawerResponse, bool, error) {
	d, err := adminusers.PartnerLoginDrawer(ctx, s.db, p, id)
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	d.Items = append([]*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: refusal, Tone: "danger"}}}},
		d.Items...)
	return &screensv1.SaveDrawerResponse{Drawer: d}, true, nil
}
