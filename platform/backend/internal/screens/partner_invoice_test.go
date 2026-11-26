package screens

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

func TestTheInvoiceDrawerListsEachLeadsLinesOrSaysWhyNothingIsInvoiced(t *testing.T) {
	anchor := time.Date(2026, 4, 15, 0, 0, 0, 0, time.UTC)
	item := activities.InvoiceItem{Place: "Kito", Day: anchor, Work: "School Visit", Planned: 40000, Payable: 20000}
	full := activities.InvoiceItem{Place: "Goma", Day: anchor, Work: "School Visit", DeliveredBy: "Ann", Planned: 40000, Payable: 40000}
	basis := &activities.InvoiceBasis{Label: "April 2026", Items: []activities.InvoiceItem{item, full},
		ByLead: []activities.InvoiceGroup{{Lead: &activities.InvoiceLead{Name: "Program Lead 1"}, Items: []activities.InvoiceItem{item}},
			{Items: []activities.InvoiceItem{full}}}}
	d := invoiceDrawer(basis, "", "fortnight", "advance", anchor)
	if d.GetSubmitLabel() != "Send invoices" || !d.GetCanSubmit() {
		t.Fatalf("head %v", d)
	}
	items := d.GetItems()
	if items[2].GetField().GetValue() != "week" || items[3].GetField().GetValue() != "2026-04-15" || items[1].GetField().GetReloadsPath() != invoiceDrawerPath {
		t.Fatalf("a period no option carries reads as the first: %v", items[2].GetField())
	}
	if items[4].GetText() != "April 2026 · 2 activities · 2 invoices, one for each Programme Lead" ||
		items[5].GetHeading() != "To Programme Lead: Program Lead 1" || items[7].GetHeading() != invoiceNoLead || items[8].GetText() != invoiceNoLeadNote {
		t.Fatalf("groups %v", items)
	}
	if f := items[6].GetLines().GetFacts()[0]; f.GetLabel() != "Kito 15 Apr 2026 · School Visit" || f.GetValue() != "20,000 of 40,000" {
		t.Fatalf("a half: %v", f)
	}
	if f := items[9].GetLines().GetFacts()[0]; f.GetLabel() != "Goma 15 Apr 2026 · School Visit · Ann" || f.GetValue() != "40,000 in full" {
		t.Fatalf("in full: %v", f)
	}
	empty := invoiceDrawer(&activities.InvoiceBasis{}, "", "month", "clearance", anchor)
	if empty.GetCanSubmit() || empty.GetItems()[4].GetText() != invoiceNothingHead || empty.GetItems()[5].GetText() != invoiceNothingFull {
		t.Fatalf("nothing: %v", empty)
	}
	refused := invoiceDrawer(nil, "Only a partner account can submit partner invoices.", "month", "advance", anchor)
	if refused.GetCanSubmit() || refused.GetItems()[4].GetNote().GetTone() != "danger" {
		t.Fatalf("refused: %v", refused)
	}
}
