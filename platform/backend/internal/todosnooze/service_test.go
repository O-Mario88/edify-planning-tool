package todosnooze

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func person(role string) auth.Principal {
	return auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: role, Status: "active"}}
}

func TestTakesOnlyReadersTheTodayPageOpensFor(t *testing.T) {
	acting := person("CCEO")
	acting.InActingAppointment = true
	holding := person("Program Lead")
	holding.Acting = &auth.ActingAppointment{}
	mustChange := person("CCEO")
	mustChange.MustChangePassword = true
	inactive := person("CCEO")
	inactive.Status = "inactive"
	tests := []struct {
		name string
		p    auth.Principal
		want bool
	}{
		{"a CCEO", person("CCEO"), true},
		{"a Programme Lead", person("Program Lead"), true},
		{"Impact Assessment", person("ImpactAssessment"), true},
		{"the Admin", person("Admin"), true},
		{"a Project Coordinator", person("ProjectCoordinator"), true},
		{"the Country Director (the page refuses)", person("CountryDirector"), false},
		{"Business Transformation (the page refuses)", person("BusinessTransformationOfficer"), false},
		{"a partner's officer (asked per person)", person("PartnerFieldOfficer"), false},
		{"a Partner Admin (asked per person)", person("PartnerAdmin"), false},
		{"a role the rules do not know", person("Nobody"), false},
		{"no role", person(""), false},
		{"working in an acting appointment", acting, false},
		{"holding an acting appointment", holding, false},
		{"must change their password", mustChange, false},
		{"not active", inactive, false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := Takes(test.p); got != test.want {
				t.Fatalf("Takes = %v, want %v", got, test.want)
			}
		})
	}
}

func TestDecideMakesTheExistingSnooze(t *testing.T) {
	friday := time.Date(2026, 11, 13, 23, 30, 0, 0, time.UTC)
	long := strings.Repeat("é", 300)
	longID := strings.Repeat("x", 140)
	tests := []struct {
		name                  string
		r                     Request
		until, message, title string
		storedTitle, storedID string
	}{
		{"tomorrow", Request{"act-1", "tomorrow", "Visit X"}, "2026-11-14", "snoozed until Sat 14 Nov", "Visit X", "Visit X", "act-1"},
		{"next week", Request{"act-1", "next_week", "Visit X"}, "2026-11-20", "snoozed until Fri 20 Nov", "Visit X", "Visit X", "act-1"},
		{"an empty title", Request{"a", "next_week", ""}, "2026-11-20", "snoozed until Fri 20 Nov", "", "", "a"},
		{"a long title is cut by characters", Request{longID, "tomorrow", long}, "2026-11-14", "snoozed until Sat 14 Nov",
			strings.Repeat("é", 120), strings.Repeat("é", 255), strings.Repeat("x", 128)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			plan, err := Decide(person("CCEO"), test.r, friday)
			if err != nil {
				t.Fatal(err)
			}
			if got := plan.Until.Format(time.DateOnly); got != test.until {
				t.Fatalf("until %s, want %s", got, test.until)
			}
			if plan.Answer.Message != test.message || plan.Answer.Title != test.title {
				t.Fatalf("answer %+v", plan.Answer)
			}
			if plan.Title != test.storedTitle || plan.TodoID != test.storedID || plan.UserID != "u1" {
				t.Fatalf("stored %q %q %q", plan.UserID, plan.TodoID, plan.Title)
			}
			if plan.Answer.TodoID != test.r.TodoID {
				t.Fatalf("the Undo names %q, want the posted %q", plan.Answer.TodoID, test.r.TodoID)
			}
		})
	}
}

func TestDecideCrossesTheMonthAndYear(t *testing.T) {
	plan, err := Decide(person("CCEO"), Request{"a", "next_week", ""}, time.Date(2026, 12, 28, 9, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if plan.Answer.Message != "snoozed until Mon 4 Jan" || plan.Until.Format(time.DateOnly) != "2027-01-04" {
		t.Fatalf("%+v", plan.Answer)
	}
}

func TestDecideRefusesAsTheExistingSnooze(t *testing.T) {
	for _, r := range []Request{{"", "tomorrow", "t"}, {"act-1", "", "t"}, {"act-1", "someday", "t"}, {"act-1", "Tomorrow", "t"}} {
		_, err := Decide(person("CCEO"), r, time.Now())
		var refusal *Refusal
		if !errors.As(err, &refusal) || refusal.Message != "Choose when the item comes back." {
			t.Fatalf("%+v: %v", r, err)
		}
	}
}

func TestDecideHandsOn(t *testing.T) {
	if _, err := Decide(person("CountryDirector"), Request{"a", "tomorrow", ""}, time.Now()); !errors.Is(err, ErrHandOn) {
		t.Fatalf("a refused reader: %v", err)
	}
	if _, err := Decide(person("CCEO"), Request{"a\x00", "tomorrow", ""}, time.Now()); !errors.Is(err, ErrHandOn) {
		t.Fatalf("a NUL: %v", err)
	}
	// The reader is asked before the form: a refused reader with an empty
	// form meets the page's door, not the snooze's words.
	if _, err := Decide(person("CountryDirector"), Request{}, time.Now()); !errors.Is(err, ErrHandOn) {
		t.Fatalf("a refused reader with an empty form: %v", err)
	}
}

func TestRowSlugIsTheExistingRowsID(t *testing.T) {
	// The ids the existing application drew on copy A (agent38_a1.json).
	for id, want := range map[string]string{"": "today-da39a3ee5e6b", "act-cmwd2x85s004pxahkdjk8": "today-098369ff7f6e"} {
		if got := RowSlug(id); got != want {
			t.Fatalf("RowSlug(%q) = %s, want %s", id, got, want)
		}
	}
}
