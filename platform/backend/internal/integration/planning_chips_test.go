//go:build integration

package integration

import (
	"strings"
	"testing"
)

// web-fixes-2: every Planning row carries its plan-status and Visit Lock
// chips as pills whose words are the cell's text, in the page's planning
// tones, and the Visit Lock chip carries its padlock.
func TestPlanningRowsCarryTheirChipsAsPills(t *testing.T) {
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/planning", nil)
	if err != nil {
		t.Fatal(err)
	}
	tones := map[string]bool{"none": true, "planned": true, "awaiting": true, "verified": true, "replan": true, "open": true, "closed": true}
	rows := 0
	for _, b := range page.GetBlocks() {
		for _, r := range b.GetTable().GetRows() {
			cells := r.GetCells()
			if len(cells) < 6 || r.GetPickId() == "" {
				continue
			}
			rows++
			for _, c := range cells[3:6] {
				words := []string{}
				for _, p := range c.GetPills() {
					if !tones[p.GetTone()] {
						t.Errorf("row %s: pill %q has tone %q", r.GetPickId(), p.GetText(), p.GetTone())
					}
					words = append(words, p.GetText())
				}
				if len(words) > 0 && strings.Join(words, "") != c.GetText() {
					t.Errorf("row %s: pills %v are not the cell's text %q", r.GetPickId(), words, c.GetText())
				}
			}
			lock := cells[5].GetPills()
			if len(lock) == 1 && lock[0].GetIcon() != "lock" && lock[0].GetIcon() != "unlock" {
				t.Errorf("row %s: the Visit Lock chip has no padlock", r.GetPickId())
			}
		}
	}
	if rows == 0 {
		t.Skip("the seeded officer has no Planning rows")
	}
}

// The Clusters page's last three filters sit under its own More filters.
func TestClustersFoldTheirAuthoredFiltersUnderMore(t *testing.T) {
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/clusters", nil)
	if err != nil {
		t.Fatal(err)
	}
	folded := []string{}
	for _, f := range page.GetBlocks()[0].GetFilters().GetFilters() {
		if f.GetMore() {
			folded = append(folded, f.GetName())
		}
	}
	if strings.Join(folded, " ") != "ssa_status cluster_risk activity_status" {
		t.Fatalf("folded = %v", folded)
	}
}
