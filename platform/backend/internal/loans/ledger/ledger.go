// Package ledger is the arithmetic of a school loan: exact money, the
// term-based repayment schedule, how a payment is allocated, and the
// position and statement derived from the ledger's postings.
//
// It holds no state and touches no database. The authoritative postings are
// the existing ledger's (apps/business_transformation/lending_ledger.py:
// disbursements, installments, repayment transactions and their
// allocations); this package computes from them, and proposes the
// schedule and allocations the lender confirms before they are posted there.
// Its rules mirror the existing ledger's so the two always agree:
//
//   - money has a quantum of 0.01 (Money counts hundredths of a shilling);
//   - an allocation may never exceed what a component is due;
//   - only postings with a value date on or before the as-of date count;
//   - a reversal subtracts exactly the allocations it reverses;
//   - an installment is overdue once its due date has passed with anything
//     unpaid, and days past due count from the earliest such installment.
package ledger

import (
	"errors"
	"fmt"
	"math/big"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Money is an amount in hundredths of a Uganda shilling. Never a float.
type Money int64

// Shillings is n whole shillings.
func Shillings(n int64) Money { return Money(n * 100) }

// ParseMoney reads a decimal amount such as "38500000.00" exactly.
func ParseMoney(raw string) (Money, error) {
	value := strings.TrimSpace(raw)
	negative := strings.HasPrefix(value, "-")
	value = strings.TrimPrefix(value, "-")
	whole, fraction, hasFraction := strings.Cut(value, ".")
	if whole == "" || !digits(whole) || (hasFraction && (fraction == "" || len(fraction) > 2 || !digits(fraction))) {
		return 0, fmt.Errorf("ledger: %q is not an amount", raw)
	}
	for len(fraction) < 2 {
		fraction += "0"
	}
	number, err := strconv.ParseInt(whole+fraction, 10, 64)
	if err != nil || len(whole) > 15 {
		return 0, fmt.Errorf("ledger: %q is too large", raw)
	}
	if negative {
		number = -number
	}
	return Money(number), nil
}

func digits(s string) bool {
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return s != ""
}

// String is the amount as a plain decimal, as the existing ledger stores it.
func (m Money) String() string {
	sign := ""
	value := int64(m)
	if value < 0 {
		sign, value = "-", -value
	}
	return fmt.Sprintf("%s%d.%02d", sign, value/100, value%100)
}

// FormatUGX writes "UGX 38,500,000", keeping cents only when there are any.
func FormatUGX(m Money) string {
	sign := ""
	value := int64(m)
	if value < 0 {
		sign, value = "-", -value
	}
	whole := strconv.FormatInt(value/100, 10)
	var grouped strings.Builder
	for index, r := range whole {
		if index > 0 && (len(whole)-index)%3 == 0 {
			grouped.WriteByte(',')
		}
		grouped.WriteRune(r)
	}
	if cents := value % 100; cents != 0 {
		return fmt.Sprintf("UGX %s%s.%02d", sign, grouped.String(), cents)
	}
	return "UGX " + sign + grouped.String()
}

// Date is a calendar day (midnight UTC, so comparisons are by day only).
func Date(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

// DayOf is the calendar day of t in its own location.
func DayOf(t time.Time) time.Time { return Date(t.Year(), t.Month(), t.Day()) }

// Rate is an interest rate per repayment period, in parts per million
// (2.5% = 25,000), so it too is exact.
type Rate struct{ PPM int64 }

// ParseRate reads a percentage per period such as "2.5" (up to four decimals).
func ParseRate(percent string) (Rate, error) {
	value := strings.TrimSpace(percent)
	whole, fraction, _ := strings.Cut(value, ".")
	if whole == "" || !digits(whole) || (fraction != "" && (len(fraction) > 4 || !digits(fraction))) {
		return Rate{}, fmt.Errorf("ledger: %q is not a percentage", percent)
	}
	for len(fraction) < 4 {
		fraction += "0"
	}
	ppm, err := strconv.ParseInt(whole+fraction, 10, 64)
	if err != nil || ppm > 1_000_000 {
		return Rate{}, fmt.Errorf("ledger: %q is not a sensible rate per period", percent)
	}
	return Rate{PPM: ppm}, nil
}

// Percent is the rate as written, e.g. "2.5".
func (r Rate) Percent() string {
	text := fmt.Sprintf("%d.%04d", r.PPM/10_000, r.PPM%10_000)
	return strings.TrimSuffix(strings.TrimRight(text, "0"), ".")
}

// Method is how interest is calculated.
type Method string

const (
	// MethodNone: no interest (fees may still apply).
	MethodNone Method = "none"
	// MethodFlat: each period's interest is the rate on the original principal.
	MethodFlat Method = "flat"
	// MethodDeclining: each period's interest is the rate on the principal
	// still outstanding at the start of the period (equal principal shares).
	MethodDeclining Method = "declining_balance"
)

// MethodLabel describes a method to a school.
func MethodLabel(m Method) string {
	switch m {
	case MethodFlat:
		return "Flat: the rate on the original amount, each term"
	case MethodDeclining:
		return "Declining balance: the rate on what is still owed, each term"
	}
	return "No interest"
}

// Terms are what a schedule is built from.
type Terms struct {
	Principal         Money
	Rate              Rate
	Method            Method
	FeePerInstallment Money
	// DueDates are the repayment dates, one per school term, increasing.
	DueDates []time.Time
}

// Installment is one scheduled repayment.
type Installment struct {
	ID             string
	Number         int
	DueDate        time.Time
	OpeningBalance Money
	Principal      Money
	Interest       Money
	Fee            Money
}

// Total is what the installment asks for.
func (i Installment) Total() Money { return i.Principal + i.Interest + i.Fee }

const shilling Money = 100

// BuildSchedule proposes the installments for terms: principal in equal
// whole-shilling shares with the remainder on the last, interest rounded half
// up to whole shillings. It invents nothing: no interest without a method and
// rate, no fee unless one is given.
func BuildSchedule(t Terms) ([]Installment, error) {
	count := len(t.DueDates)
	switch {
	case t.Principal <= 0 || t.Principal%shilling != 0:
		return nil, errors.New("ledger: the principal must be a positive amount in whole shillings")
	case count == 0:
		return nil, errors.New("ledger: a schedule needs at least one due date")
	case t.FeePerInstallment < 0:
		return nil, errors.New("ledger: a fee cannot be negative")
	}
	switch t.Method {
	case MethodFlat, MethodDeclining:
		if t.Rate.PPM <= 0 {
			return nil, errors.New("ledger: an interest method needs a rate")
		}
	case MethodNone:
		if t.Rate.PPM != 0 {
			return nil, errors.New("ledger: a rate needs an interest method")
		}
	default:
		return nil, fmt.Errorf("ledger: %q is not a supported interest method", t.Method)
	}
	for index := 1; index < count; index++ {
		if !DayOf(t.DueDates[index]).After(DayOf(t.DueDates[index-1])) {
			return nil, errors.New("ledger: due dates must be in increasing order")
		}
	}
	share := (t.Principal / Money(count) / shilling) * shilling
	schedule := make([]Installment, count)
	balance := t.Principal
	for index := range schedule {
		principal := share
		if index == count-1 {
			principal = balance
		}
		var interest Money
		switch t.Method {
		case MethodFlat:
			interest = percentOf(t.Principal, t.Rate)
		case MethodDeclining:
			interest = percentOf(balance, t.Rate)
		}
		schedule[index] = Installment{
			Number: index + 1, DueDate: DayOf(t.DueDates[index]), OpeningBalance: balance,
			Principal: principal, Interest: interest, Fee: t.FeePerInstallment,
		}
		balance -= principal
	}
	return schedule, nil
}

// percentOf is amount × rate, rounded half up to a whole shilling.
func percentOf(amount Money, rate Rate) Money {
	product := new(big.Int).Mul(big.NewInt(int64(amount)), big.NewInt(rate.PPM))
	unit := big.NewInt(1_000_000 * int64(shilling)) // to whole shillings
	quotient, remainder := new(big.Int).QuoRem(product, unit, new(big.Int))
	if new(big.Int).Mul(remainder, big.NewInt(2)).Cmp(unit) >= 0 {
		quotient.Add(quotient, big.NewInt(1))
	}
	return Money(quotient.Int64()) * shilling
}

// Component is a part of an installment a payment settles.
type Component string

const (
	Principal Component = "principal"
	Interest  Component = "interest"
	Fee       Component = "fee"
)

// DefaultOrder settles the oldest installment first, and within it fees,
// then interest, then principal: the common MFI order. A lender's agreement
// may set another.
var DefaultOrder = []Component{Fee, Interest, Principal}

// Allocation is part of a payment applied to one component of one installment.
type Allocation struct {
	InstallmentID string
	Component     Component
	Amount        Money
}

// Allocated is what has already been applied, by installment and component.
type Allocated map[string]map[Component]Money

func (a Allocated) add(id string, c Component, m Money) {
	if a[id] == nil {
		a[id] = map[Component]Money{}
	}
	a[id][c] += m
}

func (i Installment) due(c Component) Money {
	switch c {
	case Principal:
		return i.Principal
	case Interest:
		return i.Interest
	case Fee:
		return i.Fee
	}
	return 0
}

// Allocate applies amount to installments in due-date order, each in order's
// component order, never beyond what is due. Whatever is left is returned as
// excess: an overpayment is kept and reported, never dropped.
func Allocate(amount Money, installments []Installment, already Allocated, order []Component) ([]Allocation, Money) {
	sorted := append([]Installment(nil), installments...)
	sort.SliceStable(sorted, func(a, b int) bool {
		if !sorted[a].DueDate.Equal(sorted[b].DueDate) {
			return sorted[a].DueDate.Before(sorted[b].DueDate)
		}
		return sorted[a].Number < sorted[b].Number
	})
	var allocations []Allocation
	left := amount
	for _, installment := range sorted {
		for _, component := range order {
			if left <= 0 {
				return allocations, 0
			}
			open := installment.due(component) - already[installment.ID][component]
			if open <= 0 {
				continue
			}
			take := min(open, left)
			allocations = append(allocations, Allocation{InstallmentID: installment.ID, Component: component, Amount: take})
			left -= take
		}
	}
	return allocations, max(left, 0)
}

// Kinds of ledger transaction, as the existing ledger names them.
const (
	KindPayment  = "payment"
	KindReversal = "reversal"
)

// Disbursement is money the lender confirmed it paid out.
type Disbursement struct {
	ID         string
	Amount     Money
	ValueDate  time.Time
	Reference  string
	ReversedOn *time.Time
}

// Payment is a verified repayment, or the reversal of one.
type Payment struct {
	ID          string
	Kind        string
	ReversalOf  string
	Amount      Money
	ValueDate   time.Time
	Reference   string
	Allocations []Allocation
}

// Book is one loan's postings: disbursements, the current schedule version's
// installments, and verified payments with their allocations.
type Book struct {
	Disbursements   []Disbursement
	Installments    []Installment
	ScheduleVersion int
	Payments        []Payment
}

func onOrBefore(t, asOf time.Time) bool { return !DayOf(t).After(DayOf(asOf)) }

// AllocatedAsOf is the net allocation by installment and component, counting
// postings dated up to asOf; a reversal subtracts what it reverses.
func (b Book) AllocatedAsOf(asOf time.Time) Allocated {
	allocated := Allocated{}
	for _, p := range b.Payments {
		if !onOrBefore(p.ValueDate, asOf) {
			continue
		}
		sign := Money(1)
		if p.Kind == KindReversal {
			sign = -1
		}
		for _, a := range p.Allocations {
			allocated.add(a.InstallmentID, a.Component, sign*a.Amount)
		}
	}
	return allocated
}

// NetDisbursed is what was paid out by asOf, less reversed disbursements.
func (b Book) NetDisbursed(asOf time.Time) Money {
	var total Money
	for _, d := range b.Disbursements {
		if !onOrBefore(d.ValueDate, asOf) {
			continue
		}
		if d.ReversedOn != nil && onOrBefore(*d.ReversedOn, asOf) {
			continue
		}
		total += d.Amount
	}
	return total
}
