package partnerworkspace

import (
	"context"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestStaffWhoMayOpenPartnerOversightAreSentThereWithTheYearAndPartnerOnly(t *testing.T) {
	cases := map[string]string{
		"":                                "/partner-oversight/",
		"q=x&region=r&status=overdue":     "/partner-oversight/",
		"fy=2027":                         "/partner-oversight/?fy=2027",
		"partner=p 1&fy=2026&status=late": "/partner-oversight/?fy=2026&partner=p+1",
		"partner=&fy=":                    "/partner-oversight/",
	}
	for raw, want := range cases {
		q, _ := url.ParseQuery(raw)
		if got := oversightURL(q); got != want {
			t.Errorf("%q: %q, want %q", raw, got, want)
		}
	}
}

func TestASearchOrAnExportIsLeftToTheExistingPage(t *testing.T) {
	s := NewService(nil, time.Now)
	for _, raw := range []string{"q=Mukono", "export=csv"} {
		q, _ := url.ParseQuery(raw)
		resp, handled, err := s.Build(context.Background(), auth.Principal{ActiveRole: "HumanResources"}, Path, q)
		if resp != nil || handled || err != nil {
			t.Errorf("%s: got (%v, %v, %v), want it passed on", raw, resp, handled, err)
		}
	}
}

func TestInitialsAreTheAvatarFilters(t *testing.T) {
	for name, want := range map[string]string{
		"Build Africa": "BA", "Room to Read": "RR", "pangea": "PA", "X": "X", "  ": "ED", "": "ED", "édith ölund": "ÉÖ",
	} {
		if got := avatarInitials(name); got != want {
			t.Errorf("%q: %q, want %q", name, got, want)
		}
	}
}

func TestSharesRoundAsPythonDoes(t *testing.T) {
	for _, c := range []struct{ part, total, want int }{{1, 8, 12}, {3, 8, 38}, {1, 3, 33}, {2, 3, 67}, {0, 0, 0}, {5, 5, 100}} {
		if got := share(c.part, c.total); got != c.want {
			t.Errorf("%d/%d: %d, want %d", c.part, c.total, got, c.want)
		}
	}
}
