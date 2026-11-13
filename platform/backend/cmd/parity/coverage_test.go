package main

import (
	"errors"
	"reflect"
	"testing"

	"connectrpc.com/connect"
)

func TestCoverageTellsGoAnswersFromHandOffs(t *testing.T) {
	cases := map[string]error{
		"built":     nil,
		"passed on": connect.NewError(connect.CodeUnavailable, errors.New("This screen is not available here yet. Use the Edify web app.")),
		"refused":   connect.NewError(connect.CodeNotFound, errors.New("no such page")),
		"failed":    connect.NewError(connect.CodeInternal, errors.New("boom")),
	}
	for want, err := range cases {
		if got := kindOf(err); got != want {
			t.Fatalf("%v: %s, want %s", err, got, want)
		}
	}
}

func TestCoverageListsTheFullPagesNoGoPageAnswers(t *testing.T) {
	inventory := []inventoryRoute{
		{"/planning", "page"}, {"/clusters/", "page"}, {"/budget", "page"},
		{"/planning/schedule-action", "action"}, {"/reports", "page"},
	}
	missing, total := notInGo(inventory, []string{"/planning", "/clusters"})
	if total != 4 || !reflect.DeepEqual(missing, []string{"/budget", "/reports"}) {
		t.Fatalf("total %d, missing %v", total, missing)
	}
}
