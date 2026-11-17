package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/oversightportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// ErrNotDrawn is a reader whose monitor Go does not draw yet: anyone but a
// Programme Lead in their own seat.
var ErrNotDrawn = errors.New("planningmonitor: not drawn for this reader")

// Monitor is planning_monitor's answer: the teams in the roster's order,
// each holding its people, and everyone together.
type Monitor struct {
	FY    string
	Leads []*Lead
	// outside are the projects no SSA intervention measures.
	outside []string
	// wholeCountry is a country reader's monitor: its ledger reads every
	// planned activity of the year.
	wholeCountry bool
}

// Officers is everybody on the monitor (the totals' people).
func (m *Monitor) Officers() []*Officer {
	var out []*Officer
	for _, l := range m.Leads {
		out = append(out, l.Officers...)
	}
	return out
}

// monitor is one build: what it reads, and the rows it fills.
type monitor struct {
	db          schooldirectory.Querier
	fy          string
	operational string
	outside     []string
	directory   func(context.Context, []string) (map[string]oversightportfolio.Owner, error)

	schools, outreach          map[string]*School
	schoolOrder, outreachOrder []*School
	officers                   map[string]*Officer
	leadsByKey                 map[string]*Lead
	leadOrder                  []*Lead
}

func (m *monitor) allOfficers() []*Officer {
	var out []*Officer
	for _, l := range m.leadOrder {
		out = append(out, l.Officers...)
	}
	return out
}

// Read is planning_monitor for a Programme Lead in their own seat: the
// schools held by them and by the people who report to them, and the ones
// in their scope nobody holds (_monitored_schools), under the lead's team.
func Read(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time) (*Monitor, error) {
	if p.ActiveRole != rules.ProgramLeadRole || p.InActingAppointment {
		return nil, ErrNotDrawn
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	own, err := partneroversight.BothIDSpaces(ctx, db, []string{p.UserID, p.StaffProfileID})
	if err != nil {
		return nil, err
	}
	supervised, err := partneroversight.BothIDSpaces(ctx, db, scope.SupervisedStaffIDs)
	if err != nil {
		return nil, err
	}
	team := append([]string{}, own...)
	for _, id := range supervised {
		if !contains(own, id) {
			team = append(team, id)
		}
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	if outside == nil {
		outside = []string{}
	}
	m := newMonitor(db, fy, now, outside)
	schoolIDs := scope.SchoolIDs
	if schoolIDs == nil {
		schoolIDs = []string{}
	}
	base := `(s.account_owner_id = ANY($1) OR (s.id = ANY($2) AND (s.account_owner_id IS NULL OR s.account_owner_id = '')))`
	if err := m.readSchools(ctx, base, []any{team, schoolIDs}); err != nil {
		return nil, err
	}
	if err := m.people(ctx, own); err != nil {
		return nil, err
	}
	return m.finish(ctx)
}

func newMonitor(db schooldirectory.Querier, fy string, now time.Time, outside []string) *monitor {
	return &monitor{db: db, fy: fy, operational: operationalFY(now.UTC()), outside: outside,
		directory: func(ctx context.Context, ids []string) (map[string]oversightportfolio.Owner, error) {
			return oversightportfolio.StaffDirectory(ctx, db, ids)
		}}
}

// ReadCountry is planning_monitor for a country reader (the Country
// Director, the Admin): every school in their analytics scope, under every
// team of the country's roster, then the CCEOs with no Lead.
func ReadCountry(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time) (*Monitor, error) {
	if p.InActingAppointment {
		return nil, ErrNotDrawn
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	if !scope.CountryScope {
		return nil, ErrNotDrawn
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	if outside == nil {
		outside = []string{}
	}
	m := newMonitor(db, fy, now, outside)
	args := []any{}
	base := schooldirectory.AnalyticsReach(scope, &args)
	if err := m.readSchools(ctx, base, args); err != nil {
		return nil, err
	}
	teams, err := m.roster(ctx, scope.Country)
	if err != nil {
		return nil, err
	}
	if err := m.peopleOf(ctx, teams); err != nil {
		return nil, err
	}
	monitor, err := m.finish(ctx)
	if err != nil {
		return nil, err
	}
	monitor.wholeCountry = true
	return monitor, nil
}

// finish files each school under its holder's row and counts the year's
// work.
func (m *monitor) finish(ctx context.Context) (*Monitor, error) {
	fy, outside := m.fy, m.outside
	for _, s := range append(append([]*School{}, m.schoolOrder...), m.outreachOrder...) {
		o := m.officers[s.OfficerID]
		if o == nil {
			return nil, fmt.Errorf("planningmonitor: no row for the holder of %s", s.ID)
		}
		s.LeadID, s.LeadName = o.LeadID, o.LeadName
		if _, ok := m.schools[s.ID]; ok {
			o.Schools = append(o.Schools, s)
		} else {
			o.Outreach = append(o.Outreach, s)
		}
	}
	if len(m.officers) == 0 {
		return &Monitor{FY: fy, outside: outside}, nil
	}
	for _, count := range []func(context.Context) error{m.countPlannedVisits, m.countPartnerWork, m.countProjectPlaces} {
		if err := count(ctx); err != nil {
			return nil, err
		}
	}
	var leads []*Lead
	for _, l := range m.leadOrder {
		if len(l.Officers) > 0 {
			leads = append(leads, l)
		}
	}
	rank := func(l *Lead) int {
		switch l.Key {
		case rules.NoLead[0]:
			return 1
		case rules.Unassigned[0]:
			return 2
		}
		return 0
	}
	sort.SliceStable(leads, func(i, j int) bool { return rank(leads[i]) < rank(leads[j]) })
	return &Monitor{FY: fy, Leads: leads, outside: outside}, nil
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// operationalFY is get_operational_fy: the year starts on 1 October.
func operationalFY(now time.Time) string {
	if now.Month() >= time.October {
		return fmt.Sprint(now.Year() + 1)
	}
	return fmt.Sprint(now.Year())
}
