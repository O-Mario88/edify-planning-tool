package activities

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The function that withdraws a cancelled visit's advances keeps exactly the
// statuses the existing cancel keeps (MONEY_MOVED_ADVANCE_STATUSES, exported
// to rules.json): the SQL names them as a literal, so this holds the two
// together.
func TestTheWithdrawFunctionNamesTheMovedStatuses(t *testing.T) {
	raw, err := os.ReadFile(filepath.FromSlash("../../../deploy/db/advance_withdraw_roles.sql"))
	if err != nil {
		t.Fatal(err)
	}
	array := regexp.MustCompile(`(?s)ARRAY\[(.*?)\]::varchar\[\]`).FindSubmatch(raw)
	if array == nil {
		t.Fatal("the function's status list was not found")
	}
	named := []string{}
	for _, m := range regexp.MustCompile(`'([a-z_]+)'`).FindAllSubmatch(array[1], -1) {
		named = append(named, string(m[1]))
	}
	want := slices.Clone(rules.Cancel.MoneyMovedAdvanceStatuses)
	slices.Sort(named)
	slices.Sort(want)
	if len(want) == 0 || !slices.Equal(named, want) {
		t.Fatalf("the function keeps %v; the existing cancel keeps %v", named, want)
	}
}

// A person in an acting seat, with no staff profile, or asking for visits,
// is handed on before anything is read, and nothing is refused for them.
func TestTheCancelIsHandedOnBeforeAnyRead(t *testing.T) {
	s, err := NewService(nil, nil, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	for name, p := range map[string]auth.Principal{
		"acting":           {Account: auth.Account{StaffProfileID: "s", InActingAppointment: true}},
		"no staff profile": {Account: auth.Account{}},
	} {
		pl, err := s.prepareCancel(context.Background(), p, CancelRequest{ActivityID: "a"}, Origin{})
		if !errors.Is(err, ErrHandOn) || pl != nil {
			t.Errorf("%s: %v, want a hand-on with no plan", name, err)
		}
	}
}

// The costs row keeps what the existing application says it keeps, and
// nothing when it keeps nothing (costs_follow._hand_over's early return).
func TestTheCancelKeepsNoCostsRowWhenNothingIsKept(t *testing.T) {
	id, err := keepCancelCosts(context.Background(), nil, &cancelPlan{})
	if err != nil || id != 0 {
		t.Fatalf("keepCancelCosts with nothing kept: %d %v", id, err)
	}
}
