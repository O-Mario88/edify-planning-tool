package ledger

import (
	"testing"
	"time"
)

func day(y int, m time.Month, d int) time.Time { return Date(y, m, d) }

func mustMoney(t *testing.T, raw string) Money {
	t.Helper()
	m, err := ParseMoney(raw)
	if err != nil {
		t.Fatalf("ParseMoney(%q): %v", raw, err)
	}
	return m
}

func TestMoneyIsExact(t *testing.T) {
	for raw, want := range map[string]Money{
		"0": 0, "38500000": 3_850_000_000, "38500000.00": 3_850_000_000, "0.5": 50, "1000.05": 100_005, "-12.30": -1230,
	} {
		if got := mustMoney(t, raw); got != want {
			t.Errorf("ParseMoney(%q) = %d, want %d", raw, got, want)
		}
	}
	for _, raw := range []string{"", "1.005", "1e5", "abc", "1,000", "12.3.4"} {
		if _, err := ParseMoney(raw); err == nil {
			t.Errorf("ParseMoney(%q) accepted", raw)
		}
	}
	if s := Money(3_850_000_000).String(); s != "38500000.00" {
		t.Fatalf("String %q", s)
	}
	if s := FormatUGX(Money(3_850_000_000)); s != "UGX 38,500,000" {
		t.Fatalf("FormatUGX %q", s)
	}
	if s := FormatUGX(Money(100_050)); s != "UGX 1,000.50" {
		t.Fatalf("FormatUGX %q", s)
	}
}

func termDates() []time.Time {
	return []time.Time{day(2027, 2, 15), day(2027, 6, 1), day(2027, 9, 15), day(2028, 2, 15)}
}

func TestAFlatScheduleChargesInterestOnTheOriginalPrincipal(t *testing.T) {
	rate, _ := ParseRate("3")
	schedule, err := BuildSchedule(Terms{
		Principal: Shillings(10_000_001), Rate: rate, Method: MethodFlat, DueDates: termDates(),
	})
	if err != nil {
		t.Fatal(err)
	}
	var principal Money
	for _, i := range schedule {
		principal += i.Principal
		if i.Interest != Shillings(300_000) {
			t.Fatalf("installment %d interest %s, want 300,000 every term", i.Number, i.Interest)
		}
		if i.Principal%100 != 0 || i.Interest%100 != 0 {
			t.Fatalf("installment %d is not in whole shillings", i.Number)
		}
	}
	if principal != Shillings(10_000_001) {
		t.Fatalf("scheduled principal %s must equal the principal exactly", principal)
	}
	if schedule[3].Principal != Shillings(2_500_001) {
		t.Fatalf("the last installment takes the remainder: %s", schedule[3].Principal)
	}
}

func TestADecliningScheduleChargesInterestOnTheOpeningBalance(t *testing.T) {
	rate, _ := ParseRate("2.5")
	schedule, err := BuildSchedule(Terms{
		Principal: Shillings(8_000_000), Rate: rate, Method: MethodDeclining, DueDates: termDates(),
		FeePerInstallment: Shillings(10_000),
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []Money{Shillings(200_000), Shillings(150_000), Shillings(100_000), Shillings(50_000)}
	for index, i := range schedule {
		if i.Interest != want[index] || i.Principal != Shillings(2_000_000) || i.Fee != Shillings(10_000) {
			t.Fatalf("installment %d: principal %s interest %s fee %s", i.Number, i.Principal, i.Interest, i.Fee)
		}
		if i.OpeningBalance != Shillings(8_000_000)-Money(index)*Shillings(2_000_000) {
			t.Fatalf("installment %d opening balance %s", i.Number, i.OpeningBalance)
		}
	}
}

func TestInterestRoundsHalfUpToWholeShillings(t *testing.T) {
	rate, _ := ParseRate("1.25") // 1.25% of 1,000,050 = 12,500.625 -> 12,501
	schedule, err := BuildSchedule(Terms{Principal: Shillings(1_000_050), Rate: rate, Method: MethodFlat, DueDates: termDates()[:1]})
	if err != nil {
		t.Fatal(err)
	}
	if schedule[0].Interest != Shillings(12_501) {
		t.Fatalf("interest %s", schedule[0].Interest)
	}
}

func TestAScheduleNeedsIncreasingDatesAndAPrincipal(t *testing.T) {
	rate, _ := ParseRate("2")
	bad := []Terms{
		{Principal: 0, Method: MethodFlat, Rate: rate, DueDates: termDates()},
		{Principal: Shillings(1), Method: MethodFlat, Rate: rate},
		{Principal: Shillings(1_000), Method: MethodFlat, Rate: rate, DueDates: []time.Time{day(2027, 6, 1), day(2027, 2, 1)}},
		{Principal: Shillings(1_000), Method: "annuity", Rate: rate, DueDates: termDates()},
		{Principal: Shillings(1_000), Method: MethodNone, Rate: rate, DueDates: termDates()},
	}
	for index, terms := range bad {
		if _, err := BuildSchedule(terms); err == nil {
			t.Errorf("terms %d were accepted", index)
		}
	}
}

func scheduleOf(t *testing.T) []Installment {
	t.Helper()
	rate, _ := ParseRate("2.5")
	schedule, err := BuildSchedule(Terms{Principal: Shillings(8_000_000), Rate: rate, Method: MethodDeclining, DueDates: termDates()})
	if err != nil {
		t.Fatal(err)
	}
	for index := range schedule {
		schedule[index].ID = string(rune('a' + index))
	}
	return schedule
}

func TestAllocationPaysTheOldestInstallmentInterestFirst(t *testing.T) {
	schedule := scheduleOf(t)
	allocations, excess := Allocate(Shillings(2_300_000), schedule, Allocated{}, DefaultOrder)
	if excess != 0 {
		t.Fatalf("excess %s", excess)
	}
	// Installment 1: 200,000 interest then 2,000,000 principal; installment 2: 100,000 of its interest.
	want := []Allocation{
		{InstallmentID: "a", Component: Interest, Amount: Shillings(200_000)},
		{InstallmentID: "a", Component: Principal, Amount: Shillings(2_000_000)},
		{InstallmentID: "b", Component: Interest, Amount: Shillings(100_000)},
	}
	if len(allocations) != len(want) {
		t.Fatalf("allocations %+v", allocations)
	}
	for index := range want {
		if allocations[index] != want[index] {
			t.Fatalf("allocation %d = %+v, want %+v", index, allocations[index], want[index])
		}
	}
}

func TestAnOverpaymentIsKeptAsExcessNeverDropped(t *testing.T) {
	schedule := scheduleOf(t)
	total := Money(0)
	for _, i := range schedule {
		total += i.Total()
	}
	allocations, excess := Allocate(total+Shillings(55_000), schedule, Allocated{}, DefaultOrder)
	var allocated Money
	for _, a := range allocations {
		allocated += a.Amount
	}
	if allocated != total || excess != Shillings(55_000) {
		t.Fatalf("allocated %s excess %s", allocated, excess)
	}
}

func bookWith(t *testing.T, payments ...Payment) Book {
	t.Helper()
	return Book{
		Disbursements: []Disbursement{{ID: "d1", Amount: Shillings(8_000_000), ValueDate: day(2026, 11, 20)}},
		Installments:  scheduleOf(t), ScheduleVersion: 1, Payments: payments,
	}
}

func pay(t *testing.T, id string, amount Money, on time.Time, already Allocated, schedule []Installment) Payment {
	t.Helper()
	allocations, excess := Allocate(amount, schedule, already, DefaultOrder)
	if excess != 0 {
		t.Fatalf("unexpected excess %s", excess)
	}
	return Payment{ID: id, Kind: KindPayment, Amount: amount, ValueDate: on, Reference: "R-" + id, Allocations: allocations}
}

func TestPositionBeforeAnyPaymentShowsWhatIsOwedAndOverdue(t *testing.T) {
	book := bookWith(t)
	position := book.Position(day(2027, 3, 1), 14)
	if position.NetDisbursed != Shillings(8_000_000) || position.OutstandingPrincipal != Shillings(8_000_000) {
		t.Fatalf("disbursed %s outstanding %s", position.NetDisbursed, position.OutstandingPrincipal)
	}
	if position.TotalObligation != Shillings(8_500_000) || position.TotalOutstanding != Shillings(8_500_000) {
		t.Fatalf("obligation %s outstanding %s", position.TotalObligation, position.TotalOutstanding)
	}
	if position.AmountOverdue != Shillings(2_200_000) || position.DaysPastDue != 14 {
		t.Fatalf("overdue %s days %d", position.AmountOverdue, position.DaysPastDue)
	}
	if position.Status != StatusOverdue || position.Installments[0].Status != InstallmentOverdue {
		t.Fatalf("status %s / %s", position.Status, position.Installments[0].Status)
	}
	if position.NextDue == nil || position.NextDue.Number != 1 {
		t.Fatalf("next due %+v", position.NextDue)
	}
}

func TestPartialPaymentLeavesTheInstallmentPartlyPaid(t *testing.T) {
	schedule := scheduleOf(t)
	book := bookWith(t, pay(t, "p1", Shillings(1_000_000), day(2027, 2, 10), Allocated{}, schedule))
	position := book.Position(day(2027, 2, 12), 14)
	first := position.Installments[0]
	if first.Status != InstallmentPartiallyPaid || first.Remaining != Shillings(1_200_000) {
		t.Fatalf("first %s remaining %s", first.Status, first.Remaining)
	}
	if position.Status != StatusPartiallyPaid {
		t.Fatalf("loan status %s", position.Status)
	}
	if position.PrincipalRepaid != Shillings(800_000) || position.TotalOutstanding != Shillings(7_500_000) {
		t.Fatalf("principal repaid %s outstanding %s", position.PrincipalRepaid, position.TotalOutstanding)
	}
}

func TestAReversalRestoresWhatThePaymentHadSettled(t *testing.T) {
	schedule := scheduleOf(t)
	payment := pay(t, "p1", Shillings(2_200_000), day(2027, 2, 10), Allocated{}, schedule)
	reversal := Payment{ID: "r1", Kind: KindReversal, ReversalOf: "p1", Amount: payment.Amount,
		ValueDate: day(2027, 2, 20), Allocations: payment.Allocations}
	before := bookWith(t, payment).Position(day(2027, 2, 16), 14)
	if before.Installments[0].Status != InstallmentPaid || before.AmountOverdue != 0 {
		t.Fatalf("before reversal %s overdue %s", before.Installments[0].Status, before.AmountOverdue)
	}
	after := bookWith(t, payment, reversal).Position(day(2027, 2, 21), 14)
	if after.Installments[0].Status != InstallmentOverdue || after.AmountOverdue != Shillings(2_200_000) {
		t.Fatalf("after reversal %s overdue %s", after.Installments[0].Status, after.AmountOverdue)
	}
	if after.TotalVerifiedRepayments != 0 {
		t.Fatalf("net repayments %s", after.TotalVerifiedRepayments)
	}
}

func TestAPositionOnlyCountsPaymentsUpToItsDate(t *testing.T) {
	schedule := scheduleOf(t)
	book := bookWith(t, pay(t, "p1", Shillings(2_200_000), day(2027, 3, 10), Allocated{}, schedule))
	if got := book.Position(day(2027, 3, 1), 14).TotalVerifiedRepayments; got != 0 {
		t.Fatalf("a later payment counted early: %s", got)
	}
}

func TestEveryInstallmentPaidIsFinanciallySettled(t *testing.T) {
	schedule := scheduleOf(t)
	total := Money(0)
	for _, i := range schedule {
		total += i.Total()
	}
	book := bookWith(t, pay(t, "p1", total, day(2027, 1, 5), Allocated{}, schedule))
	position := book.Position(day(2027, 1, 6), 14)
	if position.Status != StatusSettled || position.TotalOutstanding != 0 || position.NextDue != nil {
		t.Fatalf("status %s outstanding %s next %+v", position.Status, position.TotalOutstanding, position.NextDue)
	}
	for _, i := range position.Installments {
		if i.Status != InstallmentPaid {
			t.Fatalf("installment %d is %s after an early full payment", i.Number, i.Status)
		}
	}
}

func TestNoDisbursementMeansAwaitingDisbursement(t *testing.T) {
	position := Book{}.Position(day(2027, 1, 1), 14)
	if position.Status != StatusAwaitingDisbursement || position.TotalOutstanding != 0 {
		t.Fatalf("status %s", position.Status)
	}
}

func TestAPaymentDueSoonShowsPaymentDue(t *testing.T) {
	position := bookWith(t).Position(day(2027, 2, 5), 14)
	if position.Status != StatusPaymentDue || position.Installments[0].Status != InstallmentDue {
		t.Fatalf("status %s / %s", position.Status, position.Installments[0].Status)
	}
	if position.Installments[1].Status != InstallmentUpcoming {
		t.Fatalf("second %s", position.Installments[1].Status)
	}
}

func TestTheStatementExplainsTheBalance(t *testing.T) {
	schedule := scheduleOf(t)
	book := bookWith(t, pay(t, "p1", Shillings(1_000_000), day(2027, 2, 10), Allocated{}, schedule))
	asOf := day(2027, 6, 2)
	lines := book.Statement(asOf)
	position := book.Position(asOf, 14)
	last := lines[len(lines)-1]
	// Owed today = disbursed + interest/fees fallen due - net paid.
	wantToday := Shillings(8_000_000) + Shillings(200_000) + Shillings(150_000) - Shillings(1_000_000)
	if last.Balance != wantToday || position.OwedToday != wantToday {
		t.Fatalf("closing balance %s, owed today %s, want %s", last.Balance, position.OwedToday, wantToday)
	}
	// Total outstanding = owed today + interest and fees not yet due.
	if position.TotalOutstanding != position.OwedToday+position.FutureCharges {
		t.Fatalf("outstanding %s != owed today %s + future %s", position.TotalOutstanding, position.OwedToday, position.FutureCharges)
	}
	var debits, credits Money
	for _, line := range lines {
		debits += line.Debit
		credits += line.Credit
	}
	if debits-credits != last.Balance {
		t.Fatal("the running balance does not add up")
	}
}

func TestAReversedPaymentIsNotTheLastPayment(t *testing.T) {
	schedule := scheduleOf(t)
	first := pay(t, "p1", Shillings(1_000_000), day(2027, 1, 5), Allocated{}, schedule)
	second := pay(t, "p2", Shillings(500_000), day(2027, 1, 20), bookWith(t, first).AllocatedAsOf(day(2027, 1, 6)), schedule)
	reversal := Payment{ID: "r2", Kind: KindReversal, ReversalOf: "p2", Amount: second.Amount, ValueDate: day(2027, 1, 25),
		Allocations: second.Allocations}
	before := bookWith(t, first, second).Position(day(2027, 1, 24), 14)
	if before.LastPaymentDate == nil || !before.LastPaymentDate.Equal(day(2027, 1, 20)) {
		t.Fatalf("before the reversal the last payment is %v", before.LastPaymentDate)
	}
	after := bookWith(t, first, second, reversal).Position(day(2027, 1, 26), 14)
	if after.LastPaymentDate == nil || !after.LastPaymentDate.Equal(day(2027, 1, 5)) {
		t.Fatalf("after reversing the 20 January payment the last payment is %v, want 5 January", after.LastPaymentDate)
	}
}
