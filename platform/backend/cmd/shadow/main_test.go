package main

import (
	"testing"
	"time"
)

var w = window{time.Date(2026, 11, 12, 12, 0, 0, 0, time.UTC), time.Date(2026, 11, 12, 12, 10, 0, 0, time.UTC)}

// Rows the two runs wrote differently only in the ids they made and the
// times inside the run read the same; anything else stays apart.
func TestOnlyTheRunsOwnIdsAndTimesAreSetAside(t *testing.T) {
	a := []map[string]any{{"id": "a1", "school_id": "s9", "created_at": "2026-11-12T15:05:00.123+03:00",
		"status": "scheduled", "payload": map[string]any{"activityId": "a1"}}}
	b := []map[string]any{{"id": "b1", "school_id": "s9", "created_at": "2026-11-12T12:06:00Z",
		"status": "scheduled", "payload": map[string]any{"activityId": "b1"}}}
	na := normalised(a, "activity", map[string]bool{"a1": true}, w)
	nb := normalised(b, "activity", map[string]bool{"b1": true}, w)
	if len(minusStrings(na, nb)) != 0 {
		t.Errorf("the same save, made twice: %v vs %v", na, nb)
	}
	b[0]["status"] = "planned"
	if len(minusStrings(normalised(a, "activity", map[string]bool{"a1": true}, w), normalised(b, "activity", map[string]bool{"b1": true}, w))) == 0 {
		t.Error("a different status must differ")
	}
	old := []map[string]any{{"id": "x", "created_at": "2026-11-11T09:00:00Z"}}
	if got := normalised(old, "activity", nil, w)[0]; got != `{"created_at":"2026-11-11T09:00:00Z","id":"x"}` {
		t.Errorf("a time outside the run and an existing id are kept: %s", got)
	}
	if got := normalised([]map[string]any{{"seq": 7.0, "hash": "h"}}, "audit_log", nil, w)[0]; got != `{"hash":"<chain>","seq":"<chain>"}` {
		t.Errorf("the chain's own columns: %s", got)
	}
}

func TestRowsAreCountedNotJustSeen(t *testing.T) {
	r := map[string]any{"k": 1.0}
	if got := minus([]map[string]any{r, r}, []map[string]any{r}); len(got) != 1 {
		t.Errorf("a row written twice on one side and once on the other: %v", got)
	}
	if got := made(map[string][]map[string]any{"t": {{"id": "n"}, {"id": "o"}}}, map[string]map[string]bool{"t": {"o": true}}); !got["n"] || got["o"] {
		t.Errorf("an id the other copy holds was updated, not made: %v", got)
	}
}
