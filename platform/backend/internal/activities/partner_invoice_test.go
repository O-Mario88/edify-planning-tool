package activities

import (
	"errors"
	"testing"
	"time"
)

func day(s string) time.Time {
	d, err := time.Parse(time.DateOnly, s)
	if err != nil {
		panic(err)
	}
	return d
}

func TestTheInvoicePeriodIsTheWeekMonthOrQuarterAsDjangoBoundsIt(t *testing.T) {
	cases := []struct{ kind, anchor, start, end, label string }{
		{"week", "2026-04-15", "2026-04-13", "2026-04-19", "Week of 13 Apr – 19 Apr 2026"},
		{"week", "2026-04-19", "2026-04-13", "2026-04-19", "Week of 13 Apr – 19 Apr 2026"},
		{"month", "2026-02-10", "2026-02-01", "2026-02-28", "February 2026"},
		// get_quarter_date_range's end is the next quarter's first day.
		{"quarter", "2026-05-15", "2026-04-01", "2026-07-01", "01 Apr – 01 Jul 2026"},
		{"quarter", "2026-11-02", "2026-10-01", "2027-01-01", "01 Oct – 01 Jan 2027"},
	}
	for _, c := range cases {
		start, end, err := invoicePeriod(c.kind, day(c.anchor))
		if err != nil || !start.Equal(day(c.start)) || !end.Equal(day(c.end)) {
			t.Fatalf("%s %s: %v %v %v", c.kind, c.anchor, start, end, err)
		}
		if got := invoicePeriodLabel(c.kind, start, end); got != c.label {
			t.Fatalf("label %q, want %q", got, c.label)
		}
	}
	var refusal *Refusal
	if _, _, err := invoicePeriod("year", day("2026-04-15")); !errors.As(err, &refusal) || refusal.Message != invoiceBadPeriod {
		t.Fatalf("a year: %v", err)
	}
}

func TestAnInstalmentTakesTheWorkItPays(t *testing.T) {
	none := map[string]int64{}
	cases := []struct {
		name, instalment      string
		paid                  map[string]int64
		done, inFlight, takes bool
		payable               int64
	}{
		{"scheduled work: half", invoiceAdvance, none, false, false, true, 20000},
		{"completed work is invoiced in full instead", invoiceAdvance, none, true, false, false, 0},
		{"an advance paid", invoiceAdvance, map[string]int64{invoiceAdvance: 20000}, false, false, false, 0},
		{"completed in full", invoiceClearance, none, true, false, true, 40000},
		{"the balance after a paid half", invoiceClearance, map[string]int64{invoiceAdvance: 20000}, true, false, true, 20000},
		{"not yet completed with evidence", invoiceClearance, none, false, false, false, 0},
		{"a half still on an invoice", invoiceClearance, none, true, true, false, 0},
		{"already cleared", invoiceClearance, map[string]int64{invoiceClearance: 40000}, true, false, false, 0},
	}
	for _, c := range cases {
		payable, takes := invoicePayable(c.instalment, 40000, c.paid, c.done, c.inFlight)
		if takes != c.takes || payable != c.payable && c.takes {
			t.Fatalf("%s: %d %v", c.name, payable, takes)
		}
	}
}

func TestAnInvoiceLineIsCategorisedByItsWork(t *testing.T) {
	cases := []struct {
		it   InvoiceItem
		kind string
		want string
	}{
		{InvoiceItem{schoolID: "s1", delivery: "partner"}, "in_school_training", "Training Facilitation Fee"},
		{InvoiceItem{delivery: "staff", facilitating: "p1"}, "cluster_meeting", "Meeting Facilitation Fee"},
		{InvoiceItem{schoolID: "s1", delivery: "partner"}, "school_visit", "School Visits"},
		{InvoiceItem{delivery: "partner"}, "partner_activity", "Other Field Work"},
	}
	for _, c := range cases {
		if got := invoiceCategory(c.it, c.kind); got != c.want {
			t.Fatalf("%s: %q, want %q", c.kind, got, c.want)
		}
	}
}

func TestAnInvoiceLineGoesToTheLeadWhoHoldsTheSchoolThenTheLeadItsOfficerReportsTo(t *testing.T) {
	pl1, pl2 := &InvoiceLead{StaffID: "pl1", Name: "A Lead"}, &InvoiceLead{StaffID: "pl2", Name: "B Lead"}
	r := &leadResolver{
		holders:   map[string][]string{"held": {"cceo", "pl2"}, "officer": {"cceo"}},
		lead:      map[string]*InvoiceLead{"pl1": pl1, "pl2": pl2},
		staffFor:  map[string]string{"cceo": "cceo", "u-cceo": "cceo", "pl1": "pl1"},
		reportsTo: map[string]*InvoiceLead{"cceo": pl1},
	}
	if got := r.leadOf(InvoiceItem{schoolID: "held"}); got != pl2 {
		t.Fatalf("a Lead holding the school comes first: %v", got)
	}
	if got := r.leadOf(InvoiceItem{schoolID: "officer"}); got != pl1 {
		t.Fatalf("the holder's Lead: %v", got)
	}
	if got := r.leadOf(InvoiceItem{monitor: "u-cceo"}); got != pl1 {
		t.Fatalf("no school: the officer the activity names: %v", got)
	}
	if got := r.leadOf(InvoiceItem{responsible: "nobody"}); got != nil {
		t.Fatalf("no Lead: %v", got)
	}
}

func TestTheInvoiceConfirmationSaysWhoHasIt(t *testing.T) {
	lead := &InvoiceLead{Name: "Program Lead 1"}
	one := &InvoiceBasis{Instalment: invoiceAdvance, Label: "April 2026", Payable: 340000, ByLead: []InvoiceGroup{{Lead: lead}}}
	if got := invoiceSentMessage(one); got != "Invoice for April 2026 sent: the 50% advance of UGX 340,000 is with Program Lead 1, the Programme Lead, for confirmation." {
		t.Fatalf("one: %q", got)
	}
	finance := &InvoiceBasis{Instalment: invoiceClearance, Label: "April 2026", Payable: 40000, ByLead: []InvoiceGroup{{}}}
	if got := invoiceSentMessage(finance); got != "Invoice for April 2026 sent: the balance of UGX 40,000 is with Edify's finance team for confirmation." {
		t.Fatalf("finance: %q", got)
	}
	many := &InvoiceBasis{Instalment: invoiceAdvance, Label: "April 2026", Payable: 1000, ByLead: []InvoiceGroup{{Lead: lead}, {}}}
	if got := invoiceSentMessage(many); got != "2 invoices for April 2026 sent: the 50% advance of UGX 1,000 is with each Programme Lead for confirmation." {
		t.Fatalf("many: %q", got)
	}
}

func TestOrThenStripFallsBackOnlyForAnEmptyValue(t *testing.T) {
	if OrThenStrip("", "month") != "month" || OrThenStrip("  ", "month") != "" || OrThenStrip(" week ", "month") != "week" {
		t.Fatal("(value or fallback).strip()")
	}
}
