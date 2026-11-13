package todosnooze

import (
	"errors"
	"strings"
	"testing"
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
		{"a long id is matched whole, not cut", "ImpactAssessment", UnsnoozeRequest{TodoID: long}, "/today/panel", long, false},
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
