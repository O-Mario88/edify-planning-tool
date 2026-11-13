package activities

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The group's words are the existing application's, letter for letter: each
// is found in the Python that says it.
func TestTheGroupWordsAreTheExistingApplications(t *testing.T) {
	sources := map[string]string{}
	for _, path := range []string{"apps/activities/group_actions.py", "apps/frontend/views/activity_group_views.py",
		"templates/partials/my_plan/group_outcome.html"} {
		raw, err := os.ReadFile(filepath.FromSlash("../../../../" + path))
		if err != nil {
			t.Fatal(err)
		}
		sources[path] = string(raw)
	}
	actions, view := sources["apps/activities/group_actions.py"], sources["apps/frontend/views/activity_group_views.py"]
	for _, c := range []struct{ words, in string }{
		{fmt.Sprintf("MAX_SELECTION = %d", maxGroupSelection), actions},
		{`"` + groupChooseDate + `"`, actions},
		{`"` + groupMoveReason + `"`, actions},
		{`"` + groupCancelReason + `"`, actions},
		{`"` + groupAlreadyOnDay + `"`, actions},
		{`"` + groupAlreadyOff + `"`, actions},
		{`"` + groupProgrammeWork + `"`, actions},
		{`limit: int = ` + fmt.Sprint(groupNamesShown), view},
		{`verb="` + groupMovedVerb + `"`, view},
		{`verb="` + groupCancelledVerb + `"`, view},
		{`"` + groupMoveAuditName + `"`, view},
		{`"` + groupCancelAuditName + `"`, view},
		{`f"{p.title} at {p.where} ({p.refusal.rstrip('.')})"`, view},
		{`f"{shown} and {more} more"`, view},
		{`f" Not {verb}: {_names(outcome.refused)}."`, view},
		{`moved to "`, view},
		{`{date.fromisoformat(day):%-d %B %Y}.`, view},
		{`f"{count} activit{'y' if count == 1 else 'ies'} cancelled."`, view},
		{`Nothing was {{ verb }}.`, sources["templates/partials/my_plan/group_outcome.html"]},
		{`<strong>{{ pick.title }} · {{ pick.where }}</strong>: {{ pick.refusal }}`, sources["templates/partials/my_plan/group_outcome.html"]},
	} {
		if !strings.Contains(c.in, c.words) {
			t.Errorf("%q is not in the existing application's source", c.words)
		}
	}
}

// clean_ids: once each, in the order ticked; no tick or more than a group
// takes is handed on (the existing application says why).
func TestTheTickedIdsAreCleanedAsTheGroupCleansThem(t *testing.T) {
	ids, err := groupIDs([]string{" a ", "b", "a", "", "c"})
	if err != nil || !slices.Equal(ids, []string{"a", "b", "c"}) {
		t.Fatalf("groupIDs = %v, %v", ids, err)
	}
	many := make([]string, maxGroupSelection+1)
	for i := range many {
		many[i] = fmt.Sprint("id", i)
	}
	for name, raw := range map[string][]string{"none": nil, "blank": {" "}, "too many": many} {
		if _, err := groupIDs(raw); !errors.Is(err, ErrHandOn) {
			t.Errorf("%s: %v, want a hand-on", name, err)
		}
	}
	if ids, err := groupIDs(many[:maxGroupSelection]); err != nil || len(ids) != maxGroupSelection {
		t.Errorf("a full group: %d, %v", len(ids), err)
	}
}

// A person in an acting seat, with no staff profile, or a group with no
// tick is handed on before anything is read (the service has no database).
func TestTheGroupIsHandedOnBeforeAnyRead(t *testing.T) {
	s, err := NewService(nil, nil, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	for name, c := range map[string]struct {
		p   auth.Principal
		ids []string
	}{
		"acting":           {auth.Principal{Account: auth.Account{StaffProfileID: "s", InActingAppointment: true}}, []string{"a"}},
		"no staff profile": {auth.Principal{Account: auth.Account{}}, []string{"a"}},
		"no tick":          {auth.Principal{Account: auth.Account{StaffProfileID: "s"}}, nil},
	} {
		req := GroupRequest{ActivityIDs: c.ids, Date: "", Reason: ""}
		if _, err := s.GroupReschedule(ctx, c.p, req, Origin{}); !errors.Is(err, ErrHandOn) {
			t.Errorf("reschedule, %s: %v, want a hand-on", name, err)
		}
		if _, err := s.GroupCancel(ctx, c.p, req, Origin{}); !errors.Is(err, ErrHandOn) {
			t.Errorf("cancel, %s: %v, want a hand-on", name, err)
		}
	}
}

func pick(id, title, where string, day string) groupPick {
	d, _ := time.Parse(time.DateOnly, day)
	return groupPick{GroupPick: GroupPick{ActivityID: id, Title: title, Where: where, Day: d}}
}

type fakeGroupPricing struct {
	verdict GroupVerdict
	asked   []GroupQuestion
}

func (f *fakeGroupPricing) DayCheck(context.Context, map[string]any) (DayVerdict, error) {
	return DayVerdict{}, nil
}
func (f *fakeGroupPricing) Settle(context.Context, []int64, string) error { return nil }
func (f *fakeGroupPricing) GroupCheck(_ context.Context, q GroupQuestion) (GroupVerdict, error) {
	f.asked = append(f.asked, q)
	return f.verdict, nil
}

// The group check puts the picks in `selection`'s order, and Go takes its
// answer only where Go's own reading agrees with it: the same activities,
// the ones Go has already left left in the same words, and a group changed
// one at a time only because its pricing refused.
func TestTheGroupCheckOrdersThePicksAndMustAgreeWithGo(t *testing.T) {
	picks := func() []groupPick {
		left := pick("b", "T", "W", "2026-11-17")
		left.Refusal = groupAlreadyOnDay
		return []groupPick{pick("a", "T", "W", "2026-11-18"), left, pick("c", "T", "W", "2026-11-16")}
	}
	agreeing := GroupVerdict{Together: true, Picks: []VerdictPick{
		{ID: "c", Done: true}, {ID: "b", Refusal: groupAlreadyOnDay}, {ID: "a", Done: true}}}
	pricing := &fakeGroupPricing{verdict: agreeing}
	s := &Service{pricing: pricing}
	got := picks()
	door, verdict, err := s.askGroup(context.Background(), GroupQuestion{Kind: "reschedule", ActivityIDs: []string{"a", "b", "c"}}, got, 2)
	if err != nil || !verdict.Together || len(door) != 3 {
		t.Fatalf("askGroup: %v %+v", err, verdict)
	}
	order := []string{}
	for _, p := range got {
		order = append(order, p.ActivityID)
	}
	if !slices.Equal(order, []string{"c", "b", "a"}) || len(pricing.asked) != 1 {
		t.Fatalf("order %v, asked %v", order, pricing.asked)
	}
	for name, verdict := range map[string]GroupVerdict{
		"the group refused":     {Refusal: groupMoveReason},
		"another activity":      {Together: true, Picks: []VerdictPick{{ID: "c", Done: true}, {ID: "b", Refusal: groupAlreadyOnDay}, {ID: "z", Done: true}}},
		"a pick Go left, moved": {Together: true, Picks: []VerdictPick{{ID: "c", Done: true}, {ID: "b", Done: true}, {ID: "a", Done: true}}},
		"left in other words":   {Together: true, Picks: []VerdictPick{{ID: "c", Done: true}, {ID: "b", Refusal: "x"}, {ID: "a", Done: true}}},
		"apart with no reason":  {Picks: agreeing.Picks},
	} {
		s := &Service{pricing: &fakeGroupPricing{verdict: verdict}}
		if _, _, err := s.askGroup(context.Background(), GroupQuestion{}, picks(), 2); !errors.Is(err, ErrHandOn) {
			t.Errorf("%s: %v, want a hand-on", name, err)
		}
	}
	// Changed one at a time because its pricing refused: taken.
	apart := GroupVerdict{GroupRefusal: "The accountant holds Monday.", Picks: agreeing.Picks}
	s = &Service{pricing: &fakeGroupPricing{verdict: apart}}
	if _, v, err := s.askGroup(context.Background(), GroupQuestion{}, picks(), 2); err != nil || v.Together {
		t.Fatalf("one at a time: %v %+v", err, v)
	}
}

// A day asked for again moves to the end (`_price_when_the_save_ends`); a
// week or a month asked for again stays where it was first asked.
func TestTheGroupKeepsItsDaysInTheOrderLastAsked(t *testing.T) {
	k := &keptCosts{}
	for _, d := range [][2]string{{"d17", "u"}, {"d19", "u"}, {"d18", "u"}, {"d19", "u"}, {"d18", "u"}, {"d19", "u"}} {
		k.day(d[0], d[1])
	}
	if fmt.Sprint(k.days) != "[[d17 u] [d18 u] [d19 u]]" {
		t.Fatalf("days %v", k.days)
	}
	k.week([]string{"u", "2026-11-16"})
	k.week([]string{"u", "2026-11-23"})
	k.week([]string{"u", "2026-11-16"})
	k.month([]any{"u", "2027", 11})
	k.month([]any{"u", "2027", 11})
	if fmt.Sprint(k.weeks) != "[[u 2026-11-16] [u 2026-11-23]]" || len(k.months) != 1 {
		t.Fatalf("weeks %v months %v", k.weeks, k.months)
	}
	if (&keptCosts{}).empty() != true || k.empty() {
		t.Fatal("empty")
	}
}

// ledger_sync's one callback a transaction: a savepoint rolled back takes it
// when it was put there inside it, and keeps a later pick's years otherwise.
func TestTheGroupsLedgerMarksFollowTheSavepoints(t *testing.T) {
	d := func(s string) time.Time { v, _ := time.Parse(time.DateOnly, s); return v }
	first := groupMarks{}
	first.undone(d("2026-11-17"))
	first.kept(d("2026-11-18"))
	first.undone(d("2027-10-05"))
	if fmt.Sprint(len(first.days)) != "2" || !first.days[1].Equal(d("2027-10-05")) {
		t.Fatalf("marks %v", first.days)
	}
	none := groupMarks{}
	none.undone(d("2026-11-17"))
	none.undone(d("2026-11-18"))
	if len(none.days) != 0 {
		t.Fatalf("marks %v, want none: every savepoint rolled back", none.days)
	}
}

// _finish's words: the count, the date, the picks left (three named, then
// how many more, each reason without its last full stop), and the outcome
// partial's words when nothing changed.
func TestTheGroupAnswersInTheViewsWords(t *testing.T) {
	left := func(n int) []GroupPick {
		out := []GroupPick{}
		for i := range n {
			out = append(out, GroupPick{Title: fmt.Sprint("T", i), Where: "W", Refusal: "Already on this date."})
		}
		return out
	}
	a := GroupAnswer{Done: []GroupPick{{}}, Refused: left(5), Message: "1 activity moved to 25 November 2026."}
	finishAnswer(&a, groupMovedVerb)
	want := "1 activity moved to 25 November 2026. Not moved: T0 at W (Already on this date); T1 at W (Already on this date); " +
		"T2 at W (Already on this date) and 2 more."
	if a.Message != want {
		t.Fatalf("message %q\nwant    %q", a.Message, want)
	}
	b := GroupAnswer{Done: []GroupPick{}, Refused: left(2), Message: "0 activities cancelled."}
	finishAnswer(&b, groupCancelledVerb)
	if b.Message != "" || b.Outcome != "Nothing was cancelled. T0 · W: Already on this date. T1 · W: Already on this date." {
		t.Fatalf("outcome %+v", b)
	}
	if activityWord(1) != "activity" || activityWord(2) != "activities" || activityWord(0) != "activities" {
		t.Fatal("pluralize")
	}
	if names := groupNames([]GroupPick{{Title: "T", Where: "W", Refusal: "Gone..."}}); names != "T at W (Gone)" {
		t.Fatalf("rstrip: %q", names)
	}
}
