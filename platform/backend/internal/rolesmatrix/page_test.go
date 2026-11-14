package rolesmatrix

import (
	"net/url"
	"strconv"
	"testing"
)

func TestHumanizeIsTheRBACTokenAsTheMatrixWritesIt(t *testing.T) {
	for token, want := range map[string]string{
		"budgetIntelligence": "Budget Intelligence",
		"resolve_duplicate":  "Resolve duplicate", // only the first letter is capitalised
		"bulkComplete":       "Bulk Complete",
		"ProjectCoordinator": "Project Coordinator",
		"MfiPartnerAdmin":    "Mfi Partner Admin",
		"Program Lead":       "Program Lead",
		"CCEO":               "CCEO",
		"ssa2Score":          "Ssa2 Score",
		"_":                  "_",
	} {
		if got := humanize(token); got != want {
			t.Errorf("humanize(%q) = %q, want %q", token, got, want)
		}
	}
}

func TestTheMatrixReadsAGroupRowThenAnEmptyBadgePerRole(t *testing.T) {
	r := page([]string{"CCEO", "ProjectCoordinator"}, []*group{{prefix: "activity", name: "Activity", labels: []string{"Assign", "Bulk Complete"}}}, url.Values{})
	tb := r.Blocks[0].GetTable()
	if len(tb.Columns) != 3 || tb.Columns[0].Label != "Permission" || tb.Columns[2].Label != "Project Coordinator" {
		t.Fatalf("columns: %v", tb.Columns)
	}
	if len(tb.Rows) != 3 || len(tb.Rows[0].Cells) != 1 || tb.Rows[0].Cells[0].Text != "Activity" {
		t.Fatalf("group row: %v", tb.Rows)
	}
	if c := tb.Rows[1].Cells; c[0].Text != "Assign" || c[1].Text != "" || c[1].Tone != "primary" || !c[1].Badge || len(c) != 3 {
		t.Errorf("permission row: %v", c)
	}
	empty := page([]string{"Admin"}, nil, url.Values{}).Blocks[0].GetTable()
	if len(empty.Rows) != 1 || empty.Rows[0].Cells[0].Text != "No permissions defined." {
		t.Errorf("empty: %v", empty.Rows)
	}
}

func TestTheMatrixPagesItsGroups(t *testing.T) {
	groups := make([]*group, rules.PageSize+1)
	for i := range groups {
		groups[i] = &group{name: "G" + strconv.Itoa(i)}
	}
	r := page(nil, groups, url.Values{pageParam: {"2"}})
	if rows := r.Blocks[0].GetTable().Rows; len(rows) != 1 || rows[0].Cells[0].Text != "G"+strconv.Itoa(rules.PageSize) {
		t.Errorf("second page: %v", rows)
	}
	if len(r.Blocks) != 2 || r.Blocks[1].GetPanel() == nil {
		t.Errorf("pager: %v", r.Blocks)
	}
}
