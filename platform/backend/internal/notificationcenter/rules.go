// Package notificationcenter is the notification centre (/notifications):
// the signed-in person's own notifications with their figures, filters and
// pages, and how they are told beyond the bell, as the existing web page
// builds them (apps.frontend.views.staff_views.notifications_page_view and
// pages/notifications/index.html). The existing app's page feed does not
// serve this page, so the Next.js web app is its reader, through
// NotificationCenterService.
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_notification_center_rules`;
// apps/notifications/test_notification_center_rules_export.py fails when
// the two differ.
package notificationcenter

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	// Page opens the notification centre at all.
	Page bool `json:"page"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Roles    map[string]Role `json:"roles"`
	Statuses struct {
		Unread, Read, Archived string
	} `json:"statuses"`
	StatusValues     []string `json:"status_values"`
	PriorityValues   []string `json:"priority_values"`
	CriticalPriority string   `json:"critical_priority"`
	DefaultStatus    string   `json:"default_status"`
	PageSize         int      `json:"page_size"`
	EmailProvider    string   `json:"email_provider"`
	EmailProviderEnv string   `json:"email_provider_env"`
	EmailKeyEnv      string   `json:"email_key_env"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Roles) == 0 || r.Statuses.Unread == "" ||
		r.Statuses.Read == "" || r.Statuses.Archived == "" || r.CriticalPriority == "" ||
		r.DefaultStatus == "" || r.PageSize <= 0 || r.EmailProvider == "" || r.EmailProviderEnv == "" ||
		r.EmailKeyEnv == "" {
		panic(fmt.Sprintf("notificationcenter: the embedded rules are unreadable: %v", err))
	}
	return r
}

// EmailConfigured is the existing mailer's is_configured, read from the
// same environment: email goes out only when its provider is chosen and the
// provider's key is present. The key's value is never read beyond that.
func EmailConfigured(getenv func(string) string) bool {
	if getenv == nil {
		getenv = os.Getenv
	}
	return getenv(rules.EmailProviderEnv) == rules.EmailProvider && getenv(rules.EmailKeyEnv) != ""
}
