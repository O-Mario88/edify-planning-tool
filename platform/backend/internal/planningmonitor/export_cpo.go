package planningmonitor

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// CPOSchool is one school of Country Planning Oversight's dataset as the
// existing build_dataset leaves it: its owner key, allocation and figures.
type CPOSchool struct {
	Owner          string
	Allocation     [3]int
	Vector         []int
	Family, Holder string
	StaffClaims    int
}

// CountryOversightSchools is service.build_dataset for the reader and a
// window (period "fy", "quarter", "month" or "week"; week as 2006-W01).
func CountryOversightSchools(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy, period, quarter string,
	month int, week string, now time.Time) (map[string]CPOSchool, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	var start *time.Time
	if week != "" {
		var y, wk int
		if _, err := fmtSscanWeek(week, &y, &wk); err == nil {
			d := isoWeekStart(y, wk)
			start = &d
		}
	}
	l := now.In(cpoLocation)
	d, err := buildCPODataset(ctx, db, scope, cpoWindowFor(fy, period, quarter, month, start), date(l.Year(), l.Month(), l.Day()))
	if err != nil {
		return nil, err
	}
	out := map[string]CPOSchool{}
	for _, s := range d.schools {
		a := d.allocations[s.id]
		out[s.id] = CPOSchool{Owner: s.ownerKey, Allocation: [3]int{a.staff, a.partner, a.deficit}, Vector: d.vectors[s.id],
			Family: s.family, Holder: s.annualHolder, StaffClaims: s.annualStaffClaims}
	}
	return out, nil
}

// CPOPerson is one person of the people-first plan as people_plan leaves it.
type CPOPerson struct {
	Team, Key, Name, Role                       string
	Visits, ByType                              map[string]int
	Outreach, Trainings, ClusterTrainings       int
	Meetings, Assigned, Planned, PartnerSchools int
	ByPartner                                   map[string][3]int
}

// CountryOversightPeople is people.people_plan for the reader and a window,
// with no filter.
func CountryOversightPeople(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy, period, quarter string,
	month int, week string, now time.Time) ([]CPOPerson, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	var start *time.Time
	if week != "" {
		var y, wk int
		if _, err := fmtSscanWeek(week, &y, &wk); err == nil {
			d := isoWeekStart(y, wk)
			start = &d
		}
	}
	l := now.In(cpoLocation)
	w := cpoWindowFor(fy, period, quarter, month, start)
	d, err := buildCPODataset(ctx, db, scope, w, date(l.Year(), l.Month(), l.Day()))
	if err != nil {
		return nil, err
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	teams, err := cpoPeoplePlan(ctx, db, scope, d.schools, peopleWindow(w), cpoNarrow{}, outside)
	if err != nil {
		return nil, err
	}
	out := []CPOPerson{}
	for _, t := range teams {
		for _, ps := range t.people {
			bp := map[string][3]int{}
			for k, h := range ps.byPartner {
				bp[k] = [3]int{h.assigned, h.planned, len(h.schools)}
			}
			out = append(out, CPOPerson{Team: t.key, Key: ps.key, Name: ps.name, Role: ps.role, Visits: ps.visits, ByType: ps.visitsByType,
				Outreach: ps.outreach, Trainings: ps.trainings, ClusterTrainings: ps.clusterTrainings, Meetings: ps.meetings,
				Assigned: ps.partnerAssigned, Planned: ps.partnerPlanned, PartnerSchools: len(ps.partnerSchools), ByPartner: bp})
		}
	}
	return out, nil
}

// peopleWindow is service._people_window: a week reads the year so far.
func peopleWindow(w cpoWindow) cpoWindow {
	if w.period == "week" {
		w.start = w.fyStart
	}
	return w
}
