package loans

import (
	"context"

	"connectrpc.com/connect"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// Role values of the existing system (apps/core/rbac.py, EdifyRole).
const (
	roleBTO             = "BusinessTransformationOfficer"
	roleCountryDirector = "CountryDirector"
	roleRVP             = "RegionalVicePresident"
	roleMFIAdmin        = "MfiPartnerAdmin"
	roleMFIOfficer      = "MfiLoanOfficer"
)

// Who sees what follows the existing permission model (apps/core/rbac.py):
//
//   - the BTO holds businessTransformation.portfolio.view and
//     .sensitive.view: every application, in full, and the follow-up work;
//   - the Country Director holds the same views and .mfi.manage: every
//     application, oversight follow-ups, and the lenders' receiving
//     addresses;
//   - the RVP holds only businessTransformation.view (rbac.py: "RVP is
//     summary-only"): the dashboard and a consolidated list without the
//     director's contact details or the school's fees, and oversight notes;
//   - a lender's own staff (MfiPartnerAdmin, MfiLoanOfficer) see only the
//     applications addressed to their lender;
//   - Admin, as in the existing system, has no record-level lending access
//     ("a technical super-role has no implicit governed lending authority").
//
// Nobody sees the director's religion on a record; it exists only in totals.
type access struct {
	role          string
	full          bool // every field of every application
	summaryOnly   bool // the RVP's consolidated view
	followsUp     bool // records follow-ups, matches schools, resends, withdraws
	oversight     bool // records oversight notes
	managesLender bool // lender receiving addresses and the referral switch
}

var staffAccess = map[string]access{
	roleBTO:             {role: roleBTO, full: true, followsUp: true},
	roleCountryDirector: {role: roleCountryDirector, full: true, oversight: true, managesLender: true},
	roleRVP:             {role: roleRVP, summaryOnly: true, oversight: true},
}

func principalOf(ctx context.Context) (auth.Principal, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return auth.Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing,
			"Sign in to continue.")
	}
	if principal.InActingAppointment {
		return auth.Principal{}, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonActingNotSupported,
			"Loan referrals are not available here while you hold an acting appointment. Use the Edify web app.")
	}
	return principal, nil
}

// staff is the caller when their active role may track loan referrals.
func staff(ctx context.Context) (auth.Principal, access, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return auth.Principal{}, access{}, err
	}
	granted, ok := staffAccess[principal.ActiveRole]
	if !ok {
		return auth.Principal{}, access{}, denied(ctx, "Your role cannot see school loan referrals.")
	}
	return principal, granted, nil
}

// countryBound is the countries a staff caller's loan records are kept to
// (docs/migration/80, §20): nil — every country — for the regional roles
// (the BTO and the RVP work across every country, §15) and the Admin; the
// one the Country Director works in, or one id that matches no country
// while they work in none.
func countryBound(p auth.Principal) []string {
	switch {
	case registry.IsRegional(p.ActiveRole) || p.ActiveRole == "Admin":
		return nil
	case p.Country != nil:
		return []string{p.Country.ID}
	}
	return []string{""}
}

func denied(ctx context.Context, message string) error {
	return apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, message)
}

// IsLenderRole says whether a role is a lender's own staff.
func IsLenderRole(role string) bool { return role == roleMFIAdmin || role == roleMFIOfficer }
