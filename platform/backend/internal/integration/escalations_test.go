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

// escalationsGoldenEnv names a file of the existing feed's answers for
// Escalations over many escalations (docs/migration/19-escalations.md says
// how it is made). Without it the comparison is skipped.
const escalationsGoldenEnv = "EDIFY_ESCALATIONS_GOLDEN"

// escalationRow is one leadership_escalation row a test files, removed when
// the test ends.
type escalationRow struct {
	ID                string  `json:"id"`
	CreatedAt         string  `json:"created_at"`
	RaisedBy          string  `json:"raised_by_user_id"`
	RaisedByName      *string `json:"raised_by_name"`
	AddressedRole     string  `json:"addressed_role"`
	AssignedTo        *string `json:"assigned_to_user_id"`
	Country           string  `json:"country_id"`
	Category          string  `json:"category"`
	Subject           string  `json:"subject"`
	Detail            string  `json:"detail"`
	RequestedDecision *string `json:"requested_decision"`
	Severity          string  `json:"severity"`
	DueDate           *string `json:"due_date"`
	Status            string  `json:"status"`
	AcknowledgedAt    *string `json:"acknowledged_at"`
	Decision          *string `json:"decision"`
	DecisionNote      *string `json:"decision_note"`
	ResolvedAt        *string `json:"resolved_at"`
}

func fileEscalations(t *testing.T, rows []escalationRow) {
	t.Helper()
	ctx := context.Background()
	var already int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM leadership_escalation`).Scan(&already); err != nil {
		t.Fatal(err)
	}
	if already != 0 {
		t.Skipf("the test database already holds %d escalations", already)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM leadership_escalation WHERE id LIKE 'gpe%'`); err != nil {
			t.Errorf("removing the test's escalations: %v", err)
		}
	})
	for _, r := range rows {
		if _, err := admin.Exec(ctx, `
INSERT INTO leadership_escalation (id, created_at, updated_at, raised_by_user_id, raised_by_name, addressed_role,
  assigned_to_user_id, country_id, category, subject, detail, requested_decision, severity, due_date, status,
  acknowledged_at, decision, decision_note, resolved_at)
VALUES ($1, $2::timestamptz, $2::timestamptz, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::date, $14,
  $15::timestamptz, $16, $17, $18::timestamptz)`,
			r.ID, r.CreatedAt, r.RaisedBy, r.RaisedByName, r.AddressedRole, r.AssignedTo, r.Country, r.Category, r.Subject,
			r.Detail, r.RequestedDecision, r.Severity, r.DueDate, r.Status, r.AcknowledgedAt, r.Decision, r.DecisionNote,
			r.ResolvedAt); err != nil {
			t.Fatalf("filing escalation %s: %v", r.ID, err)
		}
	}
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestAnOfficersEscalationReachesTheirProgrammeLead(t *testing.T) {
	cceo, pl1, pl2 := userIDOf(t, "cceo@edify.org"), userIDOf(t, "pl1@edify.org"), userIDOf(t, "pl2@edify.org")
	at := func(daysAgo int) string {
		return time.Now().Add(-time.Duration(daysAgo)*24*time.Hour - time.Hour).Format(time.RFC3339)
	}
	name := "Officer"
	fileEscalations(t, []escalationRow{
		{ID: "gpe900001", CreatedAt: at(8), RaisedBy: cceo, RaisedByName: &name, AddressedRole: "PL", AssignedTo: &pl1, Country: "Uganda",
			Category: "staffing", Subject: "[Go parity check] cover", Detail: "No one covers Gulu.", Severity: "normal", Status: "open"},
		{ID: "gpe900002", CreatedAt: at(1), RaisedBy: cceo, RaisedByName: &name, AddressedRole: "PL", AssignedTo: &pl2, Country: "Uganda",
			Category: "other", Subject: "[Go parity check] elsewhere", Detail: "x", Severity: "high", Status: "open"},
	})

	borrowAccount(t, "pl1@edify.org")
	page, err := pageOf(sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken(), "/escalations", nil)
	if err != nil {
		t.Fatal(err)
	}
	if page.GetBlocks()[1].GetPanel().GetTitle() != "Awaiting your decision" {
		t.Fatalf("the second block: %v", page.GetBlocks()[1])
	}
	table := page.GetBlocks()[2].GetTable()
	if table == nil || len(table.GetRows()) != 1 {
		t.Fatalf("pl1's inbox: %v", table)
	}
	cells := table.GetRows()[0].GetCells()
	if cells[1].GetText() != "[Go parity check] cover" || cells[5].GetText() != "8d" || cells[6].GetText() != "Overdue" {
		t.Fatalf("the escalation named to pl1: %v", cells)
	}

	borrowAccount(t, "cceo@edify.org")
	mine, err := pageOf(sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken(), "/escalations", map[string]string{"subject": "  From a drill-down "})
	if err != nil {
		t.Fatal(err)
	}
	form := mine.GetBlocks()[0].GetForm()
	if form.GetKey() != "raise" || form.GetItems()[2].GetField().GetValue() != "From a drill-down" {
		t.Fatalf("the raise form: %v", form)
	}
	if raised := mine.GetBlocks()[2].GetTable(); raised == nil || len(raised.GetRows()) != 2 {
		t.Fatalf("raised by the officer: %v", mine.GetBlocks())
	}
}

func TestEscalationsTurnAwayARoleOutsideTheChannel(t *testing.T) {
	borrowAccount(t, "business-transformation@edify.org")
	token := sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/escalations", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Business Transformation Officer opening Escalations: %v, want not found", err)
	}
}

// With the existing feed's answers on file, Go's are compared with them
// field by field, over the same escalations.
func TestEscalationsMatchTheExistingFeedOverManyEscalations(t *testing.T) {
	path := os.Getenv(escalationsGoldenEnv)
	if path == "" {
		t.Skipf("%s is not set", escalationsGoldenEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Now     time.Time       `json:"now"`
		Rows    []escalationRow `json:"rows"`
		Answers []goldenAnswer  `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Now)
	fileEscalations(t, golden.Rows)
	compareGolden(t, "/escalations", golden.Answers)
}
