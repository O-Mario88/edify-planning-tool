package clusterlead

import (
	"context"

	"connectrpc.com/connect"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Role values of the existing system (apps/core/rbac.py, EdifyRole).
const (
	RoleClusterLeader = "ClusterLeader"
	roleAdmin         = "Admin"
	roleProgramLead   = "Program Lead"
	roleCCEO          = "CCEO"
)

// The assignment policy (brief A1: "Authorized program managers may propose
// or manage cluster-leadership assignments according to a specifically
// approved permission policy; assignment must not implicitly grant
// user-administration powers"):
//
//   - Admin and Program Lead may manage the leaders of any cluster;
//   - a CCEO may manage the leaders of the clusters they are responsible for
//     (cluster.responsible_staff_id is their staff profile);
//   - nobody else may, a Cluster Leader included.
//
// Managing an assignment never creates an account or gives a role: the
// account must already hold the Cluster Leader role, which only the people
// who manage users can give it.
var anyClusterAdministrators = map[string]bool{
	roleAdmin:       true,
	roleProgramLead: true,
}

func principalOf(ctx context.Context) (auth.Principal, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return auth.Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing,
			"Sign in to continue.")
	}
	// An acting appointment swaps the person's permission set in the existing
	// system; the gateway refuses rather than guess which applies.
	if principal.InActingAppointment {
		return auth.Principal{}, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonActingNotSupported,
			"Cluster leadership is not available here while you hold an acting appointment. Use the Edify web app.")
	}
	return principal, nil
}

// leader is the caller when they sign in as a Cluster Leader.
func leader(ctx context.Context) (auth.Principal, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return auth.Principal{}, err
	}
	if principal.ActiveRole != RoleClusterLeader {
		return auth.Principal{}, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonRoleNotMigrated,
			"The Cluster Leader Portal is for Cluster Leaders.")
	}
	return principal, nil
}

// mayAdminister says whether principal may manage cluster's leaders.
func mayAdminister(principal auth.Principal, cluster Cluster) bool {
	if anyClusterAdministrators[principal.ActiveRole] {
		return true
	}
	return principal.ActiveRole == roleCCEO &&
		principal.StaffProfileID != "" &&
		cluster.ResponsibleStaffID == principal.StaffProfileID
}

func notYours(ctx context.Context) error {
	return apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
		"This cluster is not assigned to you.")
}

func notAdministrator(ctx context.Context) error {
	return apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
		"You may not manage this cluster's leaders.")
}
