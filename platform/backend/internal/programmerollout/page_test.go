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
		{lead, "view=ssa&cluster_page=2"},
		{lead, "view=ssa&rollout_matrix_rows_page=2"},
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

// Python's round() takes halves to even, and the coverage a cell states is
// Python's percentage of it.
func TestPercentageRoundsHalvesToEven(t *testing.T) {
	for _, c := range []struct{ n, d, want int }{{1, 8, 12}, {3, 8, 38}, {1, 3, 33}, {2, 3, 67}, {5, 5, 100}} {
		if got := percentage(c.n, c.d); got == nil || *got != c.want {
			t.Errorf("percentage(%d, %d) = %v, want %d", c.n, c.d, got, c.want)
		}
	}
	if percentage(1, 0) != nil {
		t.Error("percentage of nothing is not nil")
	}
}

// _ssa_score absorbs the summation noise before it rounds to one place.
func TestSSAScoreAbsorbsSummationNoise(t *testing.T) {
	for _, c := range []struct{ in, want float64 }{{4.749999999999999, 4.8}, {4.75, 4.8}, {4.65, 4.7}, {5.0, 5.0}, {6.04, 6.0}} {
		in := c.in
		if got := ssaScore(&in); *got != c.want {
			t.Errorf("ssaScore(%v) = %v, want %v", c.in, *got, c.want)
		}
	}
}
