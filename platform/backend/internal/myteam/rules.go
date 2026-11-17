// Package myteam is the Programme Lead's My Team page (/my-team), as the
// existing page draws it (apps.frontend.views.staff_views.my_team_view,
// apps.hr.team_roster and pages/my_team/index.html) and the app's feed reads
// it: the tiles, what needs the lead's action, and one row per officer the
// lead line-manages with their delivery, targets, SSA coverage, what waits
// on the lead, review, coaching, leave, overdue policies and risk.
//
// It reads; it never writes (owner, 2026-11-14). The existing page rebuilds
// an officer's target ledger when it is marked stale; the target engine works
// that rebuild out in memory and the existing page stays the ledger's only
// writer. What the engine cannot read (targets.ErrHandOn) passes the reader
// on to the existing page.
//
// The doors, statuses and words are exported to rules.json by `manage.py
// export_my_team_rules`; apps/hr/test_my_team_rules_export.py fails when the
// two differ.
package myteam

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"time"

	_ "time/tzdata" // the page's day is Nairobi's wherever the gateway runs
)

// Path is the page Go answers.
const Path = "/my-team"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles            []string            `json:"page_roles"`
	VerifiedStatuses     []string            `json:"verified_statuses"`
	NotInPlanStatuses    []string            `json:"not_in_plan_statuses"`
	AwaitingPLStatus     string              `json:"awaiting_pl_status"`
	ManagerStages        []string            `json:"manager_stages"`
	ClosedStages         []string            `json:"closed_stages"`
	ClosedReviewStatuses []string            `json:"closed_review_statuses"`
	ReviewStages         map[string]string   `json:"review_stages"`
	HighRiskBands        []string            `json:"high_risk_bands"`
	RiskWords            map[string][]string `json:"risk_words"`
	PDSupervisorStatus   string              `json:"pd_supervisor_status"`
	EscalationResolved   string              `json:"escalation_resolved"`
	ReadableDocuments    []string            `json:"readable_document_statuses"`
	PendingAck           string              `json:"pending_acknowledgement"`
	LeaveDecisionDays    int                 `json:"leave_decision_days"`
	ReviewOverdueDays    int                 `json:"review_overdue_days"`
	CoachingKinds        map[string]string   `json:"coaching_kinds"`
	OperatingStatuses    []string            `json:"operating_statuses"`
	TileLabels           map[string]string   `json:"tile_labels"`
	PageSize             int                 `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.VerifiedStatuses) == 0 ||
		len(r.ReviewStages) == 0 || len(r.TileLabels) != 6 || r.PageSize == 0 || len(r.OperatingStatuses) == 0 {
		panic(fmt.Sprintf("myteam: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// zone is settings.TIME_ZONE: timezone.localdate() and a created_at's __date.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("myteam: " + err.Error())
	}
	return z
}()

const (
	roleAdmin = "Admin"
	rolePL    = "Program Lead"
	roleCCEO  = "CCEO"
)

func labelOf(labels map[string]string, value string) string {
	if l, ok := labels[value]; ok {
		return l
	}
	return value
}

func plural(n int, word string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, word)
	}
	return fmt.Sprintf("%d %ss", n, word)
}

// dayLabel is _day: "5 Nov".
func dayLabel(d time.Time) string { return fmt.Sprintf("%d %s", d.Day(), d.Format("Jan")) }
