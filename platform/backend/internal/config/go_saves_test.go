package config

import (
	"errors"
	"strings"
	"testing"
)

func TestGoSavesAreOffUnlessNamedAndOnlyInDevelopmentOrStaging(t *testing.T) {
	const key = "0123456789abcdef0123456789abcdef"
	tests := []struct {
		name, env, saves, app, key string
		want, wantMove, wantCancel bool
		wantErr                    string
	}{
		{name: "off by default", env: "development", app: "http://localhost:8010", key: key},
		{name: "off by default in test", env: "test"},
		{name: "on in development", env: "development", saves: "schedule_visit", app: "http://localhost:8010", key: key, want: true},
		{name: "refused in test", env: "test", saves: "schedule_visit", app: "http://localhost:8010", key: key, wantErr: "refused in test"},
		{name: "an unknown save", env: "development", saves: "schedule_visit,pay_everyone", app: "http://localhost:8010", key: key, wantErr: `"pay_everyone"`},
		{name: "without the existing application", env: "development", saves: "schedule_visit", key: key, wantErr: "EDIFY_EXISTING_APP_URL"},
		{name: "without the internal key", env: "development", saves: "schedule_visit", app: "http://localhost:8010", wantErr: "EDIFY_INTERNAL_KEY"},
		{name: "the move alone", env: "development", saves: "reschedule_visit", app: "http://localhost:8010", key: key, wantMove: true},
		{name: "both saves", env: "development", saves: "schedule_visit, reschedule_visit", app: "http://localhost:8010", key: key, want: true, wantMove: true},
		{name: "the move refused in test", env: "test", saves: "reschedule_visit", app: "http://localhost:8010", key: key, wantErr: "refused in test"},
		{name: "the move without the internal key", env: "development", saves: "reschedule_visit", app: "http://localhost:8010", wantErr: "EDIFY_INTERNAL_KEY"},
		{name: "the cancel alone", env: "development", saves: "cancel_visit", app: "http://localhost:8010", key: key, wantCancel: true},
		{name: "all three saves", env: "development", saves: "schedule_visit,reschedule_visit,cancel_visit", app: "http://localhost:8010", key: key, want: true, wantMove: true, wantCancel: true},
		{name: "the cancel refused in test", env: "test", saves: "cancel_visit", app: "http://localhost:8010", key: key, wantErr: "refused in test"},
		{name: "the cancel without the existing application", env: "development", saves: "cancel_visit", key: key, wantErr: "EDIFY_EXISTING_APP_URL"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			cfg, err := Load(env(map[string]string{
				"EDIFY_ENV":              test.env,
				"EDIFY_DATABASE_URL":     "postgresql://localhost/edify_dev",
				"EDIFY_JWT_SECRET":       strongSecret,
				"EDIFY_EXISTING_APP_URL": test.app,
				"EDIFY_INTERNAL_KEY":     test.key,
				"EDIFY_GO_SAVES":         test.saves,
			}))
			if test.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), test.wantErr) {
					t.Fatalf("want an error containing %q, got %v", test.wantErr, err)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if cfg.GoSaves.ScheduleVisit != test.want || cfg.GoSaves.RescheduleVisit != test.wantMove ||
				cfg.GoSaves.CancelVisit != test.wantCancel {
				t.Fatalf("GoSaves = %+v, want schedule %v, move %v, cancel %v", cfg.GoSaves, test.want, test.wantMove, test.wantCancel)
			}
		})
	}
}

func TestGoSavesNeverLoadInProduction(t *testing.T) {
	_, err := Load(env(map[string]string{
		"EDIFY_ENV":          "production",
		"EDIFY_DATABASE_URL": "postgresql://localhost/edify",
		"EDIFY_JWT_SECRET":   strongSecret,
		"EDIFY_GO_SAVES":     "schedule_visit",
	}))
	if !errors.Is(err, ErrProductionNotApproved) {
		t.Fatalf("want ErrProductionNotApproved, got %v", err)
	}
	if _, err := loadGoSaves(Production, env(map[string]string{"EDIFY_GO_SAVES": "schedule_visit"}),
		"http://localhost:8010", "0123456789abcdef0123456789abcdef"); err == nil {
		t.Fatal("the switch must be refused in production even past Load")
	}
}
