package extrawork

import (
	"errors"
	"testing"
)

// _get_for: who may take each action, in its words.
func TestOnlyTheRightPersonTakesEachAction(t *testing.T) {
	a := assignmentRow{assigner: "pl", assignee: "cc", reviewer: "pl"}
	for _, tt := range []struct{ user, action, want string }{
		{"pl", "start", "This assignment is not yours."},
		{"cc", "verify", "You are not the reviewer of this assignment."},
		{"cc", "cancel", "You did not assign this work."},
		{"cc", "submit", ""}, {"pl", "return", ""}, {"pl", "cancel", ""},
	} {
		err := a.gate(tt.user, tt.action)
		var r *Refusal
		if tt.want == "" && err != nil || tt.want != "" && (!errors.As(err, &r) || r.Message != tt.want) {
			t.Fatalf("%s %s: %v", tt.user, tt.action, err)
		}
	}
}

func TestABlankChoiceTakesTheDefault(t *testing.T) {
	if orDefault("  ", "medium") != "medium" || orDefault("high", "medium") != "high" {
		t.Fatal("orDefault")
	}
	if cut("abcdef", 3) != "abc" || cut("ab", 3) != "ab" {
		t.Fatal("cut")
	}
}
