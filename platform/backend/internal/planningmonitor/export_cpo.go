package planningmonitor

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
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
