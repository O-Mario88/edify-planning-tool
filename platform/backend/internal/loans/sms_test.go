package loans

import (
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

func reminderBook(t *testing.T, paid ledger.Money) ledger.Book {
	t.Helper()
	rate, _ := ledger.ParseRate("2")
	schedule, err := ledger.BuildSchedule(ledger.Terms{Principal: ledger.Shillings(4_000_000), Rate: rate, Method: ledger.MethodFlat,
		DueDates: []time.Time{ledger.Date(2027, 2, 15), ledger.Date(2027, 6, 1)}})
	if err != nil {
		t.Fatal(err)
	}
	schedule[0].ID, schedule[1].ID = "i1", "i2"
	book := ledger.Book{Disbursements: []ledger.Disbursement{{ID: "d", Amount: ledger.Shillings(4_000_000), ValueDate: ledger.Date(2026, 12, 1)}},
		Installments: schedule, ScheduleVersion: 1}
	if paid > 0 {
		allocations, _ := ledger.Allocate(paid, schedule, ledger.Allocated{}, ledger.DefaultOrder)
		book.Payments = []ledger.Payment{{ID: "p", Kind: ledger.KindPayment, Amount: paid, ValueDate: ledger.Date(2027, 1, 5), Allocations: allocations}}
	}
	return book
}

func TestRemindersFollowThePolicy(t *testing.T) {
	week := "2027-W06"
	// Due within a week: an upcoming reminder for that installment.
	kind, key, due := ReminderFor(reminderBook(t, 0).Position(ledger.Date(2027, 2, 10), 14), week, "app")
	if kind != SMSUpcoming || due.ID != "i1" || !strings.Contains(key, "i1") || !strings.Contains(key, week) {
		t.Fatalf("upcoming: %s %s", kind, key)
	}
	// Due in more than a week: nothing yet.
	if kind, _, _ := ReminderFor(reminderBook(t, 0).Position(ledger.Date(2027, 1, 20), 14), week, "app"); kind != "" {
		t.Fatalf("a reminder %s was due too early", kind)
	}
	// Overdue: an overdue reminder, once a week.
	kind, key, _ = ReminderFor(reminderBook(t, 0).Position(ledger.Date(2027, 3, 1), 14), week, "app")
	if kind != SMSOverdue || key != "overdue:app:"+week {
		t.Fatalf("overdue: %s %s", kind, key)
	}
	// Paid in full: never.
	settled := reminderBook(t, ledger.Shillings(4_160_000)).Position(ledger.Date(2027, 2, 10), 14)
	if kind, _, _ := ReminderFor(settled, week, "app"); kind != "" || settled.Status != ledger.StatusSettled {
		t.Fatalf("a settled loan was reminded (%s, %s)", kind, settled.Status)
	}
	// The first installment paid: the reminder moves to the next one.
	kind, _, due = ReminderFor(reminderBook(t, ledger.Shillings(2_080_000)).Position(ledger.Date(2027, 5, 28), 14), week, "app")
	if kind != SMSUpcoming || due.ID != "i2" {
		t.Fatalf("after paying the first: %s %+v", kind, due)
	}
}
