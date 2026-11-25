package budgetpage

import "testing"

func TestCostPlanSheetLaysTheLedgerOutAsThePage(t *testing.T) {
	gs := []*group{{
		label: "School Visit", kind: "standard", total: 50000, staffTotal: 30000, vendorTotal: 20000,
		activityIDs: map[string]bool{"a1": true},
		rows: []*row{
			{item: "Transport", rate: 30000, dates: map[string]bool{"2026-11-02": true}, people: map[string]int64{"a1": 1},
				activityIDs: map[string]bool{"a1": true}, staffTotal: 30000, total: 30000},
			{item: "Partner fee", rate: 20000, dates: map[string]bool{"2026-11-02": true}, people: map[string]int64{},
				activityIDs: map[string]bool{"a1": true}, vendorTotal: 20000, total: 20000},
		},
	}}
	sheet := costPlanSheet(gs, "Period: 2 Nov 2026 – 2 Nov 2026")
	if len(sheet.Rows) != 10 {
		t.Fatalf("rows = %d, want title, caption, period, blank, band, headings, two items, subtotal, total", len(sheet.Rows))
	}
	want := map[int]string{1: "title", 2: "caption", 3: "caption", 5: "band", 6: "columns", 9: "subtotal", 10: "total"}
	for r, style := range want {
		if sheet.RowStyles[r] != style {
			t.Errorf("row %d style %q, want %q", r, sheet.RowStyles[r], style)
		}
	}
	if !sheet.NoFilter || !sheet.NoFreeze || sheet.NumberFormats[6] != rules.CostPlanSheet.Money {
		t.Error("the sheet has no filter, no frozen heading and money in its last three columns")
	}
	if empty := costPlanSheet(nil, ""); len(empty.Rows) != 6 || empty.RowStyles[5] != "caption" {
		t.Errorf("an empty plan says so before its Grand total: %d rows", len(empty.Rows))
	}
}
