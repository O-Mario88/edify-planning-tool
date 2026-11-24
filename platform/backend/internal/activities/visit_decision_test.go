package activities

import (
	"testing"
	"time"
)

// _where and _on: how the requester's notice names the visit.
func TestADecisionNamesTheVisitByItsSchoolAndDay(t *testing.T) {
	if got := visitDecisionWhere(""); got != "the school" {
		t.Fatalf("got %q", got)
	}
	day := time.Date(2026, 12, 7, 0, 0, 0, 0, time.UTC)
	if got := visitDecisionOn(&day); got != " on 7 Dec 2026" {
		t.Fatalf("got %q", got)
	}
	if got := visitDecisionOn(nil); got != "" {
		t.Fatalf("got %q", got)
	}
}

func TestADecisionNoteKeepsItsFirst512Characters(t *testing.T) {
	long := ""
	for range 600 {
		long += "é"
	}
	if got := []rune(clip(long, decisionNoteLimit)); len(got) != 512 {
		t.Fatalf("kept %d", len(got))
	}
	if clip("short", decisionNoteLimit) != "short" {
		t.Fatal("a short note is kept whole")
	}
}
