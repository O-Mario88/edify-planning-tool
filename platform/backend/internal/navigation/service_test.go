package navigation

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// team answers the one question the service asks the database: the
// partner's own login on the reader's first roster entry, or no entry.
type team struct {
	onRoster bool
	owner    *string
	asked    int
}

func (t *team) Query(context.Context, string, ...any) (pgx.Rows, error) {
	return nil, errors.New("not asked")
}

func (t *team) QueryRow(context.Context, string, ...any) pgx.Row {
	t.asked++
	return row{t}
}

type row struct{ t *team }

func (r row) Scan(dest ...any) error {
	if !r.t.onRoster {
		return pgx.ErrNoRows
	}
	*(dest[0].(**string)) = r.t.owner
	return nil
}

func principal(role, user string) auth.Principal {
	var p auth.Principal
	p.ActiveRole, p.UserID = role, user
	return p
}

func keys(t *testing.T, s *Service, p auth.Principal) (bottom, menu []string, served bool) {
	t.Helper()
	got, served, err := s.Build(context.Background(), p)
	if err != nil {
		t.Fatal(err)
	}
	for _, i := range got.GetBottom() {
		bottom = append(bottom, i.GetPageKey())
	}
	for _, sec := range got.GetSections() {
		for _, i := range sec.GetItems() {
			menu = append(menu, i.GetPageKey())
			if i.GetIconSvg() == "" {
				t.Errorf("%s has no icon", i.GetPageKey())
			}
		}
	}
	return bottom, menu, served
}

func TestEveryRoleIsAnsweredFromItsOwnExportedMenu(t *testing.T) {
	for role, want := range rules.Roles {
		db := &team{}
		s := NewService(db)
		bottom, menu, served := keys(t, s, principal(role, "u1"))
		if !served {
			t.Fatalf("%s: not served", role)
		}
		if len(bottom) != len(want.Bottom) || len(menu) != len(want.items())-len(want.Bottom) {
			t.Errorf("%s: %d bar, %d menu items; want %d, %d", role, len(bottom), len(menu), len(want.Bottom), len(want.items())-len(want.Bottom))
		}
		if partner := slices.Contains(rules.PartnerTeam.Roles, role); (db.asked > 0) != partner {
			t.Errorf("%s: asked the roster %d times", role, db.asked)
		}
	}
}

func TestARoleTheRulesDoNotNameIsLeftToTheExistingApplication(t *testing.T) {
	got, served, err := NewService(&team{}).Build(context.Background(), principal("SomethingNew", "u1"))
	if got != nil || served || err != nil {
		t.Fatalf("got %v, %v, %v", got, served, err)
	}
}

func TestAPartnerLoginIsGivenTheMenuItsPlaceOnTheTeamCalls(t *testing.T) {
	mine, someoneElse := "u1", "u2"
	withheld := []string{"partner_assignments", "partner_evidence", "todos", "calendar"}
	cases := []struct {
		name       string
		role       string
		team       team
		served     bool
		teamMember bool
	}{
		{"no roster entry: the whole portal", "PartnerFieldOfficer", team{}, true, false},
		{"the partner's own login: the whole portal", "PartnerFieldOfficer", team{onRoster: true, owner: &mine}, true, false},
		{"a field officer on someone's team: a team member", "PartnerFieldOfficer", team{onRoster: true, owner: &someoneElse}, true, true},
		{"a field officer on a team with no partner login: a team member", "PartnerFieldOfficer", team{onRoster: true}, true, true},
		{"a Partner Admin on someone's team: left to the partner scope", "PartnerAdmin", team{onRoster: true, owner: &someoneElse}, false, false},
		{"a Partner Admin's own login: the whole portal", "PartnerAdmin", team{onRoster: true, owner: &mine}, true, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			db := c.team
			bottom, menu, served := keys(t, NewService(&db), principal(c.role, mine))
			if served != c.served {
				t.Fatalf("served %v, want %v", served, c.served)
			}
			if !served {
				return
			}
			want := rules.Roles[c.role]
			if c.teamMember {
				want = rules.TeamMembers[c.role]
			}
			if len(menu)+len(bottom) != len(want.items()) {
				t.Errorf("%d items, want %d", len(menu)+len(bottom), len(want.items()))
			}
			for _, key := range withheld {
				if slices.Contains(menu, key) == c.teamMember {
					t.Errorf("%s offered: %v", key, !c.teamMember)
				}
			}
		})
	}
}

func TestARosterReadThatFailsIsAnError(t *testing.T) {
	s := NewService(failing{})
	if _, served, err := s.Build(context.Background(), principal("PartnerAdmin", "u1")); err == nil || served {
		t.Fatalf("served %v, err %v", served, err)
	}
}

type failing struct{}

func (failing) Query(context.Context, string, ...any) (pgx.Rows, error) {
	return nil, errors.New("down")
}
func (failing) QueryRow(context.Context, string, ...any) pgx.Row { return failedRow{} }

type failedRow struct{}

func (failedRow) Scan(...any) error { return errors.New("down") }

func TestEachAnswerIsItsOwnMessage(t *testing.T) {
	s := NewService(&team{})
	first, _, _ := s.Build(context.Background(), principal("CCEO", "u1"))
	first.Bottom[0].Label = "changed"
	second, _, _ := s.Build(context.Background(), principal("CCEO", "u1"))
	if second.GetBottom()[0].GetLabel() == "changed" {
		t.Fatal("answers share their items")
	}
}
