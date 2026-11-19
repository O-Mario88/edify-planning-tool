//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"slices"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

// financeDesksBuilt are the Accounts desks Go builds (internal/financedesks);
// the golden asks every desk.
var financeDesksBuilt = []string{
	"/accounts/accountability", "/accounts/advances", "/accounts/audit-log", "/accounts/blocked", "/accounts/budget-amendments",
	"/accounts/cleared", "/accounts/returned", "/accounts/variance-review", "/accounts/weekly-requests",
}

// TestTheAccountsDesksMatchTheExistingPages files the records
// internal/financedesks/testdata/golden.py filed (an accountability record,
// an audit event, a variance review and an amendment on one completed
// activity, a closed activity, an advance to disburse and a returned one),
// asks each desk Go builds as each reader the golden asked, and compares the
// whole page. Skipped unless EDIFY_FINANCE_DESKS_GOLDEN names that file,
// written within the hour.
func TestTheAccountsDesksMatchTheExistingPages(t *testing.T) {
	path := os.Getenv("EDIFY_FINANCE_DESKS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_FINANCE_DESKS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Answers []struct {
			goldenAnswer
			Path string `json:"path"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	// The order golden.py files them in (its TABLES); cleared in reverse.
	tables := []string{"activity", "activity_schedule_cost_line", "advance_request", "accountability_record",
		"finance_audit_log", "variance_review", "budget_amendment"}
	ctx := context.Background()
	clear := func() {
		for _, table := range slices.Backward(tables) {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'gdesk%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range tables {
		name := pgx.Identifier{table}.Sanitize()
		for _, row := range golden.Tables[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO `+name+` SELECT * FROM json_populate_record(NULL::`+name+`, $1::json)`, string(row)); err != nil {
				t.Fatalf("filing %s: %v", table, err)
			}
		}
	}
	byPath := map[string][]goldenAnswer{}
	for _, a := range golden.Answers {
		byPath[a.Path] = append(byPath[a.Path], a.goldenAnswer)
	}
	for _, desk := range financeDesksBuilt {
		if len(byPath[desk]) == 0 {
			t.Fatalf("the golden does not ask %s", desk)
		}
		compareGolden(t, desk, byPath[desk])
	}
}
