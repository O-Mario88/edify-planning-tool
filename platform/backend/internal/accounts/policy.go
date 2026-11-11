// Package accounts is account administration and the signed-in person's own
// account, owned by Go (owner brief, 2026-11-11: "User creation, invitations
// and account lifecycle. Roles and permission management."). The rules are
// the existing application's (apps/admin_users/services.py,
// apps/frontend/views/auth_views.py switch_role_view and
// force_change_password_view), on the existing records.
package accounts

import (
	"context"
	"slices"

	"connectrpc.com/connect"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

// Account statuses (UserStatus).
const (
	statusPending   = "pending_invited"
	statusActive    = "active"
	statusSuspended = "suspended"
	statusDisabled  = "disabled"
)

// Refusals in the existing words.
const (
	msgOnlyAdminModifiesAdmin = "Only an Admin can modify another Admin's account."
	msgOnlyAdminGrantsAdmin   = "Only an Admin can grant the Admin role."
	msgAdminNotCCEO           = "An Admin account cannot also be a CCEO. Give the field work to a separate CCEO account."
	msgOwnRole                = "You cannot change your own role. Switch among your already-granted roles from the role switcher, or ask another Admin."
	msgEmailTaken             = "A user with this email already exists."
	msgRoleRequired           = "role is required."
	msgNotFound               = "User not found."
	msgOwnDelete              = "You cannot delete your own account."
	msgLastAdmin              = "Cannot delete the last active Admin account."
)

// signedIn is the caller, refused while in an acting appointment: it swaps
// the person's permissions in the existing system, and Go does not guess
// which set applies.
func signedIn(ctx context.Context) (auth.Principal, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return auth.Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "Sign in to continue.")
	}
	if principal.InActingAppointment {
		return auth.Principal{}, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonActingNotSupported,
			"Accounts are not available here while you hold an acting appointment. Use the Edify web app.")
	}
	return principal, nil
}

// administrator is a caller who may manage accounts: user.manage in the
// role they are working in (the Admin alone, owner 2026-10-09).
func administrator(ctx context.Context) (auth.Principal, error) {
	principal, err := signedIn(ctx)
	if err != nil {
		return auth.Principal{}, err
	}
	if !rbac.Grants(principal.ActiveRole, rbac.UserManage) {
		return auth.Principal{}, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Only an Admin can manage accounts.")
	}
	return principal, nil
}

// mayAdminister is assert_may_administer: only an Admin touches an Admin's
// account or grants the Admin role. It returns the refusal, or "".
func mayAdminister(principal auth.Principal, targetRoles []string, requested []string) string {
	isAdmin := principal.ActiveRole == rbac.Admin
	if !isAdmin && slices.Contains(targetRoles, rbac.Admin) {
		return msgOnlyAdminModifiesAdmin
	}
	if !isAdmin && slices.Contains(requested, rbac.Admin) {
		return msgOnlyAdminGrantsAdmin
	}
	return ""
}

// rolesOf is the existing list(dict.fromkeys([role, *additional])): the
// opening role first, duplicates dropped, order kept.
func rolesOf(role string, additional []string) []string {
	out := []string{}
	for _, candidate := range append([]string{role}, additional...) {
		if candidate != "" && !slices.Contains(out, candidate) {
			out = append(out, candidate)
		}
	}
	return out
}

// unknownRole names a requested role the existing system does not define.
func unknownRole(roles []string) string {
	for _, role := range roles {
		if !rbac.IsRole(role) {
			return role
		}
	}
	return ""
}
