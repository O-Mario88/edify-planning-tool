package messaging

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// fakeDB answers the gate's record statements with one scripted record.
type fakeDB struct {
	values []any // id, owner, cluster lead, district, region; nil is "no row"
	teams  []string
}

type fakeRow struct{ values []any }

func (r fakeRow) Scan(dest ...any) error {
	if r.values == nil {
		return pgx.ErrNoRows
	}
	for i, d := range dest {
		*(d.(*string)) = r.values[i].(string)
	}
	return nil
}

func (f *fakeDB) QueryRow(context.Context, string, ...any) pgx.Row { return fakeRow{f.values} }
func (f *fakeDB) Query(context.Context, string, ...any) (pgx.Rows, error) {
	return nil, errors.New("not scripted")
}

func principal(role, user, staff string) auth.Principal {
	return auth.Principal{Account: auth.Account{UserID: user, ActiveRole: role, StaffProfileID: staff}}
}

func TestRoleGateBeforeAnyRecordIsRead(t *testing.T) {
	cases := []struct {
		role, context    string
		allowed, decided bool
	}{
		{"Admin", "bogus", true, true},
		{"Accountant", "school", false, true},
		{"Accountant", "leave", false, false},
		{"Accountant", "fund_request", false, false},
		{"PartnerAdmin", "budget", false, true},
		{"PartnerFieldOfficer", "accountant_disbursement", false, false},
		{"PartnerAdmin", "school", false, false},
		{"CCEO", "evidence", false, false}, // labelled by Go (fixedContextLabels): its record decides
		{"CCEO", "my_plan", false, true},
		{"CCEO", "bogus", false, true},
		{"CCEO", "system", false, false},
	}
	for _, c := range cases {
		allowed, decided := roleGate(slug(c.role), c.context)
		if allowed != c.allowed || decided != c.decided {
			t.Errorf("%s on %s: got (%v, %v), want (%v, %v)", c.role, c.context, allowed, decided, c.allowed, c.decided)
		}
	}
}

func TestAContextWithNoRecordIsReadByItsRoles(t *testing.T) {
	cases := []struct {
		role, context string
		want          bool
	}{
		{"CCEO", "verification", true},
		{"ProjectCoordinator", "ia_return", true},
		{"PartnerAdmin", "ssa_verification", true},
		{"HumanResources", "verification", false},
		{"CountryDirector", "verification", false},
		{"Accountant", "accountability_confirmation", true},
		{"CCEO", "accountability_confirmation", true},
		{"ImpactAssessment", "accountability_confirmation", false},
		{"HumanResources", "system", true},
		{"CCEO", "finance", false},
		{"Program Lead", "budget", true},
		{"ImpactAssessment", "core_school", true},
		{"CCEO", "school", false}, // a school that is not found
		{"CCEO", "project", false},
	}
	for _, c := range cases {
		if got := unresolved(slug(c.role), c.context); got != c.want {
			t.Errorf("%s on an unresolved %s: got %v, want %v", c.role, c.context, got, c.want)
		}
	}
}

func TestRecordsReadWithoutAScope(t *testing.T) {
	ctx := context.Background()
	cases := []struct {
		name          string
		p             auth.Principal
		context       string
		record        []any
		want, handsOn bool
	}{
		{"own fund request", principal("CCEO", "u1", "s1"), "fund_request", []any{"f", "u1", "", "", ""}, true, false},
		{"another's fund request", principal("CCEO", "u1", "s1"), "fund_request", []any{"f", "u2", "", "", ""}, false, false},
		{"IA reads every fund request", principal("ImpactAssessment", "u1", ""), "fund_request", []any{"f", "u2", "", "", ""}, true, false},
		{"HR reads every leave", principal("HumanResources", "u1", ""), "leave", []any{"l", "s9", "", "", ""}, true, false},
		{"own leave", principal("CCEO", "u1", "s1"), "leave", []any{"l", "s1", "", "", ""}, true, false},
		{"another's leave", principal("CCEO", "u1", "s1"), "leave", []any{"l", "s2", "", "", ""}, false, false},
		{"no profile, no leave", principal("ProjectCoordinator", "u1", ""), "leave", []any{"l", "", "", "", ""}, false, false},
		{"a found project", principal("CCEO", "u1", "s1"), "project", []any{"p", "", "", "", ""}, true, false},
		{"a missing project", principal("CCEO", "u1", "s1"), "project", nil, false, false},
		{"hand-over for the coordinator", principal("ProjectCoordinator", "u1", ""), "partner_assignment", []any{"a", "", "", "", ""}, true, false},
		{"hand-over for HR", principal("HumanResources", "u1", ""), "partner_assignment", []any{"a", "", "", "", ""}, false, false},
		{"hand-over for a partner", principal("PartnerAdmin", "u1", ""), "partner_assignment", []any{"a", "", "", "", ""}, false, true},
		{"hand-over for an officer", principal("CCEO", "u1", "s1"), "partner_assignment", []any{"a", "", "", "", ""}, false, true},
		{"RVP never reads a school", principal("RegionalVicePresident", "u1", ""), "school", []any{"x", "", "", "", ""}, false, false},
		{"a missing activity", principal("CCEO", "u1", "s1"), "activity", nil, false, false},
		{"a missing IA activity", principal("CCEO", "u1", "s1"), "ia_return", nil, true, false},
	}
	for _, c := range cases {
		g := newGate(&fakeDB{values: c.record}, c.p, time.Now())
		got, err := g.allows(ctx, c.context, "id")
		if c.handsOn != errors.Is(err, ErrHandOn) || (err != nil && !c.handsOn) {
			t.Errorf("%s: error %v, want handed on %v", c.name, err, c.handsOn)
			continue
		}
		if got != c.want {
			t.Errorf("%s: got %v, want %v", c.name, got, c.want)
		}
	}
}

func TestAThreadWithoutAContextIsNeverListed(t *testing.T) {
	g := newGate(&fakeDB{}, principal("CCEO", "u1", "s1"), time.Now())
	for _, c := range [][2]string{{"", "x"}, {"school", ""}} {
		if ok, err := g.allows(context.Background(), c[0], c[1]); ok || err != nil {
			t.Errorf("%q: got (%v, %v)", c, ok, err)
		}
	}
}

func TestUnreadIsAMoveSinceTheReaderLastReadNotTheirOwn(t *testing.T) {
	at := time.Date(2026, 11, 3, 10, 0, 0, 0, time.UTC)
	before, after := at.Add(-time.Minute), at.Add(time.Minute)
	cases := []struct {
		name    string
		m       membership
		last    lastMessage
		hasLast bool
		want    bool
	}{
		{"never moved", membership{}, lastMessage{senderID: "u2"}, true, false},
		{"never read", membership{lastReplyAt: &at}, lastMessage{senderID: "u2"}, true, true},
		{"read before", membership{lastReplyAt: &at, lastReadAt: &before}, lastMessage{senderID: "u2"}, true, true},
		{"read after", membership{lastReplyAt: &at, lastReadAt: &after}, lastMessage{senderID: "u2"}, true, false},
		{"read at the moment", membership{lastReplyAt: &at, lastReadAt: &at}, lastMessage{senderID: "u2"}, true, false},
		{"own last word", membership{lastReplyAt: &at}, lastMessage{senderID: "u1"}, true, false},
		{"no message", membership{lastReplyAt: &at}, lastMessage{}, false, false},
	}
	for _, c := range cases {
		if got := unread(c.m, c.last, c.hasLast, "u1"); got != c.want {
			t.Errorf("%s: got %v, want %v", c.name, got, c.want)
		}
	}
}

func TestInitialsAreTheAvatarFilters(t *testing.T) {
	for name, want := range map[string]string{
		"Program Lead 1": "P1", "  amy   nakato ": "AN", "Okello": "OK", "o": "O", "": "ED", "   ": "ED",
		"élan vital": "ÉV", "System": "SY",
	} {
		if got := initials(name); got != want {
			t.Errorf("%q: got %q, want %q", name, got, want)
		}
	}
}

func TestTheSnippetIsNinetyCharacters(t *testing.T) {
	long := strings.Repeat("é", 100)
	if got := firstRunes(long, snippetLength); len([]rune(got)) != 90 {
		t.Errorf("got %d characters", len([]rune(got)))
	}
	if got := firstRunes("short", snippetLength); got != "short" {
		t.Errorf("got %q", got)
	}
}

func TestBadgeTones(t *testing.T) {
	for kind, want := range map[string]string{
		"fund_request": "finance", "accountant_disbursement": "finance", "finance": "finance", "budget": "primary",
		"leave": "leave", "ia_return": "verification", "evidence_upload": "evidence", "partner_assignment": "primary",
		"school": "primary",
	} {
		if got := contextTone(kind); got != want {
			t.Errorf("%s: got %q, want %q", kind, got, want)
		}
	}
}

func TestThePagerWindow(t *testing.T) {
	labels := func(page, pages int) string {
		var out []string
		for _, l := range pager(page, pages, pages*rules.PageSize, (page-1)*rules.PageSize, "all", "newest", "").GetLinks() {
			if l.GetCurrent() {
				out = append(out, "["+l.GetLabel()+"]")
			} else {
				out = append(out, l.GetLabel())
			}
		}
		return strings.Join(out, " ")
	}
	cases := []struct {
		page, pages int
		want        string
	}{
		{1, 2, "[1] 2"},
		{1, 5, "[1] 2 3 … 5"}, // Go draws the gap the template left out
		{1, 6, "[1] 2 3 … 6"},
		{5, 9, "1 2 3 4 [5] 6 … 9"}, // Go draws the gap the template left out
		{9, 9, "1 2 3 … 8 [9]"},
	}
	for _, c := range cases {
		if got := labels(c.page, c.pages); got != c.want {
			t.Errorf("page %d of %d: got %q, want %q", c.page, c.pages, got, c.want)
		}
	}
	if p := pager(1, 1, 3, 0, "all", "newest", ""); p.GetShown() || p.GetSummary() != "Showing 1–3 of 3" {
		t.Errorf("one page: %v", p)
	}
	if p := pager(1, 1, 0, 0, "all", "newest", ""); p.GetSummary() != "Showing 0–0 of 0" {
		t.Errorf("no threads: %v", p)
	}
	if got := pager(1, 3, 20, 0, "unread", "oldest", "a b").GetNextHref(); got != "/messages?page=2&q=a+b&sort=oldest&tab=unread" {
		t.Errorf("next: %q", got)
	}
}

func TestWhoMayOpenTheInbox(t *testing.T) {
	if err := mayOpen(principal("CCEO", "u", "")); err != nil {
		t.Errorf("CCEO: %v", err)
	}
	if err := mayOpen(principal("ClusterLeader", "u", "")); !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("a cluster leader: %v", err)
	}
	if err := mayOpen(principal("Nobody", "u", "")); !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("an unknown role: %v", err)
	}
	acting := principal("Program Lead", "u", "")
	acting.InActingAppointment = true
	if err := mayOpen(acting); !errors.Is(err, ErrHandOn) {
		t.Errorf("acting: %v", err)
	}
}
