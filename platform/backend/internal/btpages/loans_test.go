package btpages

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btportfolio"
)

func TestTheSalesforceCoverageIsWrittenAsPythonWritesIt(t *testing.T) {
	cases := []struct {
		confirmed, loans int
		want             string
	}{{0, 2, "0"}, {1, 2, "50.0"}, {1, 3, "33.3"}, {2, 2, "100.0"}, {0, 0, "0"}}
	for _, c := range cases {
		if got := coverage(c.confirmed, c.loans); got != c.want {
			t.Errorf("coverage(%d, %d) = %q, want %q", c.confirmed, c.loans, got, c.want)
		}
	}
}

func TestTheExportCarriesTheSetFiltersButThePagers(t *testing.T) {
	got := loanFilterQuery(btportfolio.Filters{"page": "2", "status": "active", "fy": "2027", "q": "St Mary's & co"})
	if got != "fy=2027&q=St+Mary%27s+%26+co&status=active" {
		t.Errorf("filter query: %q", got)
	}
}

func TestALoanRowReadsAsTheRegisterDrawsIt(t *testing.T) {
	paid, out, approved := "1500000.00", "37000000.00", "40000000.00"
	cells, err := loanCells(loanRow{ref: "LN-1", officer: "LO-7", code: "1001", school: "Goma", district: "Mukono", region: "Central Region",
		mfi: "Demo", purpose: "Lab", edtech: true, approved: &approved, paid: &paid, outstanding: &out,
		status: "disbursed", health: "overdue_31_90", salesforce: "pending", ia: "returned", impact: "not_due"}, true)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"LN-1Officer LO-7", "1001", "GomaMukono · Central Region", "Demo", "Lab EdTech", "Not disbursedApproved UGX 40,000,000",
		"Disbursed", "Overdue 31–90 Paid UGX 1,500,000 · Outstanding UGX 37,000,000", "Pending", "Returned"}
	for i, w := range want {
		if cells[i].Text != w {
			t.Errorf("cell %d = %q, want %q", i, cells[i].Text, w)
		}
	}
	if cells[7].Badge || !cells[8].Badge || cells[12].Text != "Complete" || cells[2].Href != "/schools/1001" {
		t.Errorf("badges, action or link: %v %v %q %q", cells[7].Badge, cells[8].Badge, cells[12].Text, cells[2].Href)
	}
	cells, _ = loanCells(loanRow{code: "9", salesforce: "confirmed", status: "active"}, true)
	if cells[2].Text != "District not set" || cells[8].Text != "Confirmed" || !cells[8].Badge || cells[12].Text != "View" {
		t.Errorf("bare loan: %q %q %q", cells[2].Text, cells[8].Text, cells[12].Text)
	}
}
