package todosnooze

import (
	"errors"
	"strings"
	"testing"
	"time"
)

func TestDecideUnsnoozeMatchesTheExistingUndo(t *testing.T) {
	long := strings.Repeat("é", 140)
	tests := []struct {
		name     string
		p        string
		r        UnsnoozeRequest
		wantPath string
		wantTodo string
		handOn   bool
	}{
		{"a CCEO's undo redraws the whole panel", "CCEO", UnsnoozeRequest{TodoID: "act-1"}, "/today/panel", "act-1", false},
		{"the Me tab's field rides to the redraw", "Program Lead", UnsnoozeRequest{TodoID: "act-1", Section: "own"}, "/today/panel?today_section=own", "act-1", false},
		{"any other section value is passed as posted", "Program Lead", UnsnoozeRequest{TodoID: "x", Section: "a b&c"}, "/today/panel?today_section=a+b%26c", "x", false},
		{"an empty item still redraws (nothing matches)", "Admin", UnsnoozeRequest{}, "/today/panel", "", false},
		{"a long id is cut as its snooze stored it", "ImpactAssessment", UnsnoozeRequest{TodoID: long}, "/today/panel", cut(long, rules.Lengths.TodoID), false},
		{"the Country Director: the page refuses", "CountryDirector", UnsnoozeRequest{TodoID: "act-1"}, "", "", true},
		{"a partner's officer: asked per person", "PartnerFieldOfficer", UnsnoozeRequest{TodoID: "act-1"}, "", "", true},
		{"a NUL in the id: the existing undo fails", "CCEO", UnsnoozeRequest{TodoID: "a\x00b"}, "", "", true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			plan, err := DecideUnsnooze(person(test.p), test.r)
			if test.handOn {
				if !errors.Is(err, ErrHandOn) {
					t.Fatalf("err = %v, want ErrHandOn", err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if plan.UserID != "u1" || plan.TodoID != test.wantTodo {
				t.Fatalf("plan = %+v", plan)
			}
			want := Redraw{Path: test.wantPath, Retarget: "[data-dashboard-today]", Reswap: "outerHTML"}
			if plan.Redraw != want {
				t.Fatalf("redraw = %+v, want %+v", plan.Redraw, want)
			}
		})
	}
}

// The existing Snooze stores a To-Do id cut to its column (128 characters)
// while its Undo matches the whole posted id, so a long id can be snoozed but
// never undone. Go's undo matches the id the snooze stored (owner,
// 2026-11-13: "Can you fix those from the go side"; intended.json
// go-fix-snooze-id-length).
func TestUndoMatchesTheIdASnoozeStored(t *testing.T) {
	long := strings.Repeat("x", 200)
	snooze, err := Decide(person("CCEO"), Request{TodoID: long, Choice: "next_week"}, time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	undo, err := DecideUnsnooze(person("CCEO"), UnsnoozeRequest{TodoID: long})
	if err != nil {
		t.Fatal(err)
	}
	if undo.TodoID != snooze.TodoID || len([]rune(undo.TodoID)) != rules.Lengths.TodoID {
		t.Fatalf("undo matches %d characters, the snooze stored %d", len(undo.TodoID), len(snooze.TodoID))
	}
}
