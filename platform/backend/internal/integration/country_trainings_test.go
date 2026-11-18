//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
)

// The country through trainings (docs/migration/80-multi-country-phase-0.md
// §22). With Kenya Active and an Impact Assessment officer and a CCEO who
// work in Kenya alone, the training summary's officers are the country's:
// Kenya's offers only the Programme Lead of Kenya's CCEO, and Uganda's
// offers the Leads of Uganda's officers. Every row the test files starts
// "gctr".
func TestTheCountryThroughTrainings(t *testing.T) {
	ctx := context.Background()
	assessor, officer, _ := twoKenyans(t, "gctr")
	var kenyanLead, otherLead, ugandaIA string
	if err := admin.QueryRow(ctx, `SELECT
  COALESCE((SELECT u.name FROM staff_supervisor_assignment l JOIN staff_profile sp ON sp.id = l.supervisor_id JOIN "user" u ON u.id = sp.user_id
    WHERE l.supervisee_id = $1 ORDER BY l.id LIMIT 1), ''),
  COALESCE((SELECT u.name FROM staff_supervisor_assignment l JOIN staff_profile sp ON sp.id = l.supervisor_id JOIN "user" u ON u.id = sp.user_id
    WHERE l.supervisee_id <> $1 AND u.is_active AND u.name <> COALESCE((SELECT u2.name FROM staff_supervisor_assignment l2
      JOIN staff_profile sp2 ON sp2.id = l2.supervisor_id JOIN "user" u2 ON u2.id = sp2.user_id WHERE l2.supervisee_id = $1 LIMIT 1), '')
    ORDER BY u.name LIMIT 1), ''),
  (SELECT id FROM "user" WHERE email = 'ia@edify.org')`, officer.staff).Scan(&kenyanLead, &otherLead, &ugandaIA); err != nil {
		t.Fatalf("the officers' Leads: %v", err)
	}
	if kenyanLead == "" || otherLead == "" {
		t.Fatalf("the test needs the Kenyan officer and another officer each reporting to a Programme Lead (got %q, %q)", kenyanLead, otherLead)
	}
	page := func(user string) string {
		t.Helper()
		got, err := pageOf(token(t, user, "ImpactAssessment", time.Hour), trainingsummary.Path, map[string]string{"view": "trainings", "tab": "staff"})
		if err != nil {
			t.Fatalf("the training summary: %v", err)
		}
		return protojson.Format(got)
	}
	inKenya, inUganda := page(assessor.user), page(ugandaIA)
	if !strings.Contains(inKenya, kenyanLead) || strings.Contains(inKenya, otherLead) {
		t.Errorf("Kenya's training summary does not offer exactly its CCEO's Lead (%q in, %q out)", kenyanLead, otherLead)
	}
	if !strings.Contains(inUganda, otherLead) {
		t.Errorf("Uganda's training summary does not offer Uganda's Leads (%q)", otherLead)
	}
}
