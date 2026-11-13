package hrregister

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestAFigureKeepsAShortSecondFigureAndMovesASentenceToItsNote(t *testing.T) {
	strip := figures("Recognition", []metric{
		{"Recognitions", "0", "given in the last quarter", "success"},
		{"People recognised", "0", "of 35 staff, last quarter", "info"},
		{"People recognised", "9", "a second figure with the same label is dropped", "info"},
		{"Latest morale score", "", "", "info"},
	}).GetStrip()
	if strip.GetTitle() != "Recognition context" || len(strip.GetMetrics()) != 3 {
		t.Fatalf("strip: %v", strip)
	}
	sentence, figure, empty := strip.GetMetrics()[0], strip.GetMetrics()[1], strip.GetMetrics()[2]
	if sentence.GetHelper() != "" || sentence.GetNote() != "given in the last quarter" || sentence.GetTone() != "" {
		t.Errorf("a sentence under the figure: %v", sentence)
	}
	if figure.GetHelper() != "of 35 staff, last quarter" || figure.GetNote() != "" || figure.GetTone() != "info" {
		t.Errorf("a second figure under the figure: %v", figure)
	}
	if empty.GetValue() != "—" {
		t.Errorf("a figure with no value: %v", empty)
	}
}

func TestASearchOffersAWayBackAndPagesKeepIt(t *testing.T) {
	reg := register{path: "/org-structure", columns: []string{"Team member"}, emptyTitle: "No people", emptyBody: "None."}
	for i := 0; i < rules.PageSize+3; i++ {
		reg.rows = append(reg.rows, []string{"Person"})
	}
	blocks := records(reg, url.Values{"q": {" a b "}, "page": {"2"}})
	if len(blocks) != 3 {
		t.Fatalf("blocks: %v", blocks)
	}
	clear := blocks[0].GetPanel().GetItems()[0].GetLinks().GetLinks()[0]
	if clear.GetText() != "Clear search" || clear.GetHref() != "/org-structure" {
		t.Errorf("clear search: %v", clear)
	}
	if n := len(blocks[1].GetTable().GetRows()); n != 3 {
		t.Errorf("the second page holds %d rows, want 3", n)
	}
	pages := blocks[2].GetPager().GetPages()
	if len(pages) != 4 || pages[0].GetLabel() != "Page 2 of 2" || pages[1].GetHref() != "?q=a%20b&page=1" || pages[3].GetLabel() != "‹" {
		t.Errorf("pager: %v", pages)
	}
	empty := records(register{path: "/x", emptyTitle: "No people", emptyBody: "None."}, url.Values{})
	if got := empty[0].GetPanel().GetItems(); len(got) != 2 || got[0].GetHeading() != "No people" {
		t.Errorf("the empty register without a search: %v", got)
	}
}

func TestAReachBoundsThePeopleRecordsItReads(t *testing.T) {
	cases := []struct {
		r    reach
		want string
	}{
		{reach{kind: reachAll}, "TRUE"},
		{reach{kind: reachNone}, "FALSE"},
		{reach{kind: reachCountries, countries: []string{"Uganda"}}, "sp.country = ANY($1)"},
		{reach{kind: reachTeam, viewer: "pl"}, "(sp.id = $1 OR EXISTS (SELECT 1 FROM staff_supervisor_assignment l WHERE l.supervisee_id = sp.id AND l.supervisor_id = $1))"},
	}
	for _, c := range cases {
		if got, _ := c.r.profiles(nil); got != c.want {
			t.Errorf("%v: %s", c.r, got)
		}
	}
}

func TestRolesWithoutARegisterAreRefusedBeforeAnythingIsRead(t *testing.T) {
	s := NewService(nil, time.Now)
	for path, page := range rules.Pages {
		for role, r := range page.Roles {
			if r.Page {
				continue
			}
			_, served, err := s.Build(context.Background(), auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: role}}, path, url.Values{})
			if !served || !errors.Is(err, ErrNotAvailable) {
				t.Errorf("%s %s: served %v, %v; want refused", path, role, served, err)
			}
		}
	}
	if _, served, _ := s.Build(context.Background(), auth.Principal{}, "/onboarding", nil); served {
		t.Error("a register Go does not build yet was answered")
	}
}
