package planningmonitor

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// The page's doors, decided before anything is read: the path without its
// slash and an officer are refused, the Lead is sent to their dashboard, and
// IA, the regional readers, an acting seat, the Execution tab, a chosen gap
// or Lead and the data form hand on.
func TestThePageDecidesItsDoorsBeforeReading(t *testing.T) {
	pg := NewPage(nil, time.Now)
	ctx := context.Background()
	if _, served, err := pg.Build(ctx, auth.Principal{ActiveRole: "CountryDirector"}, "/planning-monitor", nil); !served || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("without the slash: %v %v", served, err)
	}
	if _, served, err := pg.Build(ctx, auth.Principal{ActiveRole: "CCEO"}, PagePath, nil); !served || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("an officer: %v %v", served, err)
	}
	if resp, served, err := pg.Build(ctx, auth.Principal{ActiveRole: "Program Lead"}, PagePath, nil); !served || err != nil || resp.GetRedirect() != dashboardSection {
		t.Errorf("the Lead: %v %v %v", resp, served, err)
	}
	for _, c := range []struct {
		role, query string
		acting      bool
	}{
		{"ImpactAssessment", "format=json", false}, {"ImpactAssessment", "fy=2026&gap=no_visit", false},
		{"ImpactAssessment", "view=execution&fy=2026", false}, {"ImpactAssessment", "fy=2026&fy=2027", false},
		{"RegionalVicePresident", "view=execution", false}, {"RegionalProgramLead", "", false},
		{"CountryDirector", "", true}, {"Program Lead", "fy=2026", false},
		{"CountryDirector", "view=execution", false}, {"CountryDirector", "gap=no_visit", false},
		{"CountryDirector", "program_lead=x", false}, {"CountryDirector", "format=json", false},
	} {
		query, _ := url.ParseQuery(c.query)
		p := auth.Principal{ActiveRole: c.role, InActingAppointment: c.acting}
		if _, served, err := pg.Build(ctx, p, PagePath, query); served || err != nil {
			t.Errorf("%s %q acting=%v: %v %v", c.role, c.query, c.acting, served, err)
		}
	}
	// IA keeps the monitors as Planning Oversight tabs: the same query, the
	// view the tab's, appended where the request gave none.
	for query, want := range map[string]string{
		"":                 "/team-planning-oversight/?view=monitor",
		"view=execution":   "/team-planning-oversight/?view=execution",
		"view=Planning":    "/team-planning-oversight/?view=monitor",
		"fy=2026":          "/team-planning-oversight/?fy=2026&view=monitor",
		"program_lead=a+b": "/team-planning-oversight/?program_lead=a+b&view=monitor",
	} {
		q, _ := url.ParseQuery(query)
		resp, served, err := pg.Build(ctx, auth.Principal{ActiveRole: "ImpactAssessment"}, PagePath, q)
		if !served || err != nil || resp.GetRedirect() != want {
			t.Errorf("IA %q: %v %v %v, want %s", query, resp.GetRedirect(), served, err, want)
		}
	}
}
