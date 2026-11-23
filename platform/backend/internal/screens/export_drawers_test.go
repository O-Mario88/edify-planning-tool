package screens

import (
	"net/url"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

var exportToday = time.Date(2026, 11, 23, 9, 0, 0, 0, time.UTC)

func TestExportDrawerPeriod(t *testing.T) {
	tests := []struct {
		name, query, fy string
		want            exportPeriod
	}{
		{"opens on this month", "", "2027", exportPeriod{from: 11, to: 11, mode: "month_range", start: "2026-10-01", end: "2027-09-30"}},
		{"keeps the page's month", "period=month&month=3", "2027", exportPeriod{from: 3, to: 3, mode: "month_range", start: "2026-10-01", end: "2027-09-30"}},
		{"opens a quarter as its months", "period=quarter&quarter=q3", "2027", exportPeriod{from: 4, to: 6, mode: "month_range", start: "2026-10-01", end: "2027-09-30"}},
		{"a month pair wins", "from_month=2&to_month=5&period=quarter&quarter=Q1", "2027", exportPeriod{from: 2, to: 5, mode: "month_range", start: "2026-10-01", end: "2027-09-30"}},
		{"ignores a month out of range", "month=13", "2027", exportPeriod{from: 11, to: 11, mode: "month_range", start: "2026-10-01", end: "2027-09-30"}},
		{"opens a week as its seven days", "period=week&week=2026-W48", "2027", exportPeriod{from: 11, to: 11, mode: "custom_dates", start: "2026-11-23", end: "2026-11-29"}},
		{"another year's week starts from that year", "period=week", "2026", exportPeriod{from: 11, to: 11, mode: "custom_dates", start: "2025-09-29", end: "2025-10-05"}},
		{"the year's own dates follow the year", "", "2026", exportPeriod{from: 11, to: 11, mode: "month_range", start: "2025-10-01", end: "2026-09-30"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			q, err := url.ParseQuery(tc.query)
			if err != nil {
				t.Fatal(err)
			}
			if got := exportDrawerPeriod(q, tc.fy, exportToday); got != tc.want {
				t.Fatalf("got %+v, want %+v", got, tc.want)
			}
		})
	}
}

func TestExportFormAccess(t *testing.T) {
	principal := func(role string) auth.Principal {
		return auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: role}}
	}
	tests := []struct {
		role, path string
		want       bool
	}{
		{"Admin", "/budget/export-drawer", true},
		{"Program Lead", "/budget/export-drawer", true},
		{"CCEO", "/budget/export-drawer", false}, // has the page, not data export
		{"MfiLoanOfficer", "/budget/export-drawer", false},
		{"CCEO", "/finance/fund-allocation/export-drawer", false},
		{"Accountant", "/finance/fund-allocation/export-drawer", true},
		{"ProjectCoordinator", "/fund-requests/weekly/export-drawer", true},
		{"PartnerAdmin", "/fund-requests/weekly/export-drawer", false},
		{"RegionalProgramLead", "/team-planning-oversight/export-drawer", true},
		{"Program Lead", "/country-planning-oversight/export-drawer", true}, // either oversight page opens both
		{"CCEO", "/country-planning-oversight/export-drawer", false},
		{"RegionalVicePresident", "/country-planning-oversight/export-drawer", true},
	}
	for _, tc := range tests {
		t.Run(tc.role+" "+tc.path, func(t *testing.T) {
			form, ok := exportFormFor(tc.path)
			if !ok {
				t.Fatal("not an export form")
			}
			if got := form.allowed(principal(tc.role)); got != tc.want {
				t.Fatalf("allowed = %v, want %v", got, tc.want)
			}
		})
	}
	acting := principal("CountryDirector")
	acting.InActingAppointment = true
	form, _ := exportFormFor("/budget/export-drawer")
	if form.allowed(acting) {
		t.Fatal("an acting leader's withheld pages are not decided here, so the form must refuse")
	}
}

func TestExportFormRefusalsUseTheExistingWords(t *testing.T) {
	principal := func(role string) auth.Principal {
		return auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: role}}
	}
	budget, _ := exportFormFor("/budget/export-drawer")
	if got := budget.refusal(principal("CCEO")); got != "Your role does not include data export." {
		t.Fatalf("CCEO: %q", got)
	}
	if got := budget.refusal(principal("HumanResources")); got != "Access Denied: Your active role does not have permission to view Monthly Budget." {
		t.Fatalf("HR: %q", got)
	}
}

func TestExportFormFields(t *testing.T) {
	form, ok := exportFormFor("/budget/export-drawer/")
	if !ok {
		t.Fatal("a trailing slash is the same form")
	}
	drawer := form.drawer(url.Values{}, exportToday, nil)
	if drawer.GetTitle() != "Export Budget" || drawer.GetSubmitLabel() != "Download Excel" || !drawer.GetCanSubmit() {
		t.Fatalf("drawer = %q / %q", drawer.GetTitle(), drawer.GetSubmitLabel())
	}
	names := fieldNames(drawer)
	want := []string{"period_type", "from_month", "to_month", "start_date", "end_date", "fy", "status", "activity_type"}
	if len(names) != len(want) {
		t.Fatalf("fields = %v", names)
	}
	for i := range want {
		if names[i] != want[i] {
			t.Fatalf("fields = %v, want %v", names, want)
		}
	}
	fy := drawer.GetItems()[5].GetField()
	if fy.GetValue() != "2027" || len(fy.GetOptions()) != 4 || fy.GetOptions()[0].GetLabel() != "FY 2025" {
		t.Fatalf("fy = %q with %d options", fy.GetValue(), len(fy.GetOptions()))
	}
	if when := drawer.GetItems()[3].GetField().GetShowWhen(); len(when) != 1 || when[0].GetValues()[0] != "custom_dates" {
		t.Fatalf("start date shows when %v", when)
	}
}

func TestPlanningFormOpensOnThePagesKindOfWork(t *testing.T) {
	form, _ := exportFormFor("/team-planning-oversight/export-drawer")
	drawer := form.drawer(url.Values{"activity": {"trainings"}}, exportToday, nil)
	kinds := drawer.GetItems()[len(drawer.GetItems())-1].GetField()
	if kinds.GetValue() != "trainings" || len(kinds.GetOptions()) != 13 {
		t.Fatalf("kind = %q with %d options", kinds.GetValue(), len(kinds.GetOptions()))
	}
}

func TestFinanceExportForm(t *testing.T) {
	form, _ := exportFormFor("/finance/fund-allocation/export-drawer")
	drawer := form.drawer(url.Values{"month": {"May"}, "fy": {"2026"}}, exportToday, nil)
	if drawer.GetTitle() != "Export consolidated allocation for May 2026" {
		t.Fatalf("title = %q", drawer.GetTitle())
	}
	if names := fieldNames(drawer); len(names) != 1 || names[0] != "export_mode" {
		t.Fatalf("fields = %v", names)
	}
}

func fieldNames(d *screensv1.PageDrawer) []string {
	out := []string{}
	for _, item := range d.GetItems() {
		out = append(out, item.GetField().GetName())
	}
	return out
}
