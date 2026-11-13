// Package messaging is the Messages inbox (/messages) for the web app, read
// by Go (docs/migration/42-messages.md): the reader's threads with the same
// tabs, counts, search, sort, rows and pager as the existing page
// (apps.frontend.views.message_views.messages_list_view,
// apps.messaging.services.threads_for_user and can_access_context, and the
// page's templates), and the top bar's unread count (unread_thread_count).
//
// It only reads. Opening a conversation marks it read in the existing
// application; that write is not here.
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_messaging_rules`;
// apps/messaging/test_messaging_rules_export.py fails when the two differ.
package messaging

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
	"time"
)

//go:embed rules.json
var rulesJSON []byte

// RoleRule is what a role may do here, by the page's own gates.
type RoleRule struct {
	Page bool   `json:"page"`
	Slug string `json:"slug"`
}

// Rules are the inbox's vocabularies.
type Rules struct {
	ActivityContexts         []string            `json:"activity_contexts"`
	AllowCDOperational       bool                `json:"allow_cd_operational_planning"`
	ContextLabels            map[string]string   `json:"context_labels"`
	FieldRoles               []string            `json:"field_roles"`
	FinanceContexts          []string            `json:"finance_contexts"`
	FundRequestReaders       []string            `json:"fund_request_readers"`
	IAContexts               []string            `json:"ia_contexts"`
	IAUnresolvedRoles        []string            `json:"ia_unresolved_roles"`
	LeaveReaders             []string            `json:"leave_readers"`
	MessageRules             []string            `json:"message_rules"`
	PageSize                 int                 `json:"page_size"`
	PartnerAssignmentReaders []string            `json:"partner_assignment_readers"`
	PartnerAssignmentScoped  []string            `json:"partner_assignment_scoped"`
	PartnerRoles             []string            `json:"partner_roles"`
	RecipientTo              string              `json:"recipient_to"`
	Roles                    map[string]RoleRule `json:"roles"`
	StageContexts            map[string][]string `json:"stage_contexts"`
	Tabs                     [][2]string         `json:"tabs"`
	TimeZone                 string              `json:"time_zone"`
}

var (
	rules    = mustLoad(rulesJSON)
	pageZone = mustZone(rules.TimeZone)
)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Tabs) == 0 || r.PageSize <= 0 || len(r.Roles) == 0 || len(r.ContextLabels) == 0 {
		panic(fmt.Sprintf("messaging: the embedded rules are unreadable: %v", err))
	}
	return r
}

func mustZone(name string) *time.Location {
	zone, err := time.LoadLocation(name)
	if err != nil {
		panic(fmt.Sprintf("messaging: the page's time zone %q is unreadable: %v", name, err))
	}
	return zone
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

// slug is get_user_role_slug for a person working in role.
func slug(role string) string { return rules.Roles[role].Slug }

// Role slugs the gate names.
const (
	slugAdmin      = "ADMIN"
	slugAccountant = "ACCOUNTANT"
	slugPartner    = "PARTNER"
	slugPL         = "PL"
)

// Active roles can_view_record names.
const (
	roleCountryDirector = "CountryDirector"
	roleRVP             = "RegionalVicePresident"
)
