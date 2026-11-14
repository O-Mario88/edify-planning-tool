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
		wantEdit, wantPair         bool
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
		{name: "the edit alone", env: "development", saves: "edit_visit", app: "http://localhost:8010", key: key, wantEdit: true},
		{name: "all four saves", env: "development", saves: "schedule_visit,reschedule_visit,cancel_visit,edit_visit", app: "http://localhost:8010", key: key, want: true, wantMove: true, wantCancel: true, wantEdit: true},
		{name: "the edit refused in test", env: "test", saves: "edit_visit", app: "http://localhost:8010", key: key, wantErr: "refused in test"},
		{name: "the edit without the internal key", env: "development", saves: "edit_visit", app: "http://localhost:8010", wantErr: "EDIFY_INTERNAL_KEY"},
		{name: "the training pair alone", env: "development", saves: "schedule_training_pair", app: "http://localhost:8010", key: key, wantPair: true},
		{name: "the training pair beside the visit", env: "development", saves: "schedule_visit,schedule_training_pair", app: "http://localhost:8010", key: key, want: true, wantPair: true},
		{name: "the training pair refused in test", env: "test", saves: "schedule_training_pair", app: "http://localhost:8010", key: key, wantErr: "refused in test"},
		{name: "the training pair without the existing application", env: "development", saves: "schedule_training_pair", key: key, wantErr: "EDIFY_EXISTING_APP_URL"},
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
				cfg.GoSaves.CancelVisit != test.wantCancel || cfg.GoSaves.EditVisit != test.wantEdit ||
				cfg.GoSaves.ScheduleTrainingPair != test.wantPair {
				t.Fatalf("GoSaves = %+v, want schedule %v, move %v, cancel %v, edit %v", cfg.GoSaves, test.want, test.wantMove,
					test.wantCancel, test.wantEdit)
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

// The group saves (docs/migration/33): each off unless named, each switch
// its own, refused outside development and staging, and needing the
// existing application as every Go save does.
func TestTheGroupSavesAreOffUnlessNamed(t *testing.T) {
	const key = "0123456789abcdef0123456789abcdef"
	app := "http://localhost:8010"
	for _, c := range []struct {
		env, saves, app string
		move, cancel    bool
		wantErr         string
	}{
		{env: "development", app: app},
		{env: "development", saves: "group_reschedule", app: app, move: true},
		{env: "development", saves: "group_cancel", app: app, cancel: true},
		{env: "staging", saves: "group_reschedule,group_cancel", app: app, move: true, cancel: true},
		{env: "test", saves: "group_cancel", app: app, wantErr: "refused in test"},
		{env: "development", saves: "group_reschedule", wantErr: "EDIFY_EXISTING_APP_URL"},
	} {
		saves, err := loadGoSaves(Environment(c.env), env(map[string]string{"EDIFY_GO_SAVES": c.saves}), c.app, key)
		if c.wantErr != "" {
			if err == nil || !strings.Contains(err.Error(), c.wantErr) {
				t.Errorf("%s %q: want %q, got %v", c.env, c.saves, c.wantErr, err)
			}
			continue
		}
		if err != nil || saves.GroupReschedule != c.move || saves.GroupCancel != c.cancel ||
			saves.RescheduleVisit || saves.CancelVisit {
			t.Errorf("%s %q: %+v, %v", c.env, c.saves, saves, err)
		}
	}
}

// A cluster's Group Training (docs/migration/38): off unless named, its
// switch its own, refused outside development and staging.
func TestTheGroupTrainingSaveIsOffUnlessNamed(t *testing.T) {
	const key = "0123456789abcdef0123456789abcdef"
	app := "http://localhost:8010"
	for _, c := range []struct {
		env, saves, app string
		on              bool
		wantErr         string
	}{
		{env: "development", app: app},
		{env: "development", saves: "schedule_training_pair", app: app},
		{env: "development", saves: "schedule_group_training", app: app, on: true},
		{env: "staging", saves: "schedule_visit,schedule_group_training", app: app, on: true},
		{env: "test", saves: "schedule_group_training", app: app, wantErr: "refused in test"},
		{env: "production", saves: "schedule_group_training", app: app, wantErr: "refused in production"},
		{env: "development", saves: "schedule_group_training", wantErr: "EDIFY_EXISTING_APP_URL"},
	} {
		saves, err := loadGoSaves(Environment(c.env), env(map[string]string{"EDIFY_GO_SAVES": c.saves}), c.app, key)
		if c.wantErr != "" {
			if err == nil || !strings.Contains(err.Error(), c.wantErr) {
				t.Errorf("%s %q: want %q, got %v", c.env, c.saves, c.wantErr, err)
			}
			continue
		}
		if err != nil || saves.ScheduleGroupTraining != c.on ||
			saves.ScheduleTrainingPair != strings.Contains(c.saves, "schedule_training_pair") {
			t.Errorf("%s %q: %+v, %v", c.env, c.saves, saves, err)
		}
	}
}

// A cluster meeting (docs/migration/49): off unless named, its switch its
// own (not the Group Training's), refused outside development and staging.
func TestTheClusterMeetingSaveIsOffUnlessNamed(t *testing.T) {
	const key = "0123456789abcdef0123456789abcdef"
	app := "http://localhost:8010"
	for _, c := range []struct {
		env, saves, app string
		on              bool
		wantErr         string
	}{
		{env: "development", app: app},
		{env: "development", saves: "schedule_group_training", app: app},
		{env: "development", saves: "schedule_cluster_meeting", app: app, on: true},
		{env: "staging", saves: "schedule_group_training,schedule_cluster_meeting", app: app, on: true},
		{env: "test", saves: "schedule_cluster_meeting", app: app, wantErr: "refused in test"},
		{env: "production", saves: "schedule_cluster_meeting", app: app, wantErr: "refused in production"},
		{env: "development", saves: "schedule_cluster_meeting", wantErr: "EDIFY_EXISTING_APP_URL"},
	} {
		saves, err := loadGoSaves(Environment(c.env), env(map[string]string{"EDIFY_GO_SAVES": c.saves}), c.app, key)
		if c.wantErr != "" {
			if err == nil || !strings.Contains(err.Error(), c.wantErr) {
				t.Errorf("%s %q: want %q, got %v", c.env, c.saves, c.wantErr, err)
			}
			continue
		}
		if err != nil || saves.ScheduleClusterMeeting != c.on ||
			saves.ScheduleGroupTraining != strings.Contains(c.saves, "schedule_group_training") {
			t.Errorf("%s %q: %+v, %v", c.env, c.saves, saves, err)
		}
	}
}
