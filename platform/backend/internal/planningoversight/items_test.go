package planningoversight

import (
	"slices"
	"testing"
	"time"
)

func day(s string) *time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return &t
}

// page_table: a Training Follow Up is a visit, an in-school training a
// training, a cluster meeting a meeting, a Core school's visit a core visit.
func TestPageTableFilesEachItemWhereThePageDoes(t *testing.T) {
	cases := []struct {
		name string
		it   item
		want int
	}{
		{"a school visit", item{activityType: "school_visit", training: "—"}, clientVisits},
		{"a follow-up visit naming its course", item{activityType: "training_follow_up_visit", training: "—"}, clientVisits},
		{"a core school's visit", item{activityType: "school_visit", schoolType: "core", training: "—"}, coreVisits},
		{"a core-trained school's visit", item{activityType: "school_visit", schoolType: "core_trained", training: "—"}, clientVisits},
		{"an in-school training", item{activityType: "school_visit", inSchool: true, training: "Phonics"}, plannedTrainings},
		{"a cluster training", item{activityType: "cluster_training", training: "Cluster Training"}, plannedTrainings},
		{"a cluster meeting", item{activityType: "cluster_meeting", training: "—"}, clusterMeetings},
		{"a meeting taught from a course", item{activityType: "cluster_meeting", training: "Leadership"}, plannedTrainings},
	}
	for _, tc := range cases {
		if got := pageTable(&tc.it); got != tc.want {
			t.Errorf("%s: table %d, want %d", tc.name, got, tc.want)
		}
	}
}

func TestHasRiskReadsEachDetector(t *testing.T) {
	today := *day("2026-11-25")
	priced := func(a act, status string, planned *time.Time) *item {
		return &item{a: &a, status: status, plannedDate: planned, plannedCost: 1000}
	}
	cases := []struct {
		name string
		it   *item
		want bool
	}{
		{"priced work still ahead", priced(act{}, "scheduled", day("2026-12-01")), false},
		{"no cost line", &item{a: &act{}, status: "scheduled", plannedDate: day("2026-12-01")}, true},
		{"the free half of a live pair", &item{a: &act{}, status: "scheduled", plannedDate: day("2026-12-01"), costOnVisit: true}, false},
		{"marked cost missing", priced(act{costMissing: true}, "scheduled", day("2026-12-01")), true},
		{"past its day and not delivered", priced(act{}, "scheduled", day("2026-11-24")), true},
		{"past its day, with the PL", priced(act{}, "submitted_to_pl", day("2026-11-24")), false},
		{"past its day, completed", priced(act{}, "completed", day("2026-11-01")), false},
		{"started, no evidence after the grace", priced(act{}, "in_progress", day("2026-11-21")), true},
		{"waiting on its Salesforce ID", priced(act{}, "salesforce_id_required", day("2026-12-01")), true},
		{"returned by IA", priced(act{ia: "returned"}, "returned_by_ia", day("2026-12-01")), true},
		{"rescheduled three times", priced(act{reschedules: 3}, "scheduled", day("2026-12-01")), true},
		{"rescheduled twice", priced(act{reschedules: 2}, "scheduled", day("2026-12-01")), false},
	}
	for _, tc := range cases {
		if got := hasRisk(tc.it, today); got != tc.want {
			t.Errorf("%s: risky %v, want %v", tc.name, got, tc.want)
		}
	}
	// Six days in the IA queue (five allowed) and unverified.
	sub := time.Date(2026, 11, 19, 8, 0, 0, 0, time.UTC)
	queued := priced(act{ia: "pending"}, "awaiting_ia_verification", day("2026-12-01"))
	queued.submittedToIA = &sub
	if !hasRisk(queued, today) {
		t.Error("six days in the IA queue: no risk")
	}
	// Verified and unpaid fifteen days past its day (fourteen allowed).
	unpaid := priced(act{ia: "confirmed"}, "ia_verified", day("2026-11-10"))
	if !hasRisk(unpaid, today) {
		t.Error("verified and unpaid past the window: no risk")
	}
}

func TestCompletionColumnsReadTheSalesforceIDAlone(t *testing.T) {
	today := *day("2026-11-25")
	done := &item{a: &act{salesforce: " SV-1 ", plannedDate: day("2026-11-20"), actualDelivery: day("2026-11-18")},
		status: "completed", plannedDate: day("2026-11-20")}
	annotateCompletion(done, today)
	if done.salesforceID != "SV-1" || !done.isComplete || done.gap != "" || !done.finishedEarly || done.rowState != "done" || !done.showsComplete {
		t.Errorf("complete and early: %+v", done)
	}
	missing := &item{a: &act{plannedDate: day("2026-11-20")}, status: "submitted_to_pl", plannedDate: day("2026-11-20")}
	annotateCompletion(missing, today)
	if missing.gap != "Missing Salesforce ID" || missing.isComplete || missing.showsComplete {
		t.Errorf("done without its ID: %+v", missing)
	}
	late := &item{a: &act{}, status: "scheduled", plannedDate: day("2026-11-24")}
	annotateCompletion(late, today)
	if late.rowState != "overdue" {
		t.Errorf("past its day: row %q", late.rowState)
	}
	returned := &item{a: &act{}, status: "returned_by_pl", plannedDate: day("2026-11-24")}
	annotateCompletion(returned, today)
	if returned.rowState != "" {
		t.Errorf("returned: row %q", returned.rowState)
	}
}

func TestNumbersReadAsThePageWritesThem(t *testing.T) {
	for n, want := range map[int64]string{0: "0", 999: "999", 2256000: "2,256,000", -1500: "-1,500"} {
		if got := intcomma(n); got != want {
			t.Errorf("intcomma(%d) = %q, want %q", n, got, want)
		}
	}
	for _, c := range []struct {
		n, d int
		want string
	}{{10, 23, "43.5%"}, {1, 2, "50%"}, {4, 3, "133.3%"}, {0, 7, "0%"}} {
		if got := percent(c.n, c.d); got != c.want {
			t.Errorf("percent(%d, %d) = %q, want %q", c.n, c.d, got, c.want)
		}
	}
	if got := pyTitle("in school training"); got != "In School Training" {
		t.Errorf("pyTitle = %q", got)
	}
	if got := floorDiv(7, 2); got != 3 {
		t.Errorf("floorDiv = %d", got)
	}
	if got := plural(1, "school", "schools") + " · " + plural(2, "staff member", "staff members"); got != "1 school · 2 staff members" {
		t.Errorf("plural = %q", got)
	}
}

func TestPageWindowIsTheSharedPagersWindow(t *testing.T) {
	cases := []struct {
		current, pages int
		want           []int
	}{
		{1, 2, []int{1, 2}},
		{1, 9, []int{1, 2, 0, 9}},
		{5, 9, []int{1, 0, 4, 5, 6, 0, 9}},
		{9, 9, []int{1, 0, 8, 9}},
	}
	for _, c := range cases {
		if got := pageWindow(c.current, c.pages); !slices.Equal(got, c.want) {
			t.Errorf("pageWindow(%d, %d) = %v, want %v", c.current, c.pages, got, c.want)
		}
	}
}

// risksFor names a risk exactly where hasRisk finds one, and words each as
// risk_service does, worst first.
func TestRisksForAgreeWithHasRiskAndReadAsTheDetectors(t *testing.T) {
	today := *day("2026-11-25")
	sub := time.Date(2026, 11, 19, 8, 0, 0, 0, time.UTC)
	items := []*item{}
	for _, status := range []string{"scheduled", "submitted_to_pl", "completed", "in_progress", "salesforce_id_required", "returned_by_ia", "awaiting_ia_verification", "ia_verified"} {
		for _, planned := range []*time.Time{nil, day("2026-12-01"), day("2026-11-24"), day("2026-11-01")} {
			for _, a := range []act{{}, {costMissing: true}, {ia: "returned"}, {reschedules: 3}, {ia: "confirmed"}, {ia: "pending"}} {
				for _, cost := range []int64{0, 1000} {
					a := a
					it := &item{a: &a, status: status, plannedDate: planned, plannedCost: cost, ownerName: "Paul N."}
					items = append(items, it)
					queued := *it
					queued.submittedToIA = &sub
					items = append(items, &queued)
				}
			}
		}
	}
	for i, it := range items {
		if got, want := len(risksFor(it, today)) > 0, hasRisk(it, today); got != want {
			t.Fatalf("item %d (%s, %v): risks %v, hasRisk %v", i, it.status, it.plannedDate, got, want)
		}
	}
	overdue := &item{a: &act{costMissing: true}, status: "scheduled", plannedDate: day("2026-11-01"), ownerName: "Paul N."}
	got := risksFor(overdue, today)
	if len(got) != 2 || got[0].key != "scheduled_without_cost" || got[1].key != "activity_overdue" ||
		got[1].reason != "Planned for 1 Nov and still not completed (24 days)." || got[1].severity != "critical" || got[0].owner != "Paul N." {
		t.Fatalf("the overdue unpriced item: %+v", got)
	}
}
