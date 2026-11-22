package planningmonitor

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
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
