package btpages

import (
	"context"
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btportfolio"
)

func TestThePortalSectionsAreTheExistingPagesOwn(t *testing.T) {
	if len(portalTabs) != len(btportfolio.Rules.Portal.Sections) {
		t.Fatalf("tabs %d, sections %d", len(portalTabs), len(btportfolio.Rules.Portal.Sections))
	}
	for i, tab := range portalTabs {
		if tab[0] != btportfolio.Rules.Portal.Sections[i] {
			t.Errorf("tab %d is %q, the existing page has %q", i, tab[0], btportfolio.Rules.Portal.Sections[i])
		}
	}
}

func TestAnUnknownSectionOrANonPartnerReaderIsPassedOn(t *testing.T) {
	s := NewService(nil, nil)
	for _, c := range []struct{ role, path string }{{"MfiPartnerAdmin", "/mfi-portal/nope"}} {
		_, served, err := s.Build(context.Background(), auth.Principal{ActiveRole: c.role}, c.path, url.Values{})
		if served || err != nil {
			t.Errorf("%s %s: served %v, err %v", c.role, c.path, served, err)
		}
	}
	if _, served, err := s.Build(context.Background(), auth.Principal{ActiveRole: "CCEO"}, "/mfi-portal/loans", url.Values{}); !served || err == nil {
		t.Errorf("a reader without the portal is refused: served %v, err %v", served, err)
	}
}
