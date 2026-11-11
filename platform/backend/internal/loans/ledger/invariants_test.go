package ledger

import (
	"math/rand"
	"testing"
	"time"
)

// For many random loans and payment sequences (including reversals and
// overpayments) the ledger's identities hold exactly.
func TestTheLedgerIdentitiesHoldForRandomPaymentHistories(t *testing.T) {
	random := rand.New(rand.NewSource(20261111))
	methods := []Method{MethodFlat, MethodDeclining, MethodNone}
	for loan := 0; loan < 2000; loan++ {
		method := methods[random.Intn(len(methods))]
		rate := Rate{PPM: int64(random.Intn(60_000)) + 1}
		if method == MethodNone {
			rate = Rate{}
		}
		start := Date(2026, 11, 1)
		var dates []time.Time
		for term := 0; term < 1+random.Intn(9); term++ {
			start = start.AddDate(0, 3+random.Intn(2), random.Intn(20))
			dates = append(dates, start)
		}
		principal := Shillings(int64(500_000 + random.Intn(80_000_000)))
		schedule, err := BuildSchedule(Terms{Principal: principal, Rate: rate, Method: method, DueDates: dates,
			FeePerInstallment: Shillings(int64(random.Intn(3) * 5_000))})
		if err != nil {
			t.Fatal(err)
		}
		for index := range schedule {
			schedule[index].ID = string(rune('A' + index))
		}
		book := Book{Disbursements: []Disbursement{{ID: "d", Amount: principal, ValueDate: Date(2026, 11, 1)}},
			Installments: schedule, ScheduleVersion: 1}
		when := Date(2026, 11, 2)
		for step := 0; step < 1+random.Intn(8); step++ {
			when = when.AddDate(0, 0, 1+random.Intn(90))
			already := book.AllocatedAsOf(when)
			if step > 0 && random.Intn(5) == 0 {
				last := book.Payments[len(book.Payments)-1]
				if last.Kind == KindPayment {
					book.Payments = append(book.Payments, Payment{ID: last.ID + "r", Kind: KindReversal, ReversalOf: last.ID,
						Amount: last.Amount, ValueDate: when, Allocations: last.Allocations})
					continue
				}
			}
			amount := Shillings(int64(1 + random.Intn(int(principal/shilling)/2+1)))
			allocations, excess := Allocate(amount, schedule, already, DefaultOrder)
			var applied Money
			for _, a := range allocations {
				applied += a.Amount
				if a.Amount <= 0 {
					t.Fatalf("loan %d: a non-positive allocation %+v", loan, a)
				}
			}
			if applied+excess != amount || excess < 0 {
				t.Fatalf("loan %d: allocated %s + excess %s != amount %s", loan, applied, excess, amount)
			}
			if applied > 0 {
				book.Payments = append(book.Payments, Payment{ID: string(rune('a' + step)), Kind: KindPayment, Amount: applied,
					ValueDate: when, Allocations: allocations})
			}
			check(t, loan, book, when)
		}
		check(t, loan, book, when.AddDate(3, 0, 0))
	}
}

func check(t *testing.T, loan int, book Book, asOf time.Time) {
	t.Helper()
	position := book.Position(asOf, 14)
	allocated := book.AllocatedAsOf(asOf)
	for _, installment := range book.Installments {
		for _, component := range DefaultOrder {
			if got := allocated[installment.ID][component]; got < 0 || got > installment.due(component) {
				t.Fatalf("loan %d: %s of installment %d allocated %s of %s", loan, component, installment.Number, got, installment.due(component))
			}
		}
	}
	if position.TotalOutstanding != position.TotalObligation-position.TotalVerifiedRepayments {
		t.Fatalf("loan %d: outstanding %s != obligation %s - repaid %s", loan, position.TotalOutstanding,
			position.TotalObligation, position.TotalVerifiedRepayments)
	}
	if position.TotalOutstanding != position.OwedToday+position.FutureCharges {
		t.Fatalf("loan %d: outstanding %s != owed today %s + future %s", loan, position.TotalOutstanding,
			position.OwedToday, position.FutureCharges)
	}
	lines := book.Statement(asOf)
	if len(lines) > 0 && lines[len(lines)-1].Balance != position.OwedToday {
		t.Fatalf("loan %d: statement closes at %s, position owes %s", loan, lines[len(lines)-1].Balance, position.OwedToday)
	}
	if (position.Status == StatusSettled) != (position.TotalOutstanding == 0) {
		t.Fatalf("loan %d: status %s with %s outstanding", loan, position.Status, position.TotalOutstanding)
	}
	var remaining Money
	for _, view := range position.Installments {
		remaining += view.Remaining
	}
	if remaining != position.TotalOutstanding {
		t.Fatalf("loan %d: installments leave %s, position %s", loan, remaining, position.TotalOutstanding)
	}
}
