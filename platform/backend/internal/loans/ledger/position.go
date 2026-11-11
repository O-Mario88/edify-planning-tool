package ledger

import (
	"fmt"
	"sort"
	"time"
)

// Installment statuses.
const (
	InstallmentUpcoming      = "upcoming"
	InstallmentDue           = "due"
	InstallmentPartiallyPaid = "partially_paid"
	InstallmentPaid          = "paid"
	InstallmentOverdue       = "overdue"
)

// Servicing statuses: where the loan stands financially, a dimension apart
// from the application's status and the collateral's.
const (
	StatusAwaitingDisbursement = "awaiting_disbursement"
	StatusCurrent              = "active_current"
	StatusPaymentDue           = "active_payment_due"
	StatusPartiallyPaid        = "active_partially_paid"
	StatusOverdue              = "active_overdue"
	StatusRestructured         = "active_restructured"
	StatusSettled              = "financially_settled"
	// StatusNoSchedule: money was disbursed but no schedule is posted yet,
	// so nothing can be said to be due.
	StatusNoSchedule = "active_schedule_pending"
)

var statusLabels = map[string]string{
	StatusAwaitingDisbursement: "Awaiting disbursement",
	StatusCurrent:              "Active — current",
	StatusPaymentDue:           "Active — payment due",
	StatusPartiallyPaid:        "Active — partially paid",
	StatusOverdue:              "Active — overdue",
	StatusRestructured:         "Active — restructured",
	StatusSettled:              "Financially settled",
	StatusNoSchedule:           "Active — schedule not yet set",
	InstallmentUpcoming:        "Upcoming",
	InstallmentDue:             "Due",
	InstallmentPartiallyPaid:   "Partially paid",
	InstallmentPaid:            "Paid",
	InstallmentOverdue:         "Overdue",
}

// Label is a status as people read it.
func Label(status string) string {
	if label, ok := statusLabels[status]; ok {
		return label
	}
	return status
}

// InstallmentView is an installment with what has been paid against it.
type InstallmentView struct {
	Installment
	PaidPrincipal, PaidInterest, PaidFee Money
	Paid, Remaining                      Money
	Status                               string
}

// Position is a loan's standing on a day, derived only from verified
// postings. Pending receipts are never part of it.
type Position struct {
	AsOf time.Time
	// Principal.
	NetDisbursed, PrincipalRepaid, OutstandingPrincipal Money
	// What the agreement asks for in all, what was paid, what remains.
	TotalObligation, TotalVerifiedRepayments, TotalOutstanding Money
	InterestScheduled, FeesScheduled                           Money
	// What has fallen due by AsOf and is unpaid, and since when.
	AmountOverdue Money
	DaysPastDue   int
	// OwedToday is disbursed principal plus interest and fees already due,
	// less what was paid: the statement's closing balance. FutureCharges is
	// the interest and fees not yet due; OwedToday + FutureCharges is
	// TotalOutstanding whenever the schedule covers the disbursement.
	OwedToday, FutureCharges Money
	NextDue                  *InstallmentView
	LastPaymentDate          *time.Time
	Installments             []InstallmentView
	Status                   string
}

// Position computes the loan's standing at asOf. An installment due within
// dueWindowDays ahead is Due rather than Upcoming.
func (b Book) Position(asOf time.Time, dueWindowDays int) Position {
	asOf = DayOf(asOf)
	p := Position{AsOf: asOf, NetDisbursed: b.NetDisbursed(asOf)}
	allocated := b.AllocatedAsOf(asOf)
	installments := append([]Installment(nil), b.Installments...)
	sort.SliceStable(installments, func(i, j int) bool {
		if !installments[i].DueDate.Equal(installments[j].DueDate) {
			return installments[i].DueDate.Before(installments[j].DueDate)
		}
		return installments[i].Number < installments[j].Number
	})
	var earliestOverdue *time.Time
	anyPartial, anyDue := false, false
	window := asOf.AddDate(0, 0, dueWindowDays)
	for _, installment := range installments {
		paid := allocated[installment.ID]
		view := InstallmentView{
			Installment:   installment,
			PaidPrincipal: paid[Principal], PaidInterest: paid[Interest], PaidFee: paid[Fee],
		}
		view.Paid = view.PaidPrincipal + view.PaidInterest + view.PaidFee
		view.Remaining = max(installment.Total()-view.Paid, 0)
		p.TotalObligation += installment.Total()
		p.InterestScheduled += installment.Interest
		p.FeesScheduled += installment.Fee
		p.PrincipalRepaid += view.PaidPrincipal
		due := DayOf(installment.DueDate)
		if onOrBefore(due, asOf) {
			p.OwedToday += installment.Interest + installment.Fee
		} else {
			p.FutureCharges += installment.Interest + installment.Fee
		}
		switch {
		case view.Remaining == 0:
			view.Status = InstallmentPaid
		case due.Before(asOf):
			view.Status = InstallmentOverdue
			p.AmountOverdue += view.Remaining
			if earliestOverdue == nil {
				earliestOverdue = &due
			}
		case view.Paid > 0:
			view.Status = InstallmentPartiallyPaid
			anyPartial = true
		case !due.After(window):
			view.Status = InstallmentDue
			anyDue = true
		default:
			view.Status = InstallmentUpcoming
		}
		if view.Remaining > 0 && p.NextDue == nil {
			next := view
			p.NextDue = &next
		}
		p.Installments = append(p.Installments, view)
	}
	reversed := b.ReversedBy(asOf)
	for _, payment := range b.Payments {
		if !onOrBefore(payment.ValueDate, asOf) {
			continue
		}
		var applied Money
		for _, a := range payment.Allocations {
			applied += a.Amount
		}
		if payment.Kind == KindReversal {
			p.TotalVerifiedRepayments -= applied
		} else {
			p.TotalVerifiedRepayments += applied
			if !reversed[payment.ID] && (p.LastPaymentDate == nil || payment.ValueDate.After(*p.LastPaymentDate)) {
				when := DayOf(payment.ValueDate)
				p.LastPaymentDate = &when
			}
		}
	}
	if earliestOverdue != nil {
		p.DaysPastDue = int(asOf.Sub(*earliestOverdue).Hours() / 24)
	}
	p.OutstandingPrincipal = max(p.NetDisbursed-p.PrincipalRepaid, 0)
	p.OwedToday += p.NetDisbursed - p.TotalVerifiedRepayments
	if len(installments) == 0 {
		// Without a schedule, only the disbursed principal is known to be owed.
		p.TotalObligation = p.NetDisbursed
	}
	p.TotalOutstanding = max(p.TotalObligation-p.TotalVerifiedRepayments, 0)

	switch {
	case p.NetDisbursed == 0:
		p.Status = StatusAwaitingDisbursement
	case len(installments) == 0:
		p.Status = StatusNoSchedule
	case p.TotalOutstanding == 0 && p.OutstandingPrincipal == 0:
		p.Status = StatusSettled
	case p.AmountOverdue > 0:
		p.Status = StatusOverdue
	case anyPartial:
		p.Status = StatusPartiallyPaid
	case anyDue:
		p.Status = StatusPaymentDue
	case b.ScheduleVersion > 1:
		p.Status = StatusRestructured
	default:
		p.Status = StatusCurrent
	}
	return p
}

// Line is one line of a school's statement.
type Line struct {
	Date        time.Time
	Description string
	Reference   string
	Debit       Money
	Credit      Money
	// Balance is the running balance after this line: what the school owed
	// on that day.
	Balance Money
}

// Statement is the loan's ledger up to asOf, oldest first: each
// disbursement and each installment's interest and fees on its due date as
// debits, each verified payment as a credit and each reversal as a debit.
// Its closing balance equals Position(asOf).OwedToday.
func (b Book) Statement(asOf time.Time) []Line {
	asOf = DayOf(asOf)
	type entry struct {
		line  Line
		order int
	}
	var entries []entry
	for _, d := range b.Disbursements {
		if !onOrBefore(d.ValueDate, asOf) {
			continue
		}
		entries = append(entries, entry{Line{Date: DayOf(d.ValueDate), Description: "Loan disbursed",
			Reference: d.Reference, Debit: d.Amount}, 0})
		if d.ReversedOn != nil && onOrBefore(*d.ReversedOn, asOf) {
			entries = append(entries, entry{Line{Date: DayOf(*d.ReversedOn), Description: "Disbursement reversed",
				Reference: d.Reference, Credit: d.Amount}, 0})
		}
	}
	for _, i := range b.Installments {
		if !onOrBefore(i.DueDate, asOf) {
			continue
		}
		if i.Interest > 0 {
			entries = append(entries, entry{Line{Date: DayOf(i.DueDate),
				Description: fmt.Sprintf("Interest, installment %d", i.Number), Debit: i.Interest}, 1})
		}
		if i.Fee > 0 {
			entries = append(entries, entry{Line{Date: DayOf(i.DueDate),
				Description: fmt.Sprintf("Fees, installment %d", i.Number), Debit: i.Fee}, 1})
		}
	}
	for _, payment := range b.Payments {
		if !onOrBefore(payment.ValueDate, asOf) {
			continue
		}
		var applied Money
		for _, a := range payment.Allocations {
			applied += a.Amount
		}
		if payment.Kind == KindReversal {
			entries = append(entries, entry{Line{Date: DayOf(payment.ValueDate), Description: "Payment reversed",
				Reference: payment.Reference, Debit: applied}, 2})
		} else {
			entries = append(entries, entry{Line{Date: DayOf(payment.ValueDate), Description: "Payment received (verified)",
				Reference: payment.Reference, Credit: applied}, 2})
		}
	}
	sort.SliceStable(entries, func(i, j int) bool {
		if !entries[i].line.Date.Equal(entries[j].line.Date) {
			return entries[i].line.Date.Before(entries[j].line.Date)
		}
		return entries[i].order < entries[j].order
	})
	lines := make([]Line, len(entries))
	var balance Money
	for index, e := range entries {
		balance += e.line.Debit - e.line.Credit
		e.line.Balance = balance
		lines[index] = e.line
	}
	return lines
}

// ReversedBy are the payments reversed on or before asOf, by id.
func (b Book) ReversedBy(asOf time.Time) map[string]bool {
	reversed := map[string]bool{}
	for _, payment := range b.Payments {
		if payment.Kind == KindReversal && onOrBefore(payment.ValueDate, asOf) {
			reversed[payment.ReversalOf] = true
		}
	}
	return reversed
}
