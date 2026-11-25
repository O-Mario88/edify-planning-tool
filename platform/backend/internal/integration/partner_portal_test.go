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

// TestThePartnerPortalListsMatchTheExistingPages files the work and
// assignments internal/partnerassigned/testdata/portal_golden.py filed for
// the partner login's organisation, asks Assigned Schools, the Activity Log
// and Assigned Activities as each reader the golden asked, with each status
// and page, and compares the whole page. Skipped unless
// EDIFY_PARTNER_PORTAL_GOLDEN names that file, written within the hour.
func TestThePartnerPortalListsMatchTheExistingPages(t *testing.T) {
	path := os.Getenv("EDIFY_PARTNER_PORTAL_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PARTNER_PORTAL_GOLDEN is not set")
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
	// The order portal_golden.py files them in (its TABLES); cleared in reverse.
	tables := []string{"activity", "partner_assignment"}
	ctx := context.Background()
	clear := func() {
		for _, table := range slices.Backward(tables) {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'gpta%'`); err != nil {
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
	for _, page := range []string{"/partner/schools", "/partner/activities", "/partner/assignments"} {
		if len(byPath[page]) == 0 {
			t.Fatalf("the golden does not ask %s", page)
		}
		compareGolden(t, page, byPath[page])
	}
}

// A partner login's My Plan is drawn by Go: its Needs Attention section
// always shows, and the organisation's login, who sees its money, has the
// Send Invoice button.
func TestAPartnersMyPlanIsGos(t *testing.T) {
	borrowAccount(t, "partner@edify.org")
	token := sessionOf(t, "partner@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/my-plan", nil)
	if err != nil {
		t.Fatalf("the partner's My Plan: %v", err)
	}
	if got := page.GetHeader().GetTitle(); got != "My Plan" {
		t.Fatalf("title = %q", got)
	}
	if actions := page.GetHeader().GetActions(); len(actions) != 1 || actions[0].GetLabel() != "Send Invoice" {
		t.Fatalf("header actions = %v", actions)
	}
	if got := page.GetBlocks()[0].GetPanel().GetTitle(); got == "" || got[:15] != "Needs Attention" {
		t.Fatalf("first section = %q", got)
	}
}
