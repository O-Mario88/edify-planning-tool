package auth

import (
	"context"
	"errors"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/golang-jwt/jwt/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
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
