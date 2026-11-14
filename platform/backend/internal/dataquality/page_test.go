package dataquality

import "testing"

func TestAnIssueRowReadsAsTheQueueWritesIt(t *testing.T) {
	c := issueRow(issue{schoolPK: "s1", code: "1699", school: "Hill  Primary", field: "school_phone", value: "070", fix: "Add school phone number"}, true).Cells
	if c[0].Text != "1699" || c[1].Text != "Hill Primary school_phone: 070" || c[1].Href != "/schools/s1" || c[2].Text != "Add school phone number" ||
		c[3].Text != "Unassigned" || c[4].Text != "Assign to me Resolve" {
		t.Errorf("row: %v", c)
	}
	bare := issueRow(issue{school: "X", assigned: true}, false).Cells
	if bare[0].Text != "—" || bare[1].Href != "" || bare[2].Text != "—" || bare[3].Text != "Assigned" {
		t.Errorf("bare row: %v", bare)
	}
}
