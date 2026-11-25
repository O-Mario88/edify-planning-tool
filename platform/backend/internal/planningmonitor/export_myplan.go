package planningmonitor

import (
	"context"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// OwnReadiness adapts ReadOwn for myplan.Service.WithReadiness without creating
// a circular import between myplan and planningmonitor.
func OwnReadiness(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time) (*myplan.OwnReadiness, bool, error) {
	_, r, ok, err := ReadOwn(ctx, db, p, fy, now)
	if err != nil || !ok {
		return nil, ok, err
	}
	toLine := func(l Line) myplan.ReadinessLine {
		return myplan.ReadinessLine{
			Target:    l.Target,
			Planned:   l.Planned,
			Remaining: l.Remaining(),
			Over:      l.Over(),
			Percent:   l.Percent(),
			Required:  l.Required(),
			Tone:      l.Tone(),
		}
	}
	return &myplan.OwnReadiness{
		Score:                 r.Score(),
		SchoolsTotal:          r.SchoolsTotal(),
		StaffVisits:           toLine(r.StaffVisits()),
		StaffTrainings:        toLine(r.StaffTrainings()),
		PartnerVisits:         toLine(r.PartnerVisits()),
		PartnerTrainings:      toLine(r.PartnerTrainings()),
		PartnerAssignment:     toLine(r.PartnerAssignment()),
		ProjectAssignment:     toLine(r.ProjectAssignment()),
		PartnerBeyondStaff:    r.PartnerBeyondStaff,
		PartnerCoreSchools:    r.PartnerCoreSchools,
		SchoolsStaffScheduled: r.SchoolsStaffScheduled,
		SchoolsToRecruit:      r.SchoolsToRecruit,
		PortfolioVisits:       r.PortfolioVisits,
		ClientStaffAndPartner: r.ClientStaffAndPartner,
		CoreVisitsOver:        r.CoreVisitsOver,
		ProjectCeiling:        r.ProjectCeiling,
		ProjectAdded:          r.ProjectAdded,
		ProjectAssigned:       r.ProjectAssigned,
		PartnerVisitsAwaiting: r.PartnerVisitsAwaiting,
	}, true, nil
}

// OwnList is my_plan_views._readiness_list's schools for myplan.Service.
// WithReadinessList: own_monitor's schools behind key, by name; page picks
// the rows drawn, and only those read their visit gate (list_actions.offer
// asks the page's rows only). ok is false for a role that plans no visits.
func OwnList(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time, key string,
	page func(total int) (lo, hi int)) ([]myplan.ListSchool, int, bool, error) {
	o, _, ok, err := ReadOwn(ctx, db, p, fy, now)
	if err != nil || !ok {
		return nil, 0, ok, err
	}
	for _, s := range append(slices.Clip(o.Schools), o.Outreach...) {
		s.OfficerName = o.Name
	}
	found := listSchools([]*Officer{o}, key)
	lo, hi := page(len(found))
	gateRules, operational := schoolprofile.GateRules(), schooldirectory.OperationalFY(now)
	out := make([]myplan.ListSchool, 0, hi-lo)
	for _, s := range found[lo:hi] {
		g, err := visitgate.Of(ctx, db, gateRules, visitgate.School{ID: s.ID, Code: s.Code, Name: s.Name, Type: s.Type}, fy, operational)
		if err != nil {
			return nil, 0, true, err
		}
		out = append(out, myplan.ListSchool{
			ID: s.ID, Code: s.Code, Name: s.Name, Type: s.Type, District: s.District,
			Clustered: s.Clustered, ClusterID: s.ClusterID, ClusterName: s.ClusterName,
			StaffVisits: s.StaffVisits, HasPartner: s.hasPartner(), TrainingDone: s.TrainingDone,
			GroupTraining: s.GroupTraining, InSchoolTraining: s.InSchoolTraining, Meeting: s.Meeting,
			NeedsTraining: s.needsTraining(), InProject: s.InProject, CanAssign: g.CanAssignPartner,
		})
	}
	return out, len(found), true, nil
}
