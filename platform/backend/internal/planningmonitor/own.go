package planningmonitor

import (
	"context"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// ReadOwn is planning_monitor.own_monitor(principal, fy): a Programme Lead's or
// CCEO's own schools, planned visits, partner work, and project places, folded
// into their personal Readiness summary. Returns (nil, Readiness{}, false, nil)
// for any role that does not plan visits.
func ReadOwn(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time) (*Officer, Readiness, bool, error) {
	role := planningRole(p.Roles, p.ActiveRole)
	code := rules.RoleCodes[role]
	if code == "" {
		return nil, Readiness{}, false, nil
	}
	ids := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return nil, Readiness{}, false, nil
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, Readiness{}, false, err
	}
	if outside == nil {
		outside = []string{}
	}
	m := newMonitor(db, fy, now, outside)
	if err := m.readSchools(ctx, `s.account_owner_id = ANY($1)`, []any{ids}); err != nil {
		return nil, Readiness{}, false, err
	}
	key := p.StaffProfileID
	if key == "" {
		key = ids[0]
	}
	name := strings.TrimSpace(p.Email)
	officer := &Officer{
		Key:          key,
		Name:         name,
		VisitsTarget: rules.VisitTargets[code],
		Role:         code,
		IDs:          ids,
		Schools:      m.schoolOrder,
		Outreach:     m.outreachOrder,
	}
	m.leadOrder = []*Lead{{Key: key, Name: name, Officers: []*Officer{officer}}}
	for _, count := range []func(context.Context) error{m.countPlannedVisits, m.countPartnerWork, m.countProjectPlaces} {
		if err := count(ctx); err != nil {
			return nil, Readiness{}, false, err
		}
	}
	return officer, officer.Readiness(), true, nil
}

// SchoolsTotal returns the total number of operating schools held in r.Inventory.
func (r Readiness) SchoolsTotal() int {
	return r.schools(func(t *TypeInventory) int { return t.Total })
}

// Score returns the plain average readiness score across the four pillars.
func (r Readiness) Score() int { return r.score() }

// Remaining returns how many units remain toward the line's target.
func (l Line) Remaining() int { return l.remaining() }

// Over returns how many units exceed the line's target.
func (l Line) Over() int { return l.over() }

// Percent returns the whole percentage toward the line's target (0..100).
func (l Line) Percent() int { return l.percent() }

// Required returns whether the line has a positive target.
func (l Line) Required() bool { return l.required() }

// Tone returns the semantic tone for the line's completion state.
func (l Line) Tone() string { return l.tone() }
