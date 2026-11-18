//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/settingspage"
)

type settingsAnswer struct {
	UserID     string            `json:"user_id"`
	ActiveRole string            `json:"active_role"`
	Env        map[string]string `json:"env"`
	Policy     struct {
		ForAll bool     `json:"for_all"`
		Roles  []string `json:"roles"`
	} `json:"policy"`
	Answer map[string]any `json:"answer"`
}

// TestTheSettingsPageMatchesTheExistingPage files the accounts
// internal/settingspage/testdata/golden.py made, and reads each as Go does,
// through the gateway's own role, under each SMS and two-step policy
// setting, against what the existing view put in front of them. Skipped
// unless EDIFY_SETTINGS_GOLDEN names that file.
func TestTheSettingsPageMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_SETTINGS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_SETTINGS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []settingsAnswer             `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM "user" WHERE id LIKE 'gset%'`); err != nil {
			t.Errorf("clearing the accounts: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows["user"] {
		if _, err := admin.Exec(ctx, `INSERT INTO "user" SELECT * FROM json_populate_record(NULL::"user", $1::json)`, string(row)); err != nil {
			t.Fatalf("filing an account: %v", err)
		}
	}
	compared, differing := 0, 0
	for _, a := range golden.Answers {
		env := a.Env
		service := settingspage.NewService(gateway, settingspage.Policy{RequiredForAll: a.Policy.ForAll, RequiredRoles: a.Policy.Roles},
			func(name string) string { return env[name] })
		principal := auth.Principal{Account: auth.Account{UserID: a.UserID, ActiveRole: a.ActiveRole}}
		got, err := service.Build(ctx, principal)
		switch refused, _ := a.Answer["refused"].(string); refused {
		case "password_owed":
			// The gateway's interceptor refuses every call but the password's
			// own while one is owed (auth.openWhilePasswordOwed), as the
			// existing middleware redirects; the page is never read.
			continue
		case "":
			compared++
		default:
			compared++
			if !errors.Is(err, settingspage.ErrNotAvailable) {
				differing++
				t.Errorf("%s: the existing page refuses (%s); Go answered %v", a.UserID, refused, err)
			}
			continue
		}
		if err != nil {
			t.Fatalf("%s: %v", a.UserID, err)
		}
		two := got.GetTwoStep()
		want := map[string]any{
			"email":                  got.GetEmail(),
			"must_change_password":   got.GetMustChangePassword(),
			"mfa_in_force":           two.GetInForce(),
			"mfa_required_by_policy": two.GetRequiredByPolicy(),
			"mfa_channel":            two.GetChannel(),
			"mfa_app_available":      two.GetAppAvailable(),
			"mfa_sms_available":      two.GetSmsAvailable(),
			"mfa_sms_blocked_reason": two.GetSmsBlockedReason(),
			"mfa_email_hint":         two.GetEmailHint(),
			"mfa_phone_hint":         two.GetPhoneHint(),
			"session_idle_minutes":   float64(got.GetSessionIdleMinutes()),
		}
		for key, value := range want {
			if a.Answer[key] != value {
				differing++
				t.Errorf("%s %v %v: %s is %v in Go, %v on the existing page", a.UserID, a.Env, a.Policy, key, value, a.Answer[key])
			}
		}
	}
	t.Logf("%d answers compared, %d differing", compared, differing)
}
