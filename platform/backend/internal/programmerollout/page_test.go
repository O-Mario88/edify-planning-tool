package programmerollout

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// Figures read as Django's intcomma writes them.
func TestIntcommaIsDjangos(t *testing.T) {
	for n, want := range map[int]string{0: "0", 999: "999", 1000: "1,000", 12345: "12,345", 1234567: "1,234,567", -4200: "-4,200"} {
		if got := intcomma(n); got != want {
			t.Errorf("%d: %q, want %q", n, got, want)
		}
	}
}

// The page's doors, decided before anything is read.
func TestThePageDecidesItsDoorsBeforeReading(t *testing.T) {
	s := NewService(nil, time.Now)
	ctx := context.Background()
	lead := auth.Principal{ActiveRole: "Program Lead", StaffProfileID: "sp1", UserID: "u1"}
	if _, served, err := s.Build(ctx, lead, Path+"/", nil); !served || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("with the slash: %v %v", served, err)
	}
	if _, served, err := s.Build(ctx, auth.Principal{ActiveRole: "CCEO"}, Path, nil); !served || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("an officer: %v %v", served, err)
	}
	for _, c := range []struct {
		p     auth.Principal
		query string
	}{
		{auth.Principal{ActiveRole: "Admin"}, ""},
		{auth.Principal{ActiveRole: "ImpactAssessment"}, ""},
		{auth.Principal{ActiveRole: "Program Lead", StaffProfileID: "sp1", InActingAppointment: true}, ""},
		{auth.Principal{ActiveRole: "Program Lead"}, ""},
		{lead, "view=ssa"},
		{lead, "view=spiritual"},
		{lead, "course_page=2"},
		{lead, "lead=sp9"},
	} {
		query, _ := url.ParseQuery(c.query)
		if _, served, err := s.Build(ctx, c.p, Path, query); served || err != nil {
			t.Errorf("%s %q: %v %v", c.p.ActiveRole, c.query, served, err)
		}
	}
}
