// Package iapages is the Impact Assessment review pages
// (apps.frontend.views.ia_views) as the app's feed reads them, starting with
// Duplicate Review (/ia/duplicates/). Their decisions (ignore, return, flag)
// stay with the existing application.
//
// The doors, the verification permission and the activity labels
// are exported to rules.json by `manage.py export_ia_pages_rules`;
// apps/activities/test_ia_pages_rules_export.py fails when the two differ.
package iapages

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on one page (the IA pages draw no workspace
// strip).
type Role struct {
	Page bool `json:"page"`
}

var rules = func() (r struct {
	Pages map[string]struct {
		Roles map[string]Role `json:"roles"`
	} `json:"pages"`
	IAVerifyRoles []string          `json:"ia_verify_roles"`
	ActivityTypes map[string]string `json:"activity_types"`
	// SchoolProfileRoles may open a school's profile.
	SchoolProfileRoles []string `json:"school_profile_roles"`
	// QueryKeysNotPassed are the query keys the feed never passes to a page.
	QueryKeysNotPassed []string `json:"query_keys_not_passed"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Pages) == 0 || len(r.IAVerifyRoles) == 0 || len(r.ActivityTypes) == 0 {
		panic(fmt.Sprintf("iapages: the embedded rules are unreadable: %v", err))
	}
	return r
}()
