// Package config reads the gateway's configuration from the environment and
// refuses anything unsafe before a single connection is opened.
package config

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"strings"
)

// Environment names the deployment a process runs in.
type Environment string

const (
	Development Environment = "development"
	Test        Environment = "test"
	Staging     Environment = "staging"
	Production  Environment = "production"
)

// ErrProductionNotApproved is returned for EDIFY_ENV=production. The cutover
// of production traffic is a separate, explicitly approved decision; until it
// is taken this binary cannot be started as a production process at all.
var ErrProductionNotApproved = errors.New(
	"config: EDIFY_ENV=production is refused: production cutover has not been approved for this build",
)

const (
	minSecretLength   = 32
	defaultHTTPAddr   = "127.0.0.1:8090"
	envEnvironment    = "EDIFY_ENV"
	envHTTPAddr       = "EDIFY_HTTP_ADDR"
	envDatabaseURL    = "EDIFY_DATABASE_URL"
	envAllowedHosts   = "EDIFY_DB_ALLOWED_HOSTS"
	envProdMarkers    = "EDIFY_DB_PRODUCTION_MARKERS"
	envJWTSecret      = "EDIFY_JWT_SECRET"
	envAnalyticsAddr  = "EDIFY_ANALYTICS_ADDR"
	envReleaseVersion = "EDIFY_RELEASE"
	envCORSOrigins    = "EDIFY_CORS_ALLOWED_ORIGINS"
	envExistingAppURL = "EDIFY_EXISTING_APP_URL"
)

// weakSecretFragments mark placeholder secrets that must never sign tokens
// outside a developer's machine.
var weakSecretFragments = []string{"change-me", "dev-only", "example", "password"}

// Config is the validated configuration of one gateway process.
type Config struct {
	Env      Environment
	HTTPAddr string
	Release  string

	// DatabaseURL is read from EDIFY_DATABASE_URL only. DATABASE_URL, the
	// existing application's variable, is deliberately never consulted, so a
	// shell or host configured for that application cannot point the gateway
	// at its database by accident.
	DatabaseURL string
	// DBAllowedHosts lists the only database hosts a non-production process
	// may connect to. Development and test also accept loopback.
	DBAllowedHosts []string
	// DBProductionMarkers are extra substrings that identify the production
	// database endpoint, added to the built-in ones.
	DBProductionMarkers []string

	// JWTSecret verifies the HS256 access tokens issued by the existing
	// identity system of the SAME environment.
	JWTSecret string

	// CORSAllowedOrigins lists the browser origins that may call the gateway.
	// Empty (the default) sends no CORS headers at all: the native app does
	// not need them. It exists for the app's web build during development.
	CORSAllowedOrigins []string

	// ExistingAppURL is the base URL of the existing Edify application of the
	// SAME environment. The gateway asks it for the screens whose rules have
	// not been ported yet. Empty disables those screens.
	ExistingAppURL string

	// AnalyticsAddr is the internal gRPC address of the Python analytics
	// worker. Empty disables the worker; the gateway then answers without it.
	AnalyticsAddr string

	// Loans configures the School Loan Application Portal.
	Loans Loans

	// ClusterActions configures the Cluster Action Register's follow-up.
	ClusterActions ClusterActions

	// SignIn configures signing in.
	SignIn SignIn
}

// LoadGuard reads only what the production-protection guard needs, for a
// tool that opens its own connection and serves nothing (cmd/clusterctl).
// Production is refused exactly as Load refuses it.
func LoadGuard(getenv func(string) string) (Config, error) {
	env, err := parseEnvironment(getenv(envEnvironment))
	if err != nil {
		return Config{}, err
	}
	if env == Production {
		return Config{}, ErrProductionNotApproved
	}
	return Config{
		Env:                 env,
		DBAllowedHosts:      splitList(getenv(envAllowedHosts)),
		DBProductionMarkers: splitList(getenv(envProdMarkers)),
	}, nil
}

// Load reads and validates configuration through getenv (os.Getenv in
// production code, a map lookup in tests).
func Load(getenv func(string) string) (Config, error) {
	env, err := parseEnvironment(getenv(envEnvironment))
	if err != nil {
		return Config{}, err
	}
	if env == Production {
		return Config{}, ErrProductionNotApproved
	}

	cfg := Config{
		Env:                 env,
		HTTPAddr:            firstNonEmpty(getenv(envHTTPAddr), defaultHTTPAddr),
		Release:             firstNonEmpty(getenv(envReleaseVersion), "dev"),
		DatabaseURL:         strings.TrimSpace(getenv(envDatabaseURL)),
		DBAllowedHosts:      splitList(getenv(envAllowedHosts)),
		DBProductionMarkers: splitList(getenv(envProdMarkers)),
		JWTSecret:           getenv(envJWTSecret),
		AnalyticsAddr:       strings.TrimSpace(getenv(envAnalyticsAddr)),
		CORSAllowedOrigins:  splitList(getenv(envCORSOrigins)),
		ExistingAppURL:      strings.TrimRight(strings.TrimSpace(getenv(envExistingAppURL)), "/"),
	}

	if cfg.DatabaseURL == "" {
		return Config{}, fmt.Errorf("config: %s is required", envDatabaseURL)
	}
	if err := validateSecret(env, cfg.JWTSecret); err != nil {
		return Config{}, err
	}
	if env == Staging && len(cfg.DBAllowedHosts) == 0 {
		return Config{}, fmt.Errorf(
			"config: %s must name the staging database host explicitly", envAllowedHosts,
		)
	}
	if err := validateOrigins(env, cfg.CORSAllowedOrigins); err != nil {
		return Config{}, err
	}
	if err := validateExistingAppURL(env, cfg.ExistingAppURL); err != nil {
		return Config{}, err
	}
	if cfg.Loans, err = loadLoans(env, getenv); err != nil {
		return Config{}, err
	}
	if cfg.ClusterActions, err = loadClusterActions(getenv); err != nil {
		return Config{}, err
	}
	if cfg.SignIn, err = loadSignIn(env, getenv, cfg.ExistingAppURL); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

// validateOrigins refuses a wildcard everywhere, and anything but an https
// origin in staging.
func validateOrigins(env Environment, origins []string) error {
	for _, origin := range origins {
		if strings.Contains(origin, "*") {
			return fmt.Errorf("config: %s may not contain a wildcard", envCORSOrigins)
		}
		if !strings.HasPrefix(origin, "https://") && !strings.HasPrefix(origin, "http://") {
			return fmt.Errorf("config: %s entries must be origins such as https://host (got %q)", envCORSOrigins, origin)
		}
		if env == Staging && !strings.HasPrefix(origin, "https://") {
			return fmt.Errorf("config: %s must be https in staging (got %q)", envCORSOrigins, origin)
		}
	}
	return nil
}

// productionSite is the production application's host. No build that can
// run today may call it.
const productionSite = "edifyplanning.app"

// validateExistingAppURL keeps the gateway pointed at the existing
// application of its own environment: this machine in development and test,
// an https host in staging, and never the production site.
func validateExistingAppURL(env Environment, raw string) error {
	if raw == "" {
		return nil
	}
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Host == "" || parsed.Path != "" {
		return fmt.Errorf("config: %s must be a base URL such as https://host", envExistingAppURL)
	}
	host := strings.ToLower(parsed.Hostname())
	if host == productionSite || strings.HasSuffix(host, "."+productionSite) {
		return fmt.Errorf("config: %s points at the production site; this build may not use it", envExistingAppURL)
	}
	ip := net.ParseIP(host)
	local := host == "localhost" || (ip != nil && ip.IsLoopback())
	switch {
	case env == Staging && (parsed.Scheme != "https" || local):
		return fmt.Errorf("config: %s must be an https staging host", envExistingAppURL)
	case env != Staging && !local:
		return fmt.Errorf("config: %s must be on this machine in %s", envExistingAppURL, env)
	}
	return nil
}

func parseEnvironment(raw string) (Environment, error) {
	switch env := Environment(strings.ToLower(strings.TrimSpace(raw))); env {
	case Development, Test, Staging, Production:
		return env, nil
	case "":
		return "", fmt.Errorf("config: %s is required (development, test or staging)", envEnvironment)
	default:
		return "", fmt.Errorf("config: unknown %s %q", envEnvironment, raw)
	}
}

func validateSecret(env Environment, secret string) error {
	if len(secret) < minSecretLength {
		return fmt.Errorf("config: %s must be at least %d characters", envJWTSecret, minSecretLength)
	}
	if env != Staging {
		return nil
	}
	lowered := strings.ToLower(secret)
	for _, fragment := range weakSecretFragments {
		if strings.Contains(lowered, fragment) {
			return fmt.Errorf("config: %s looks like a placeholder; staging needs its own generated secret", envJWTSecret)
		}
	}
	return nil
}

func splitList(raw string) []string {
	var items []string
	for _, part := range strings.Split(raw, ",") {
		if item := strings.ToLower(strings.TrimSpace(part)); item != "" {
			items = append(items, item)
		}
	}
	return items
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			return trimmed
		}
	}
	return ""
}
