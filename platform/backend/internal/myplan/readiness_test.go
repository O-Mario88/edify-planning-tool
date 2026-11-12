package myplan

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestVisitTargetReadsAProgrammeLeadBeforeACCEO(t *testing.T) {
	cases := []struct {
		active string
		roles  []string
		want   int
	}{
		{"CCEO", nil, 560},
		{"Program Lead", nil, 280},
		{"Admin", []string{"Admin", "CCEO"}, 560},
		{"CCEO", []string{"CCEO", "Program Lead"}, 280},
		{"Admin", []string{"Admin"}, 0},
	}
	for _, c := range cases {
		p := auth.Principal{Account: auth.Account{ActiveRole: c.active, Roles: c.roles}}
		if got := visitTarget(p); got != c.want {
			t.Errorf("%s %v: %d, want %d", c.active, c.roles, got, c.want)
		}
	}
}

func TestEmptyReadinessLinksTheTargetToItsListsInThePagesQuery(t *testing.T) {
	request := NewQuery(values("fy", " 2026 ", "list", "x", "list_page", "2"))
	table := emptyReadiness(560, " 2026 ", request).GetTable()
	if table.Title != "Planned and remaining · FY 2026" || table.Subtitle != "Readiness 75% · 0 schools held" {
		t.Fatalf("%q / %q", table.Title, table.Subtitle)
	}
	visits := table.Rows[0].Cells
	if visits[2].Href != "?fy=+2026+&list=staff_queue#plan-list" || visits[2].Tone != "" {
		t.Errorf("target %q %q", visits[2].Href, visits[2].Tone)
	}
	if visits[3].Text != "560" || visits[3].Tone != "warning" || visits[3].Href != "?fy=+2026+&list=staff_visits_left#plan-list" {
		t.Errorf("remaining %+v", visits[3])
	}
	want := "Your target is 560 visits a year. You have scheduled visits at 0 of your schools yourself. Your schools take 0 of those 560 visits: recruit 560 more schools to meet your target. No project ceiling is set for you, so no project target is asked of you. Readiness is the average of your visits, schools in training, schools with a Partner and schools added to projects."
	if table.Footnote != want {
		t.Errorf("footnote %q", table.Footnote)
	}
	if len(table.Rows) != 6 || table.Rows[5].Cells[2].Text != "None required" || table.Rows[5].Cells[4].Tone != "neutral" {
		t.Errorf("rows %v", table.Rows)
	}
}

func TestReadinessListReadsAKnownKeyStripped(t *testing.T) {
	for raw, want := range map[string]string{" staff_queue ": "staff_queue", "nope": "", "": "", "no_visit": "no_visit"} {
		if got := readinessList(NewQuery(values("list", raw))); got != want {
			t.Errorf("%q: %q, want %q", raw, got, want)
		}
	}
	table := emptyReadinessList("staff_queue").GetTable()
	if table.Rows[0].Cells[0].Text != "None of your schools: the staff queue: core schools, and schools not in a partner's hands." {
		t.Errorf("%q", table.Rows[0].Cells[0].Text)
	}
}
