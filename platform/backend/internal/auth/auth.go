// Package auth authenticates gateway requests against the existing Edify
// identity system.
//
// The gateway issues nothing. Sign-in, MFA, lockout and refresh-token rotation
// stay in the existing application; it mints a short-lived HS256 access token
// carrying {sub: user id, activeRole}. This package verifies that token and
// then re-reads the account on every request, so a deactivated or deleted
// account stops working at once rather than when its token expires.
package auth

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/golang-jwt/jwt/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

const (
	bearerPrefix      = "Bearer "
	signingAlgorithm  = "HS256"
	accountStatusLive = "active"
	// roleAdmin is the platform's own role: it is never held per country.
	roleAdmin = "Admin"
)

// ErrAccountNotFound is returned by an AccountLoader when no usable account
// has the given id.
var ErrAccountNotFound = errors.New("auth: account not found or inactive")

// ErrTokenExpired and ErrTokenInvalid are the two ways verification fails.
var (
	ErrTokenExpired = errors.New("auth: token expired")
	ErrTokenInvalid = errors.New("auth: token invalid")
)

// Claims are the fields of the existing access token the gateway reads.
type Claims struct {
	UserID     string
	ActiveRole string
}

// Account is the existing account record, as far as the gateway needs it.
type Account struct {
	UserID string
	Email  string
	Name   string
	Roles  []string
	// ActiveRole is the account's stored role when loaded, and the role the
	// request is made in once the account is part of a Principal.
	ActiveRole     string
	Status         string
	StaffProfileID string
	// Acting is the acting appointment the person holds today, when it is
	// active and still stands (apps.acting.services.still_valid); nil
	// otherwise. Whether they are working in it is InActingAppointment.
	Acting *ActingAppointment
	// InActingAppointment is true while the person is working in an acting
	// capacity: the appointment is switched on and the request is made in
	// the role it was made from. The existing system then presents them in
	// the acting role, inside the appointing leader's seat; modules that
	// have not taken that seat over refuse rather than guess.
	InActingAppointment bool
	// MustChangePassword: an administrator chose the password, and it must
	// be replaced before anything else (the existing PasswordChangeMiddleware).
	MustChangePassword bool
	// Country is the Edify Global country the request is made in, nil when
	// the account works in no Active country (docs/migration/80, §12). Where
	// its roles come from the registry, Authenticate narrows Roles and
	// ActiveRole to the roles the account holds there.
	Country *country.Work
}

// ActingAppointment is the acting appointment a person holds today
// (acting_assignment), as far as a request needs it.
type ActingAppointment struct {
	AppointmentID string
	RoleKey       string
	// ActingRole is the role whose operational capability set it delegates;
	// AppointeeRole the permanent role it was made from.
	ActingRole    string
	AppointeeRole string
	Label         string
	ShortLabel    string
	MonthLabel    string
	SeatStaffID   string
	SeatName      string
	ScopeType     string
	Country       string
	// InCapacity is the appointee's own switch (in_capacity).
	InCapacity bool
}

// WorkingIn says whether a request made in role is made in the acting
// capacity (apps.acting.services.attach).
func (a *ActingAppointment) WorkingIn(role string) bool {
	return a != nil && a.InCapacity && role == a.AppointeeRole
}

// Principal is the authenticated caller of one request.
type Principal struct {
	Account
}

// Verifier checks access tokens.
type Verifier struct {
	secret []byte
	now    func() time.Time
}

// NewVerifier returns a Verifier for the environment's signing secret.
func NewVerifier(secret string, now func() time.Time) *Verifier {
	if now == nil {
		now = time.Now
	}
	return &Verifier{secret: []byte(secret), now: now}
}

type tokenClaims struct {
	ActiveRole string `json:"activeRole"`
	jwt.RegisteredClaims
}

// Verify returns the claims of a valid token. Only HS256 is accepted and an
// expiry is mandatory, so neither "alg: none" nor a non-expiring token passes.
func (v *Verifier) Verify(raw string) (Claims, error) {
	var claims tokenClaims
	_, err := jwt.ParseWithClaims(raw, &claims,
		func(*jwt.Token) (any, error) { return v.secret, nil },
		jwt.WithValidMethods([]string{signingAlgorithm}),
		jwt.WithExpirationRequired(),
		jwt.WithTimeFunc(v.now),
	)
	switch {
	case errors.Is(err, jwt.ErrTokenExpired):
		return Claims{}, ErrTokenExpired
	case err != nil:
		return Claims{}, fmt.Errorf("%w: %v", ErrTokenInvalid, err)
	case claims.Subject == "":
		return Claims{}, fmt.Errorf("%w: no subject", ErrTokenInvalid)
	}
	return Claims{UserID: claims.Subject, ActiveRole: claims.ActiveRole}, nil
}

// AccountLoader reads the existing account for a user id.
type AccountLoader interface {
	LoadAccount(ctx context.Context, userID string) (Account, error)
}

// Authenticator turns an Authorization header into a Principal.
type Authenticator struct {
	verifier *Verifier
	accounts AccountLoader
}

// NewAuthenticator wires token verification to the account store.
func NewAuthenticator(verifier *Verifier, accounts AccountLoader) *Authenticator {
	return &Authenticator{verifier: verifier, accounts: accounts}
}

// Authenticate verifies the bearer token in header and loads its account.
// Every failure is a structured Unauthenticated or PermissionDenied error.
func (a *Authenticator) Authenticate(ctx context.Context, header string) (Principal, error) {
	if !strings.HasPrefix(header, bearerPrefix) || strings.TrimSpace(header[len(bearerPrefix):]) == "" {
		return Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing,
			"Sign in to continue.")
	}
	claims, err := a.verifier.Verify(strings.TrimSpace(header[len(bearerPrefix):]))
	if errors.Is(err, ErrTokenExpired) {
		return Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthExpired,
			"Your session has expired. Please sign in again.")
	}
	if err != nil {
		return Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthInvalid,
			"Invalid authentication token.")
	}

	account, err := a.accounts.LoadAccount(ctx, claims.UserID)
	if errors.Is(err, ErrAccountNotFound) {
		return Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthInvalid,
			"User not found or inactive.")
	}
	if err != nil {
		return Principal{}, fmt.Errorf("auth: loading account: %w", err)
	}
	if account.Status != accountStatusLive {
		return Principal{}, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonAccountInactive,
			"This account is not active.")
	}
	account, inCountry := rolesInCountry(account)
	if !inCountry {
		return Principal{}, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			fmt.Sprintf("Your account has no role in %s yet. An Admin assigns the roles you hold there.", account.Country.Name))
	}
	account.ActiveRole = resolveActiveRole(claims.ActiveRole, account)
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	return Principal{Account: account}, nil
}

// rolesInCountry is the account as it works in the country the request is
// made in. Where that country's roles are the existing profile's (Uganda's),
// or the account is an Admin (a platform role, held in no one country), or it
// works in no Active country, nothing changes. Where they come from the
// registry, the account holds the roles assigned to it there and, from its
// profile, any regional role (country.IsRegional: those work across every
// country, as Admin does): its
// stored role counts only when it is one of them, the first assigned
// otherwise, and an acting appointment (the existing application's, made
// in Uganda) does not travel. false when it holds no role there at all.
func rolesInCountry(account Account) (Account, bool) {
	if !account.Country.FromRegistry() || slices.Contains(account.Roles, roleAdmin) {
		return account, true
	}
	roles := []string{}
	for _, held := range account.Country.Roles {
		if held.Role != roleAdmin && !country.IsRegional(held.Role) && !slices.Contains(roles, held.Role) {
			roles = append(roles, held.Role)
		}
	}
	for _, role := range account.Roles {
		if country.IsRegional(role) && !slices.Contains(roles, role) {
			roles = append(roles, role)
		}
	}
	if len(roles) == 0 {
		return account, false
	}
	account.Roles = roles
	if !slices.Contains(roles, account.ActiveRole) {
		account.ActiveRole = roles[0]
	}
	account.Acting = nil
	return account, true
}

// HeldInCountry is the assignment of the request's role in the country the
// request is made in, when that country's roles come from the registry; the
// role's scope there is the assignment's, not the existing profile's.
func (a Account) HeldInCountry() (country.Assigned, bool) {
	// A regional role is never held in one country: it works across every
	// one (country.IsRegional), even where an older assignment names it.
	if !a.Country.FromRegistry() || country.IsRegional(a.ActiveRole) {
		return country.Assigned{}, false
	}
	for _, held := range a.Country.Roles {
		if held.Role == a.ActiveRole {
			return held, true
		}
	}
	return country.Assigned{}, false
}

// resolveActiveRole mirrors the existing rule: the token's role counts only
// when the account still holds it; otherwise the account's own active role.
func resolveActiveRole(tokenRole string, account Account) string {
	for _, role := range account.Roles {
		if role == tokenRole {
			return tokenRole
		}
	}
	return account.ActiveRole
}

type principalKey struct{}

// WithPrincipal returns a context carrying the authenticated caller.
func WithPrincipal(ctx context.Context, principal Principal) context.Context {
	return context.WithValue(ctx, principalKey{}, principal)
}

// SettingsName is the name the existing tables key the request's country's
// settings by (country.SettingsName): existing, Uganda's, unless the request
// is made by a caller working in a country whose roles come from the
// registry. Code reached without a caller (a job, a command) reads Uganda's.
func SettingsName(ctx context.Context, existing string) string {
	if p, ok := PrincipalFrom(ctx); ok {
		return country.SettingsName(p.Country, existing)
	}
	return existing
}

// PrincipalFrom returns the authenticated caller, if the request has one.
func PrincipalFrom(ctx context.Context) (Principal, bool) {
	principal, ok := ctx.Value(principalKey{}).(Principal)
	return principal, ok
}

// Procedures open while a new password is owed: reading who you are, and
// setting it. Everything else waits, as the existing
// apps/accounts/middleware.py keeps the web on its change-password page.
var openWhilePasswordOwed = map[string]bool{
	"/edify.identity.v1.IdentityService/GetSession":    true,
	"/edify.identity.v1.AccountService/SetNewPassword": true,
}

// Interceptor authenticates every unary call before its handler runs.
func (a *Authenticator) Interceptor() connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, request connect.AnyRequest) (connect.AnyResponse, error) {
			principal, err := a.Authenticate(ctx, request.Header().Get("Authorization"))
			if err != nil {
				return nil, err
			}
			if principal.MustChangePassword && !openWhilePasswordOwed[request.Spec().Procedure] {
				return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonPasswordChangeRequired,
					"Set a new password to continue.")
			}
			ctx = WithBearer(WithPrincipal(ctx, principal), bearerOf(request.Header().Get("Authorization")))
			return next(ctx, request)
		}
	}
}

type bearerKey struct{}

// WithBearer returns a context carrying the caller's verified access token,
// for the one place that forwards it: the feed from the existing application.
func WithBearer(ctx context.Context, token string) context.Context {
	return context.WithValue(ctx, bearerKey{}, token)
}

// BearerFrom returns the caller's verified access token, or "".
func BearerFrom(ctx context.Context) string {
	token, _ := ctx.Value(bearerKey{}).(string)
	return token
}

func bearerOf(header string) string {
	return strings.TrimSpace(strings.TrimPrefix(header, bearerPrefix))
}
