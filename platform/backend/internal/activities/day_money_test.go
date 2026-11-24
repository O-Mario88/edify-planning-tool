package activities

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"testing"
	"time"
)

// vendor_channel._school_transport: the provider is owed the shares of the
// members at a school. Another member's share enters its staff request, so
// invoicing the whole pool would pay it twice.
func TestTheTransportCompanyIsOwedTheSchoolShares(t *testing.T) {
	pool := map[string]int64{"primary_transport_per_day": 50000, "lunch_per_day": 12000}
	tests := []struct {
		name    string
		schools []bool
		want    int64
	}{
		{"one school", []bool{true}, 50000},
		{"every member at a school", []bool{true, true, true}, 50000},
		{"one member with no school", []bool{true, false}, 25000},
		{"no member at a school", []bool{false}, 0},
		{"an empty day", nil, 0},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := schoolTransportAmount(pool, tt.schools); got != tt.want {
				t.Fatalf("got %d, want %d", got, tt.want)
			}
		})
	}
}

func TestEveryTransportKeyCountsTowardTheProvider(t *testing.T) {
	pool := map[string]int64{"secondary_transport_per_day": 70000, "airport_transport": 30000, "dinner": 9000}
	if got := schoolTransportAmount(pool, []bool{true}); got != 100000 {
		t.Fatalf("got %d", got)
	}
}

// NON_FUNDABLE_ACTIVITY_STATUSES: a visit waiting for its owner's approval
// draws no money and takes no share of a day.
func TestTheDaySharesNothingWithWorkThatDrawsNoMoney(t *testing.T) {
	want := []string{"awaiting_owner_approval", "cancelled", "deferred", "rejected"}
	got := slices.Sorted(slices.Values(nonFundableStatuses))
	if !slices.Equal(got, want) {
		t.Fatalf("got %v", got)
	}
}

func dayMoneySQL(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.FromSlash("../../../deploy/db/day_money_roles.sql"))
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func namedIn(t *testing.T, sql, list string) []string {
	t.Helper()
	block := regexp.MustCompile(`(?s)` + list + `\(\) RETURNS varchar\[\].*?ARRAY\[(.*?)\]::varchar\[\]`).FindStringSubmatch(sql)
	if block == nil {
		t.Fatalf("the list %s was not found", list)
	}
	named := []string{}
	for _, m := range regexp.MustCompile(`'([a-z_]+)'`).FindAllStringSubmatch(block[1], -1) {
		named = append(named, m[1])
	}
	slices.Sort(named)
	return named
}

func TestTheMoneyFunctionsNameTheExistingStatuses(t *testing.T) {
	sql := dayMoneySQL(t)
	moved := slices.Sorted(slices.Values(rules.Cancel.MoneyMovedAdvanceStatuses))
	if len(moved) == 0 || !slices.Equal(namedIn(t, sql, "money_moved"), moved) {
		t.Fatalf("money moved names %v, want %v", namedIn(t, sql, "money_moved"), moved)
	}
	requestable := slices.Sorted(slices.Values(append(slices.Clone(moved),
		"self_funded_pending_reimbursement", "not_requested", "cancelled")))
	if !slices.Equal(namedIn(t, sql, "not_requestable"), requestable) {
		t.Fatalf("not requestable names %v, want %v", namedIn(t, sql, "not_requestable"), requestable)
	}
	fundable := slices.Sorted(slices.Values(nonFundableStatuses))
	if !slices.Equal(namedIn(t, sql, "not_fundable"), fundable) {
		t.Fatalf("not fundable names %v, want %v", namedIn(t, sql, "not_fundable"), fundable)
	}
	weekly := slices.Sorted(slices.Values(rebuildableWeeklyStatuses))
	if !slices.Equal(namedIn(t, sql, "week_rebuildable"), weekly) {
		t.Fatalf("rebuildable names %v, want %v", namedIn(t, sql, "week_rebuildable"), weekly)
	}
}

func TestAFollowRowNamesTheWeeksAndMonthsItRefiles(t *testing.T) {
	var steps costsFollowSteps
	raw := `{"days":[["b1","u1"]],"together":false,
	  "weeks":[["u1","2026-12-07"],["","2026-12-14"]],
	  "months":[["u1","2027",12],["u2","2027","1"],["","2027",2]]}`
	if err := json.Unmarshal([]byte(raw), &steps); err != nil {
		t.Fatal(err)
	}
	money := newDayMoney()
	if err := money.addSteps(steps); err != nil {
		t.Fatal(err)
	}
	if got := money.sortedWeeks(); len(got) != 1 || got[0].owner != "u1" || got[0].start.Format(time.DateOnly) != "2026-12-07" {
		t.Fatalf("weeks %+v", got)
	}
	got := money.sortedMonths()
	if len(got) != 2 || got[0] != (monthBucket{"u1", "2027", 12}) || got[1] != (monthBucket{"u2", "2027", 1}) {
		t.Fatalf("months %+v", got)
	}
}

func TestAFollowRowWithAnUnreadableWeekIsNotSettled(t *testing.T) {
	steps := costsFollowSteps{Weeks: [][]string{{"u1", "someday"}}}
	if err := newDayMoney().addSteps(steps); err == nil {
		t.Fatal("a week that is no date must fail the row")
	}
}

// LeaveBudgetImpactService.handle_reschedule: the trail a move leaves on its
// budget lines, by the ISO weeks of the two dates as the row wrote them.
func TestAMoveLeavesItsTrailOnTheLines(t *testing.T) {
	trail, write, err := followNote{Kind: "reschedule_note", Activity: "a1", Old: "2026-12-16T00:00:00+03:00",
		New: "2027-01-05T00:00:00+03:00", Reason: "the school asked"}.trail()
	if err != nil || !write {
		t.Fatalf("write %v, %v", write, err)
	}
	if want := " [Audit: Rescheduled due to the school asked. Old period: Week 51, New period: Week 1]"; trail != want {
		t.Fatalf("got %q", trail)
	}
}

func TestAMoveToTheSameMomentLeavesNoTrail(t *testing.T) {
	_, write, err := followNote{Kind: "reschedule_note", Old: "2026-12-16T00:00:00+03:00",
		New: "2026-12-15T21:00:00+00:00", Reason: "x"}.trail()
	if err != nil || write {
		t.Fatalf("write %v, %v", write, err)
	}
}

func TestAFollowNoteOfAnUnknownKindFailsTheRow(t *testing.T) {
	if _, _, err := (followNote{Kind: "something_else"}).trail(); err == nil {
		t.Fatal("an unknown note must fail the row")
	}
}

// plan_changes._tell_monthly: the words a monthly request's people read when
// the plan under it moved its total.
func TestAFollowedMonthSaysWhatMovedIt(t *testing.T) {
	got := monthFollowedBody("Core Visit at Mpatta", "2027-M12", 1234567, 17714)
	want := "Core Visit at Mpatta changed, so the December FY 2027 request now totals UGX 1,234,567 (it was UGX 17,714). " +
		"It stays where it is; nothing needs sending again."
	if got != want {
		t.Fatalf("got %q", got)
	}
}

func TestAMonthThatIsNoMonthIsNamedByItsKey(t *testing.T) {
	if got := monthLabel("2027-Q1"); got != "2027-Q1" {
		t.Fatalf("got %q", got)
	}
	if got := monthLabel(""); got != "the month" {
		t.Fatalf("got %q", got)
	}
}

func TestShillingsAreGroupedInThousands(t *testing.T) {
	for amount, want := range map[int64]string{0: "0", 999: "999", 1000: "1,000", 62000: "62,000", 1234567: "1,234,567", -4500: "-4,500"} {
		if got := groupThousands(amount); got != want {
			t.Fatalf("%d = %q, want %q", amount, got, want)
		}
	}
}

// Its preparer is always told; whoever approved it is told too.
func TestAFollowedMonthTellsItsPreparerAndItsApprover(t *testing.T) {
	tests := []struct {
		status string
		want   []string
	}{
		{"submitted_to_pl", []string{"u1"}},
		{"approved_by_pl", []string{"u1", "pl"}},
		{"approved_by_cd", []string{"u1", "pl"}},
		{"approved_by_rvp", []string{"u1", "pl"}},
	}
	for _, tt := range tests {
		t.Run(tt.status, func(t *testing.T) {
			if got := monthFollowedRecipients(tt.status, "u1", "pl"); !slices.Equal(got, tt.want) {
				t.Fatalf("got %v", got)
			}
		})
	}
	if got := monthFollowedRecipients("approved_by_pl", "u1", ""); !slices.Equal(got, []string{"u1"}) {
		t.Fatalf("an approver that is nobody is not told: %v", got)
	}
}

func TestAFollowedMonthLinksByRole(t *testing.T) {
	for role, want := range map[string][2]string{
		"CountryDirector": {"/budget", "View Team Request"},
		"Admin":           {"/budget", "View Team Request"},
		"Program Lead":    {"/accounts/monthly-request", "View Monthly Request"},
		"":                {"/accounts/monthly-request", "View Monthly Request"},
	} {
		route, label := monthFollowedLink(role)
		if route != want[0] || label != want[1] {
			t.Fatalf("%q = %s, %s", role, route, label)
		}
	}
}

func TestAPlannersChangeIsReadFromTheRow(t *testing.T) {
	var steps costsFollowSteps
	if err := json.Unmarshal([]byte(`{"days":[],"change":"Core Visit at Mpatta"}`), &steps); err != nil {
		t.Fatal(err)
	}
	money := newDayMoney()
	if err := money.addSteps(steps); err != nil {
		t.Fatal(err)
	}
	if !money.planChange || money.change != "Core Visit at Mpatta" {
		t.Fatalf("got %v %q", money.planChange, money.change)
	}
	plain := newDayMoney()
	if err := plain.addSteps(costsFollowSteps{}); err != nil || plain.planChange {
		t.Fatal("a row with no change is no planner's change")
	}
}

// The total before is the first one seen: the change may touch a request
// from more than one of its activities.
func TestAFollowedMonthKeepsItsFirstTotal(t *testing.T) {
	money := newDayMoney()
	money.follow("f1", 100)
	money.follow("f2", 50)
	money.follow("f1", 300)
	if len(money.followed) != 2 || money.followed[0] != (followedMonth{"f1", 100}) || money.followed[1] != (followedMonth{"f2", 50}) {
		t.Fatalf("got %+v", money.followed)
	}
}

// generate_weekly_fund_request: a request is filed under its Monday, and two
// days of one week are one rebuild.
func TestADaysWeekIsItsMonday(t *testing.T) {
	money := newDayMoney()
	money.addWeek("u1", time.Date(2026, 12, 3, 0, 0, 0, 0, time.UTC))
	money.addWeek("u1", time.Date(2026, 12, 6, 0, 0, 0, 0, time.UTC))
	money.addWeek("", time.Date(2026, 12, 6, 0, 0, 0, 0, time.UTC))
	got := money.sortedWeeks()
	if len(got) != 1 || got[0].start.Format(time.DateOnly) != "2026-11-30" {
		t.Fatalf("weeks %+v", got)
	}
}
