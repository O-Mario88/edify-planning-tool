package schools

import (
	"context"

	"connectrpc.com/connect"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Role values of the existing system (apps/core/rbac.py, EdifyRole).
const (
	roleCCEO        = "CCEO"
	roleProgramLead = "Program Lead"
)

// directPortfolioRoles are the roles this slice serves. Both hold the
// existing `schoolDirectory.view` permission, and for both the existing
// School Directory lists the direct portfolio: operating schools with a
// `staff_school_assignment` row for the person's own staff profile.
//
// This is deliberately a strict SUBSET of what the existing application
// shows. Temporary coverage, supervised teams, country and region reach,
// project and partner portfolios are not served here; each arrives with the
// migration step that owns it (docs/migration/04-migration-plan.md). A caller
// can therefore never see a school through the gateway that the existing
// application would withhold.
var directPortfolioRoles = map[string]bool{
	roleCCEO:        true,
	roleProgramLead: true,
}

// authorize decides whether the caller may read a direct portfolio at all.
func authorize(ctx context.Context) (auth.Principal, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return auth.Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing,
			"Sign in to continue.")
	}
	// An acting appointment swaps the person's permission set in the existing
	// system. Until that rule is migrated the gateway refuses rather than
	// guess which set applies.
	if principal.InActingAppointment {
		return auth.Principal{}, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonActingNotSupported,
			"Schools are not available here while you hold an acting appointment. Use the Edify web app.")
	}
	if !directPortfolioRoles[principal.ActiveRole] {
		return auth.Principal{}, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonRoleNotMigrated,
			"Schools are not available here for your role yet. Use the Edify web app.")
	}
	return principal, nil
}
