package screens

// The Users page's Reset password drawer and its save
// (extended_views.admin_user_detail_view, action reset_password).

import (
	"context"
	"errors"
	"regexp"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accounts"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminusers"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

var adminPasswordPath = regexp.MustCompile(`^/admin-panel/users/([A-Za-z0-9]{1,30})/?$`)

const usersRefusal = "Access Denied: Your active role does not have permission to view Users."

// TemporaryPasswords is accounts.Service.SetTemporaryPassword.
type TemporaryPasswords interface {
	SetTemporaryPassword(ctx context.Context, principal auth.Principal, id, password string) error
}

// WithTemporaryPasswords makes the Reset password drawer's save Go's.
func (s *Service) WithTemporaryPasswords(t TemporaryPasswords) *Service {
	s.passwords = t
	return s
}

// adminPasswordTarget is the account the drawer is about, when the path is
// the drawer's.
func adminPasswordTarget(rawPath string) (string, string, bool) {
	path, query, _ := strings.Cut(rawPath, "?")
	m := adminPasswordPath.FindStringSubmatch(path)
	if m == nil || query != "drawer=password" {
		return "", "", false
	}
	return m[1], path, true
}

func (s *Service) adminPasswordDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	id, path, ok := adminPasswordTarget(rawPath)
	if !ok || s.db == nil || p.InActingAppointment {
		return nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return &screensv1.GetDrawerResponse{Refusal: usersRefusal}, true, nil
	}
	d, err := adminusers.PasswordDrawer(ctx, s.db, p, id)
	switch {
	case errors.Is(err, adminusers.ErrHandOn):
		return nil, false, nil
	case errors.Is(err, adminusers.ErrNoAccount):
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This drawer is not available.")
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

func (s *Service) adminPasswordSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	id, path, target := adminPasswordTarget(message.GetPath())
	if !ok || !target || !s.nativeForms() || s.passwords == nil || p.InActingAppointment {
		return nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return &screensv1.SaveDrawerResponse{Error: "This drawer is not available."}, true, nil
	}
	if _, err := adminusers.PasswordDrawer(ctx, s.db, p, id); err != nil {
		switch {
		case errors.Is(err, adminusers.ErrHandOn):
			return nil, false, nil
		case errors.Is(err, adminusers.ErrNoAccount):
			return &screensv1.SaveDrawerResponse{Error: "This drawer is not available."}, true, nil
		}
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	password := strings.TrimSpace(message.GetValues()["new_password"])
	if password == "" {
		return &screensv1.SaveDrawerResponse{Error: "Password cannot be empty."}, true, nil
	}
	var name string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, id).Scan(&name); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	err := s.passwords.SetTemporaryPassword(ctx, p, id, password)
	var refused *accounts.Refused
	switch {
	case errors.As(err, &refused):
		return &screensv1.SaveDrawerResponse{Error: refused.Message}, true, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.SaveDrawerResponse{Saved: true,
		Message: "Password reset for " + name + ". They will be required to change it on next login."}, true, nil
}
