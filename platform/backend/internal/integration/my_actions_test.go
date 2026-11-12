//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"connectrpc.com/connect"
)

// myActionsGoldenEnv names a file of the existing feed's answers for My
// Actions over many actions (docs/migration/21-my-actions.md says how it is
// made). Without it the comparison is skipped.
const myActionsGoldenEnv = "EDIFY_MY_ACTIONS_GOLDEN"

// teamActionRow is one team_action row a test files, removed when the test
// ends.
type teamActionRow struct {
	ID               string  `json:"id"`
	CreatedAt        string  `json:"created_at"`
	ConditionKey     string  `json:"condition_key"`
	IssueType        string  `json:"issue_type"`
	SchoolID         string  `json:"school_id"`
	SenderID         string  `json:"sender_id"`
	RecipientID      string  `json:"recipient_id"`
	RequestedAction  string  `json:"requested_action"`
	WorkflowRoute    string  `json:"workflow_route"`
	DueDate          *string `json:"due_date"`
	State            string  `json:"state"`
	ResolvedAt       *string `json:"resolved_at"`
	ResolvedBySystem bool    `json:"resolved_by_system"`
	ReturnedReason   string  `json:"returned_reason"`
}

func fileTeamActions(t *testing.T, rows []teamActionRow) {
	t.Helper()
	ctx := context.Background()
	var already int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM team_action`).Scan(&already); err != nil {
		t.Fatal(err)
	}
	if already != 0 {
		t.Skipf("the test database already holds %d team actions", already)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM team_action WHERE id LIKE 'gpa%'`); err != nil {
			t.Errorf("removing the test's actions: %v", err)
		}
	})
	for _, r := range rows {
		if _, err := admin.Exec(ctx, `
INSERT INTO team_action (id, created_at, updated_at, condition_key, issue_type, severity, school_id, fy, sender_id,
  sender_role, recipient_id, recipient_role, requested_action, workflow_route, message, priority, due_date, state,
  detected_at, blocked_reason, resolved_at, resolved_by_system, manual_resolution_reason, returned_reason, reminder_count)
VALUES ($1, $2::timestamptz, $2::timestamptz, $3, $4, 'critical', $5, '2027', $6, 'Program Lead', $7, 'CCEO', $8, $9, '',
  'urgent', $10::date, $11, $2::timestamptz, '', $12::timestamptz, $13, '', $14, 0)`,
			r.ID, r.CreatedAt, r.ConditionKey, r.IssueType, r.SchoolID, r.SenderID, r.RecipientID, r.RequestedAction,
			r.WorkflowRoute, r.DueDate, r.State, r.ResolvedAt, r.ResolvedBySystem, r.ReturnedReason); err != nil {
			t.Fatalf("filing action %s: %v", r.ID, err)
		}
	}
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestMyActionsListsWhatWasHandedToTheReader(t *testing.T) {
	me, lead := userIDOf(t, "cceo@edify.org"), userIDOf(t, "pl1@edify.org")
	var school, name string
	if err := admin.QueryRow(context.Background(), `SELECT id, name FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1`).Scan(&school, &name); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	day := func(offset int) *string {
		d := now.In(time.FixedZone("EAT", 3*3600)).AddDate(0, 0, offset).Format("2006-01-02")
		return &d
	}
	resolved := now.Format(time.RFC3339)
	fileTeamActions(t, []teamActionRow{
		{ID: "gpa900001", CreatedAt: now.Format(time.RFC3339), ConditionKey: "gpa-t-1", IssueType: "no_visit", SchoolID: school, SenderID: lead,
			RecipientID: me, RequestedAction: "[Go parity check] Visit", WorkflowRoute: "/schools/" + school, DueDate: day(-2), State: "open"},
		{ID: "gpa900002", CreatedAt: now.Format(time.RFC3339), ConditionKey: "gpa-t-2", IssueType: "no_ssa", SchoolID: school, SenderID: lead,
			RecipientID: me, RequestedAction: "[Go parity check] SSA", DueDate: day(3), State: "resolved", ResolvedAt: &resolved, ResolvedBySystem: true},
		{ID: "gpa900003", CreatedAt: now.Format(time.RFC3339), ConditionKey: "gpa-t-3", IssueType: "no_ssa", SchoolID: school, SenderID: me,
			RecipientID: lead, RequestedAction: "[Go parity check] not mine", State: "open"},
	})
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/actions/mine", nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := page.GetBlocks()[0].GetPanel().GetItems()[0].GetText(); got != "1 of 1 resolved action confirmed by the record." {
		t.Fatalf("the provenance line: %q", got)
	}
	links := page.GetBlocks()[1].GetPanel().GetItems()[0].GetLinks().GetLinks()
	if links[0].GetText() != "Open 1" || links[2].GetText() != "Resolved 1" || links[3].GetText() != "All 2" {
		t.Fatalf("the tabs: %v", links)
	}
	table := tableOf(page)
	if table == nil || len(table.GetRows()) != 1 {
		t.Fatalf("the open tab: %v", table)
	}
	cells := table.GetRows()[0].GetCells()
	if cells[2].GetText() != "[Go parity check] Visit No visit" || cells[4].GetText()[len(cells[4].GetText())-11:] != "2 days late" ||
		cells[6].GetActions()[0].GetHref() != "/schools/"+school {
		t.Fatalf("the open action: %v", cells)
	}
	done, err := pageOf(token, "/actions/mine", map[string]string{"tab": "resolved"})
	if err != nil {
		t.Fatal(err)
	}
	if cells := tableOf(done).GetRows()[0].GetCells(); cells[5].GetText() != "Resolved Confirmed by the record" || cells[6].GetActions()[0].GetLabel() != "View school" {
		t.Fatalf("the resolved action: %v", cells)
	}
}

// With the existing feed's answers on file, Go's are compared with them
// field by field, over the same actions.
func TestMyActionsMatchesTheExistingFeedOverManyActions(t *testing.T) {
	path := os.Getenv(myActionsGoldenEnv)
	if path == "" {
		t.Skipf("%s is not set", myActionsGoldenEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Today   string          `json:"today"`
		Rows    []teamActionRow `json:"rows"`
		Answers []goldenAnswer  `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if today := time.Now().In(time.FixedZone("EAT", 3*3600)).Format("2006-01-02"); today != golden.Today {
		t.Skipf("the answers were made on %s; today is %s, so every lateness has moved", golden.Today, today)
	}
	fileTeamActions(t, golden.Rows)
	compareGolden(t, "/actions/mine", golden.Answers)
}

// A partner's team member is refused the pages the Partner Admin keeps, as
// the existing feed refuses them (apps.partners.member_scope.page_withheld);
// the same login with no roster entry opens them.
func TestAPartnersTeamMemberIsRefusedMyActionsAndTheDecisionLog(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "partner@edify.org")
	token := sessionOf(t, "partner@edify.org", seededPassword).GetAccessToken()
	for _, path := range []string{"/actions/mine", "/decision-log"} {
		if _, err := pageOf(token, path, nil); err != nil {
			t.Fatalf("%s with no roster entry: %v", path, err)
		}
	}
	var partner string
	if err := admin.QueryRow(ctx, `SELECT id FROM partner WHERE deleted_at IS NULL AND active_status AND user_id IS NULL ORDER BY id LIMIT 1`).Scan(&partner); err != nil {
		t.Skip("the seed has no partner without a login of its own")
	}
	if _, err := admin.Exec(ctx, `
INSERT INTO partner_member (created_at, updated_at, id, name, role, title, phone, email, active, partner_id, user_id)
VALUES (now(), now(), 'gpm900001', '[Go parity check] member', 'member', '', '', '', true, $1, $2)`, partner, userIDOf(t, "partner@edify.org")); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM partner_member WHERE id = 'gpm900001'`); err != nil {
			t.Errorf("removing the roster entry: %v", err)
		}
	})
	for _, path := range []string{"/actions/mine", "/decision-log"} {
		if _, err := pageOf(token, path, nil); connect.CodeOf(err) != connect.CodeNotFound {
			t.Errorf("%s as a team member: %v, want not found", path, err)
		}
	}
}
