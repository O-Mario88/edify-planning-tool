package adminusers

// The Reset password drawer (extended_views.admin_user_detail_view,
// ?drawer=password; partials/admin/reset_password_drawer.html) as the feed
// reads it. Its save is accounts.SetTemporaryPassword, through screens.

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrNoAccount is the view's 404: no such live account.
var ErrNoAccount = errors.New("adminusers: no such account")

// ErrHandOn is a reader Go does not draw the drawer for: anyone but the
// Admin, whose reach over an account the existing view decides.
var ErrHandOn = errors.New("adminusers: the drawer is handed on")

// partnerLoginRoles is partner_login_roles.
var partnerLoginRoles = map[string]bool{"PartnerAdmin": true, "PartnerFieldOfficer": true}

// PasswordDrawer draws the Reset password drawer for the account id.
func PasswordDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	if p.ActiveRole != "Admin" {
		return nil, ErrHandOn
	}
	var name, email, role string
	err := db.QueryRow(ctx, `SELECT COALESCE(name, ''), COALESCE(email, ''), COALESCE(active_role, '') FROM "user"
WHERE id = $1 AND deleted_at IS NULL`, id).Scan(&name, &email, &role)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNoAccount
	}
	if err != nil {
		return nil, fmt.Errorf("adminusers: the account: %w", err)
	}
	subtitle := email
	if partnerLoginRoles[role] {
		// login_organisation: the organisation the account is the login of,
		// its own or a team member's.
		var org string
		err := db.QueryRow(ctx, `SELECT name FROM (
  (SELECT name, 1 AS k FROM partner WHERE user_id = $1 ORDER BY id LIMIT 1)
  UNION ALL
  (SELECT p.name, 2 FROM partner p JOIN partner_member m ON m.partner_id = p.id WHERE m.user_id = $1 ORDER BY p.id LIMIT 1)
) x ORDER BY k LIMIT 1`, id).Scan(&org)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("adminusers: the login's organisation: %w", err)
		}
		if org != "" {
			subtitle += " · login of " + org
		}
	}
	return &screensv1.PageDrawer{Title: "Reset the password of " + name, Subtitle: subtitle, HasRequired: true,
		SubmitLabel: "Reset password", CancelLabel: "Cancel", CanSubmit: true,
		Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "new_password",
			Label: "New password", Kind: "password", Required: true,
			Help: name + " signs in with it once and is then asked to choose their own. Any session they have open is signed out, " +
				"and a locked account is unlocked."}}}}}, nil
}
