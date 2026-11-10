package config

import (
	"errors"
	"strings"
	"testing"
)

const strongSecret = "9f2c7a1e5b8d4c3f6a0e1d2b7c8f9a4e5d6c7b8a"

func env(values map[string]string) func(string) string {
	return func(key string) string { return values[key] }
}

func TestLoadRefusesProduction(t *testing.T) {
	_, err := Load(env(map[string]string{
		"EDIFY_ENV":          "production",
		"EDIFY_DATABASE_URL": "postgresql://localhost/edify",
		"EDIFY_JWT_SECRET":   strongSecret,
	}))
	if !errors.Is(err, ErrProductionNotApproved) {
		t.Fatalf("want ErrProductionNotApproved, got %v", err)
	}
}

func TestLoadIgnoresTheExistingApplicationsDatabaseURL(t *testing.T) {
	_, err := Load(env(map[string]string{
		"EDIFY_ENV":        "development",
		"DATABASE_URL":     "postgresql://localhost/edify_pm",
		"EDIFY_JWT_SECRET": strongSecret,
	}))
	if err == nil || !strings.Contains(err.Error(), "EDIFY_DATABASE_URL is required") {
		t.Fatalf("DATABASE_URL must never be used; got %v", err)
	}
}

func TestLoadValidation(t *testing.T) {
	valid := map[string]string{
		"EDIFY_ENV":          "development",
		"EDIFY_DATABASE_URL": "postgresql://localhost/edify_dev",
		"EDIFY_JWT_SECRET":   strongSecret,
	}
	tests := []struct {
		name      string
		overrides map[string]string
		wantErr   string
	}{
		{name: "valid development"},
		{name: "missing environment", overrides: map[string]string{"EDIFY_ENV": ""}, wantErr: "EDIFY_ENV is required"},
		{name: "unknown environment", overrides: map[string]string{"EDIFY_ENV": "prod"}, wantErr: "unknown EDIFY_ENV"},
		{name: "short secret", overrides: map[string]string{"EDIFY_JWT_SECRET": "short"}, wantErr: "at least 32"},
		{
			name:      "staging needs an explicit database host",
			overrides: map[string]string{"EDIFY_ENV": "staging"},
			wantErr:   "EDIFY_DB_ALLOWED_HOSTS",
		},
		{
			name: "staging refuses a placeholder secret",
			overrides: map[string]string{
				"EDIFY_ENV":              "staging",
				"EDIFY_DB_ALLOWED_HOSTS": "staging-db.internal",
				"EDIFY_JWT_SECRET":       "change-me-change-me-change-me-change-me",
			},
			wantErr: "placeholder",
		},
		{
			name: "valid staging",
			overrides: map[string]string{
				"EDIFY_ENV":              "staging",
				"EDIFY_DB_ALLOWED_HOSTS": " Staging-DB.internal , ",
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			values := map[string]string{}
			for key, value := range valid {
				values[key] = value
			}
			for key, value := range test.overrides {
				values[key] = value
			}
			cfg, err := Load(env(values))
			if test.wantErr == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				if cfg.HTTPAddr != defaultHTTPAddr {
					t.Errorf("default address: got %q", cfg.HTTPAddr)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("want error containing %q, got %v", test.wantErr, err)
			}
		})
	}
}

func TestAllowedHostsAreNormalised(t *testing.T) {
	cfg, err := Load(env(map[string]string{
		"EDIFY_ENV":              "staging",
		"EDIFY_DATABASE_URL":     "postgresql://staging-db.internal/edify",
		"EDIFY_JWT_SECRET":       strongSecret,
		"EDIFY_DB_ALLOWED_HOSTS": " Staging-DB.internal , ,other.internal",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(cfg.DBAllowedHosts, "|"); got != "staging-db.internal|other.internal" {
		t.Fatalf("got %q", got)
	}
}

func TestCORSOrigins(t *testing.T) {
	base := map[string]string{
		"EDIFY_ENV":              "development",
		"EDIFY_DATABASE_URL":     "postgresql://localhost/edify_dev",
		"EDIFY_JWT_SECRET":       strongSecret,
		"EDIFY_DB_ALLOWED_HOSTS": "staging-db.internal",
	}
	tests := []struct {
		name, env, origins, wantErr string
	}{
		{name: "none by default", env: "development"},
		{name: "local web build in development", env: "development", origins: "http://localhost:8082"},
		{name: "wildcard is refused", env: "development", origins: "*", wantErr: "wildcard"},
		{name: "wildcard host is refused", env: "development", origins: "https://*.example.org", wantErr: "wildcard"},
		{name: "not an origin", env: "development", origins: "localhost:8082", wantErr: "must be origins"},
		{name: "staging refuses http", env: "staging", origins: "http://app.staging.example.org", wantErr: "https in staging"},
		{name: "staging accepts https", env: "staging", origins: "https://app.staging.example.org"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			values := map[string]string{"EDIFY_ENV": test.env, "EDIFY_CORS_ALLOWED_ORIGINS": test.origins}
			for key, value := range base {
				if _, set := values[key]; !set {
					values[key] = value
				}
			}
			_, err := Load(env(values))
			if test.wantErr == "" && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if test.wantErr != "" && (err == nil || !strings.Contains(err.Error(), test.wantErr)) {
				t.Fatalf("want error containing %q, got %v", test.wantErr, err)
			}
		})
	}
}

func TestExistingAppURL(t *testing.T) {
	tests := []struct {
		name, env, value, wantErr string
	}{
		{name: "not configured", env: "development"},
		{name: "local in development", env: "development", value: "http://localhost:8010/"},
		{name: "production site", env: "development", value: "https://edifyplanning.app", wantErr: "production site"},
		{name: "production subdomain", env: "staging", value: "https://www.edifyplanning.app", wantErr: "production site"},
		{name: "remote host in development", env: "development", value: "https://app.example.org", wantErr: "on this machine"},
		{name: "staging over http", env: "staging", value: "http://app.staging.example.org", wantErr: "https staging host"},
		{name: "staging over https", env: "staging", value: "https://app.staging.example.org"},
		{name: "with a path", env: "development", value: "http://localhost:8010/api", wantErr: "base URL"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			cfg, err := Load(env(map[string]string{
				"EDIFY_ENV":              test.env,
				"EDIFY_DATABASE_URL":     "postgresql://localhost/edify_dev",
				"EDIFY_JWT_SECRET":       strongSecret,
				"EDIFY_DB_ALLOWED_HOSTS": "staging-db.internal",
				"EDIFY_EXISTING_APP_URL": test.value,
			}))
			if test.wantErr == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				if strings.HasSuffix(cfg.ExistingAppURL, "/") {
					t.Fatalf("trailing slash kept: %q", cfg.ExistingAppURL)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("want error containing %q, got %v", test.wantErr, err)
			}
		})
	}
}
