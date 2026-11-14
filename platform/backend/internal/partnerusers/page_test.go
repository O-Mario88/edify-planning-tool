package partnerusers

import (
	"context"
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teams"
)

func TestAMembersLoginReadsActiveInvitedDeactivatedOrNone(t *testing.T) {
	for _, c := range []struct {
		login *teams.MemberLogin
		want  string
	}{
		{nil, "No login"},
		{&teams.MemberLogin{Email: "a@x.org", IsActive: true, Status: "active"}, "a@x.org · Active"},
		{&teams.MemberLogin{Email: "b@x.org", Status: "pending_invited"}, "b@x.org · Invited"},
		{&teams.MemberLogin{Email: "c@x.org", Status: "disabled"}, "c@x.org · Deactivated"},
	} {
		if got := login(teams.Member{Login: c.login}); got != c.want {
			t.Errorf("%+v: %q, want %q", c.login, got, c.want)
		}
	}
}

func TestContactRunsPhoneAndEmailTogetherAndLinksTheEmail(t *testing.T) {
	if c := contact(teams.Member{}); c.GetText() != "—" || c.GetHref() != "" {
		t.Errorf("none: %v", c)
	}
	if c := contact(teams.Member{Phone: "0700 1", Email: "a@x.org"}); c.GetText() != "0700 1a@x.org" || c.GetHref() != "mailto:a@x.org" {
		t.Errorf("both: %v", c)
	}
	if c := contact(teams.Member{Phone: "0700 1"}); c.GetText() != "0700 1" || c.GetHref() != "" {
		t.Errorf("phone: %v", c)
	}
}

func TestTheMenuOffersSetUpLoginOnlyWithoutOne(t *testing.T) {
	got := menu("p", teams.Member{ID: "m"}).GetActions()
	if len(got) != 2 || got[0].GetHref() != "/partners/p/members/m/schools" || got[1].GetLabel() != "Set up login" || got[1].GetKey() != "menu" {
		t.Fatalf("without a login: %v", got)
	}
	if got := menu("p", teams.Member{ID: "m", Login: &teams.MemberLogin{}}).GetActions(); got[1].GetLabel() != "Reset password" {
		t.Fatalf("with a login: %v", got)
	}
}

type stubTeams struct {
	team teams.PartnerTeam
	err  error
}

func (s stubTeams) Team(context.Context, auth.Principal, string) (teams.PartnerTeam, error) {
	return s.team, s.err
}

func TestAReaderWhoLeadsNoTeamIsSentToTheDashboard(t *testing.T) {
	admin := auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}
	for _, svc := range []*Service{
		NewService(stubTeams{err: &teams.Refused{NotFound: true}}),
		NewService(stubTeams{team: teams.PartnerTeam{Roster: true}}),
	} {
		got, served, err := svc.Build(context.Background(), admin, Path, nil)
		if err != nil || !served || got.GetRedirect() != dashboard {
			t.Fatalf("%v %v %v", got, served, err)
		}
	}
	if _, _, err := NewService(stubTeams{err: errors.New("down")}).Build(context.Background(), admin, Path, nil); err == nil {
		t.Fatal("a failed read is not an error")
	}
}
