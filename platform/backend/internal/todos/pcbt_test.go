package todos

import (
	"testing"
	"time"
)

func ymd(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

// A Salesforce confirmation is due three days after submission: medium
// until the day before, high from then, overdue the day after it, critical
// a week past it (_business_transformation_todos). The seed has only loans
// two days old.
func TestASalesforceConfirmationsPriorityFollowsItsAge(t *testing.T) {
	submitted := ymd(2026, 11, 1)
	tests := []struct {
		today            time.Time
		priority, status string
		linked           string
	}{
		{ymd(2026, 10, 30), "medium", "waiting_me", "MFI · Desks · 0 days old"},
		{ymd(2026, 11, 2), "medium", "waiting_me", "MFI · Desks · 1 days old"},
		{ymd(2026, 11, 3), "high", "waiting_me", "MFI · Desks · 2 days old"},
		{ymd(2026, 11, 4), "high", "waiting_me", "MFI · Desks · 3 days old"},
		{ymd(2026, 11, 5), "high", "overdue", "MFI · Desks · 4 days old"},
		{ymd(2026, 11, 11), "high", "overdue", "MFI · Desks · 10 days old"},
		{ymd(2026, 11, 12), "critical", "overdue", "MFI · Desks · 11 days old"},
	}
	for _, tt := range tests {
		got := salesforceRow("l1", "MFI", "Desks", submitted, tt.today)
		if got.Priority != tt.priority || got.StatusKey != tt.status || got.Linked != tt.linked {
			t.Errorf("%s: got %s/%s %q, want %s/%s %q", tt.today.Format("Jan 2"), got.Priority, got.StatusKey, got.Linked,
				tt.priority, tt.status, tt.linked)
		}
		if !got.Due.Equal(ymd(2026, 11, 4)) || got.ActionURL != "/loans?open=l1#loan-register-title" {
			t.Errorf("due %v, link %q", got.Due, got.ActionURL)
		}
	}
}

// learning_todos._row: the oldest item sets the due day; more than a week
// old makes the row critical and overdue. The seed's conclusions are not
// due yet.
func TestALoanConclusionRowTurnsCriticalAfterAWeek(t *testing.T) {
	today := ymd(2026, 11, 13)
	for _, tt := range []struct {
		oldest           time.Time
		priority, status string
	}{
		{ymd(2026, 11, 6), "high", "waiting_me"},
		{ymd(2026, 11, 5), "critical", "overdue"},
	} {
		got := learningRow("bt-impact-conclusions-prepare", "Prepare 2 loan impact conclusions", "Prepare Conclusions",
			[]time.Time{ymd(2026, 11, 10), tt.oldest}, today)
		if got.Priority != tt.priority || got.StatusKey != tt.status || !got.Due.Equal(tt.oldest) || got.Linked != "2 waiting" {
			t.Errorf("oldest %v: got %+v", tt.oldest, got)
		}
	}
	if got := plural(1, "loan impact conclusion"); got != "1 loan impact conclusion" {
		t.Errorf("plural: %q", got)
	}
}

// The financing gap's school count is written as f"{n:,}".
func TestThousandsIsPythonsCommaFormat(t *testing.T) {
	for n, want := range map[int]string{0: "0", 999: "999", 1000: "1,000", 21543: "21,543", 1234567: "1,234,567"} {
		if got := thousands(n); got != want {
			t.Errorf("thousands(%d) = %q, want %q", n, got, want)
		}
	}
}
