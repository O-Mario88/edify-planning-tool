package auth

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/golang-jwt/jwt/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

const testSecret = "unit-test-signing-secret-0123456789abcdef"

var fixedNow = time.Date(2026, 11, 9, 12, 0, 0, 0, time.UTC)

// sign mints a token the way the existing identity system does:
// {sub, activeRole, iat, exp}, HS256.
func sign(t *testing.T, method jwt.SigningMethod, key any, claims jwt.MapClaims) string {
	t.Helper()
	token, err := jwt.NewWithClaims(method, claims).SignedString(key)
	if err != nil {
		t.Fatal(err)
	}
	return token
}

func validClaims() jwt.MapClaims {
	return jwt.MapClaims{
		"sub":        "user-1",
		"activeRole": "CCEO",
		"iat":        fixedNow.Add(-time.Minute).Unix(),
		"exp":        fixedNow.Add(14 * time.Minute).Unix(),
	}
}

func TestVerify(t *testing.T) {
	verifier := NewVerifier(testSecret, func() time.Time { return fixedNow })

	expired := validClaims()
	expired["exp"] = fixedNow.Add(-time.Second).Unix()
	noExpiry := validClaims()
	delete(noExpiry, "exp")
	noSubject := validClaims()
	delete(noSubject, "sub")

	tests := []struct {
		name    string
		token   string
		wantErr error
	}{
		{name: "valid", token: sign(t, jwt.SigningMethodHS256, []byte(testSecret), validClaims())},
		{name: "expired", token: sign(t, jwt.SigningMethodHS256, []byte(testSecret), expired), wantErr: ErrTokenExpired},
		{name: "wrong secret", token: sign(t, jwt.SigningMethodHS256, []byte("another-secret-another-secret-12345"), validClaims()), wantErr: ErrTokenInvalid},
		{name: "no expiry", token: sign(t, jwt.SigningMethodHS256, []byte(testSecret), noExpiry), wantErr: ErrTokenInvalid},
		{name: "no subject", token: sign(t, jwt.SigningMethodHS256, []byte(testSecret), noSubject), wantErr: ErrTokenInvalid},
		{name: "alg none", token: sign(t, jwt.SigningMethodNone, jwt.UnsafeAllowNoneSignatureType, validClaims()), wantErr: ErrTokenInvalid},
		{name: "another HMAC size", token: sign(t, jwt.SigningMethodHS512, []byte(testSecret), validClaims()), wantErr: ErrTokenInvalid},
		{name: "garbage", token: "not.a.token", wantErr: ErrTokenInvalid},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			claims, err := verifier.Verify(test.token)
			if !errors.Is(err, test.wantErr) {
				t.Fatalf("want %v, got %v", test.wantErr, err)
			}
			if test.wantErr == nil && (claims.UserID != "user-1" || claims.ActiveRole != "CCEO") {
				t.Fatalf("claims: %+v", claims)
			}
		})
	}
}

type fakeAccounts struct {
	account Account
	err     error
}

func (f fakeAccounts) LoadAccount(context.Context, string) (Account, error) {
	return f.account, f.err
}

func TestAuthenticate(t *testing.T) {
	verifier := NewVerifier(testSecret, func() time.Time { return fixedNow })
	valid := "Bearer " + sign(t, jwt.SigningMethodHS256, []byte(testSecret), validClaims())
	live := Account{UserID: "user-1", Roles: []string{"CCEO", "Program Lead"}, ActiveRole: "Program Lead", Status: "active"}
	single := Account{UserID: "user-1", Roles: []string{"Program Lead"}, ActiveRole: "Program Lead", Status: "active"}
	suspended := live
	suspended.Status = "suspended"
	// Edify Global (docs/migration/80, §12): Uganda's roles stay the
	// profile's; Kenya's are the registry's.
	inUganda := live
	inUganda.Country = &country.Work{Country: country.Country{Code: "UG", Name: "Uganda"}, RolesSource: country.RolesFromProfile}
	kenya := func(roles ...string) *country.Work {
		w := &country.Work{Country: country.Country{Code: "KE", Name: "Kenya"}, RolesSource: country.RolesFromRegistry, MembershipID: "m1"}
		for _, role := range roles {
			w.Roles = append(w.Roles, country.Assigned{Role: role, ScopeType: country.ScopePortfolio})
		}
		return w
	}
	officerInKenya, assessorInKenya, nobodyInKenya, adminInKenya := live, live, live, live
	officerInKenya.Country = kenya("CCEO")
	assessorInKenya.Country = kenya("ImpactAssessment")
	nobodyInKenya.Country = kenya()
	adminInKenya.Roles, adminInKenya.ActiveRole, adminInKenya.Country = []string{"Admin"}, "Admin", kenya()

	tests := []struct {
		name       string
		header     string
		accounts   fakeAccounts
		wantCode   connect.Code
		wantReason string
		wantRole   string
	}{
		{name: "token role held by the account wins", header: valid, accounts: fakeAccounts{account: live}, wantRole: "CCEO"},
		{name: "token role no longer held falls back", header: valid, accounts: fakeAccounts{account: single}, wantRole: "Program Lead"},
		{name: "Uganda keeps the profile's roles", header: valid, accounts: fakeAccounts{account: inUganda}, wantRole: "CCEO"},
		{name: "a role assigned in Kenya", header: valid, accounts: fakeAccounts{account: officerInKenya}, wantRole: "CCEO"},
		{name: "a profile role not assigned in Kenya", header: valid, accounts: fakeAccounts{account: assessorInKenya}, wantRole: "ImpactAssessment"},
		{name: "no role in Kenya", header: valid, accounts: fakeAccounts{account: nobodyInKenya}, wantCode: connect.CodePermissionDenied, wantReason: apierr.ReasonPermissionDenied},
		{name: "an Admin is the platform's", header: valid, accounts: fakeAccounts{account: adminInKenya}, wantRole: "Admin"},
		{name: "no header", header: "", wantCode: connect.CodeUnauthenticated, wantReason: apierr.ReasonAuthMissing},
		{name: "not a bearer token", header: "Basic abc", wantCode: connect.CodeUnauthenticated, wantReason: apierr.ReasonAuthMissing},
		{name: "empty bearer token", header: "Bearer  ", wantCode: connect.CodeUnauthenticated, wantReason: apierr.ReasonAuthMissing},
		{name: "invalid token", header: "Bearer nope", wantCode: connect.CodeUnauthenticated, wantReason: apierr.ReasonAuthInvalid},
		{name: "deactivated or deleted account", header: valid, accounts: fakeAccounts{err: ErrAccountNotFound}, wantCode: connect.CodeUnauthenticated, wantReason: apierr.ReasonAuthInvalid},
		{name: "suspended account", header: valid, accounts: fakeAccounts{account: suspended}, wantCode: connect.CodePermissionDenied, wantReason: apierr.ReasonAccountInactive},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			principal, err := NewAuthenticator(verifier, test.accounts).Authenticate(context.Background(), test.header)
			if test.wantReason == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				if principal.ActiveRole != test.wantRole {
					t.Fatalf("active role %q, want %q", principal.ActiveRole, test.wantRole)
				}
				return
			}
			if connect.CodeOf(err) != test.wantCode || apierr.Reason(err) != test.wantReason {
				t.Fatalf("got %v / %q, want %v / %q", connect.CodeOf(err), apierr.Reason(err), test.wantCode, test.wantReason)
			}
		})
	}
}

func TestAuthenticateReportsStoreFailuresAsPlainErrors(t *testing.T) {
	verifier := NewVerifier(testSecret, func() time.Time { return fixedNow })
	header := "Bearer " + sign(t, jwt.SigningMethodHS256, []byte(testSecret), validClaims())
	_, err := NewAuthenticator(verifier, fakeAccounts{err: errors.New("connection reset")}).Authenticate(context.Background(), header)

	var connectErr *connect.Error
	if err == nil || errors.As(err, &connectErr) {
		t.Fatalf("a store failure must stay an internal error for the interceptor to hide, got %v", err)
	}
}

func TestRolesInCountry(t *testing.T) {
	acting := &ActingAppointment{AppointmentID: "a1", AppointeeRole: "CCEO", InCapacity: true}
	account := Account{UserID: "u1", Roles: []string{"CCEO", "Program Lead"}, ActiveRole: "Program Lead", Acting: acting,
		Country: &country.Work{Country: country.Country{Code: "KE", Name: "Kenya"}, RolesSource: country.RolesFromRegistry,
			Roles: []country.Assigned{{Role: "CCEO"}, {Role: "CCEO"}, {Role: "ImpactAssessment"}, {Role: "RegionalProgramLead"}}}}
	got, ok := rolesInCountry(account)
	if !ok || strings.Join(got.Roles, ",") != "CCEO,ImpactAssessment" || got.ActiveRole != "CCEO" || got.Acting != nil {
		t.Errorf("in Kenya: %+v (%v); want the roles assigned there, the first active, no acting appointment", got, ok)
	}
	if held, ok := got.HeldInCountry(); !ok || held.Role != "CCEO" {
		t.Errorf("the role held in Kenya: %+v (%v)", held, ok)
	}
	// A regional role assigned in one country (none can be now) is not held
	// there: it is the profile's, across every country.
	got.ActiveRole = "RegionalProgramLead"
	if held, ok := got.HeldInCountry(); ok {
		t.Errorf("a regional role is held through Kenya: %+v", held)
	}

	// A regional role on the profile works across every country, so it is
	// kept beside the roles assigned there (owner, 2026-11-18).
	regional := account
	regional.Roles, regional.ActiveRole = []string{"CCEO", "RegionalVicePresident"}, "RegionalVicePresident"
	if got, ok := rolesInCountry(regional); !ok || got.ActiveRole != "RegionalVicePresident" ||
		strings.Join(got.Roles, ",") != "CCEO,ImpactAssessment,RegionalVicePresident" {
		t.Errorf("a regional role in Kenya: %+v (%v)", got, ok)
	}
	onlyRegional := regional
	onlyRegional.Country = &country.Work{Country: country.Country{Code: "KE", Name: "Kenya"}, RolesSource: country.RolesFromRegistry}
	if got, ok := rolesInCountry(onlyRegional); !ok || strings.Join(got.Roles, ",") != "RegionalVicePresident" {
		t.Errorf("a regional role with nothing assigned in Kenya is refused or changed: %+v (%v)", got, ok)
	}

	account.Country.RolesSource = country.RolesFromProfile
	if got, ok := rolesInCountry(account); !ok || len(got.Roles) != 2 || got.Acting == nil {
		t.Errorf("in Uganda: %+v (%v); want the profile's roles untouched", got, ok)
	}
	if _, ok := account.HeldInCountry(); ok {
		t.Error("a role is held through the registry in Uganda")
	}
	account.Country = nil
	if got, ok := rolesInCountry(account); !ok || len(got.Roles) != 2 {
		t.Errorf("in no country: %+v (%v); want unchanged", got, ok)
	}
}
