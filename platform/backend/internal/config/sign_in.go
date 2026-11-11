package config

import (
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"net/url"
	"strings"
)

// SignIn configures signing in, which Go owns (owner brief, 2026-11-11).
// The lockout and token lifetimes are the existing application's defaults,
// fixed in internal/signin; what differs between deployments is read here.
type SignIn struct {
	// FieldEncryptionKey opens authenticator-app secrets stored by the
	// existing application: its FIELD_ENCRYPTION_KEY of the SAME environment.
	// Empty means a sign-in by authenticator app cannot be checked here.
	FieldEncryptionKey string
	// MFARequiredForAll and MFARequiredRoles are the existing
	// MFA_REQUIRED_FOR_ALL and MFA_REQUIRED_ROLES, and must match them.
	MFARequiredForAll bool
	MFARequiredRoles  []string
	// AppBaseURL is where a password reset link points (the existing
	// application's APP_BASE_URL, whose page sets the new password). Empty
	// in staging until it is set, and then no reset link is mailed.
	AppBaseURL string
}

const (
	envFieldKey       = "EDIFY_FIELD_ENCRYPTION_KEY"
	envMFAForAll      = "EDIFY_MFA_REQUIRED_FOR_ALL"
	envMFARoles       = "EDIFY_MFA_REQUIRED_ROLES"
	envAppBaseURL     = "EDIFY_APP_BASE_URL"
	defaultAppBaseURL = "http://localhost:3000"
)

func loadSignIn(env Environment, getenv func(string) string, existingApp string) (SignIn, error) {
	fallback := defaultAppBaseURL
	if env == Staging {
		fallback = ""
	}
	out := SignIn{
		FieldEncryptionKey: strings.TrimSpace(getenv(envFieldKey)),
		AppBaseURL:         strings.TrimRight(firstNonEmpty(getenv(envAppBaseURL), existingApp, fallback), "/"),
	}
	switch strings.ToLower(strings.TrimSpace(getenv(envMFAForAll))) {
	case "", "0", "false", "no", "off":
	case "1", "true", "yes", "on":
		out.MFARequiredForAll = true
	default:
		return SignIn{}, fmt.Errorf("config: %s must be true or false", envMFAForAll)
	}
	// Roles keep their case: they are the existing role names.
	for _, role := range strings.Split(getenv(envMFARoles), ",") {
		if role = strings.TrimSpace(role); role != "" {
			out.MFARequiredRoles = append(out.MFARequiredRoles, role)
		}
	}
	if out.FieldEncryptionKey != "" && !isFieldKey(out.FieldEncryptionKey) {
		return SignIn{}, fmt.Errorf("config: %s must be 32 bytes (64 hex characters or base64)", envFieldKey)
	}
	if out.AppBaseURL == "" {
		return out, nil
	}
	parsed, err := url.Parse(out.AppBaseURL)
	if err != nil || parsed.Host == "" || (parsed.Scheme != "https" && parsed.Scheme != "http") {
		return SignIn{}, fmt.Errorf("config: %s must be a base URL such as https://host", envAppBaseURL)
	}
	host := strings.ToLower(parsed.Hostname())
	if host == productionSite || strings.HasSuffix(host, "."+productionSite) {
		return SignIn{}, fmt.Errorf("config: %s points at the production site; this build may not use it", envAppBaseURL)
	}
	if env == Staging && parsed.Scheme != "https" {
		return SignIn{}, fmt.Errorf("config: %s must be https in staging", envAppBaseURL)
	}
	return out, nil
}

// isFieldKey is the existing key format: 64 hex characters or base64 of 32
// bytes.
func isFieldKey(raw string) bool {
	if decoded, err := hex.DecodeString(raw); err == nil && len(raw) == 64 {
		return len(decoded) == 32
	}
	decoded, err := base64.StdEncoding.DecodeString(raw)
	return err == nil && len(decoded) == 32
}
