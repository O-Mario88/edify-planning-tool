// Package settingspage is the Settings page (/settings) for the signed-in
// person: their email, whether they must change their password, their
// two-step verification and how long an idle session lasts, as the existing
// page draws them (apps.frontend.views.extended_views.settings_view,
// pages/settings/index.html and apps.accounts.mfa_service.enrolment_state).
// The Next.js web app is its reader, through SettingsScreenService.
// Changing two-step verification is a save the existing web app still makes.
//
// The rules it is read by are the existing ones, exported to rules.json by
// `manage.py export_settings_page_rules`;
// apps/accounts/test_settings_page_rules_export.py fails when the two differ.
package settingspage

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	// Page opens Settings at all.
	Page bool `json:"page"`
}

// Rules are the page's rules and words.
type Rules struct {
	Roles                     map[string]Role `json:"roles"`
	SessionIdleEnv            string          `json:"session_idle_env"`
	SessionIdleDefaultSeconds int             `json:"session_idle_default_seconds"`
	SMSProvider               string          `json:"sms_provider"`
	SMSProviderEnv            string          `json:"sms_provider_env"`
	SMSRequiredEnvs           []string        `json:"sms_required_envs"`
	Channels                  struct {
		Email string `json:"email"`
		SMS   string `json:"sms"`
		App   string `json:"app"`
	} `json:"channels"`
	SMSNeedsPhone    string `json:"sms_needs_phone"`
	SMSNotConfigured string `json:"sms_not_configured"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Roles) == 0 || r.SessionIdleEnv == "" ||
		r.SessionIdleDefaultSeconds <= 0 || r.SMSProvider == "" || r.SMSProviderEnv == "" ||
		len(r.SMSRequiredEnvs) == 0 || r.Channels.Email == "" || r.Channels.SMS == "" ||
		r.Channels.App == "" || r.SMSNeedsPhone == "" || r.SMSNotConfigured == "" {
		panic(fmt.Sprintf("settingspage: the embedded rules are unreadable: %v", err))
	}
	return r
}
