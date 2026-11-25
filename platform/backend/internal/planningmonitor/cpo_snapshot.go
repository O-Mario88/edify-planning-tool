package planningmonitor

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// cpoSnapshot is service.Snapshot: the tree and how it was read.
type cpoSnapshot struct {
	tree    *cpoTree
	filters cpoFilters
	data    *cpoDataset
	leads   [][2]string
	people  []*cpoTeam
	roster  []cpoRosterOwner
}

// cpoWindowOf is Filters.window.
func cpoWindowOf(f cpoFilters) cpoWindow {
	var start *time.Time
	period := f.period
	if f.period == "week" && f.week != "" {
		var y, wk int
		if _, err := fmtSscanWeek(f.week, &y, &wk); err == nil {
			d := isoWeekStart(y, wk)
			start = &d
		}
	}
	if period == "week" && start == nil {
		period = "fy"
	}
	return cpoWindowFor(f.fy, period, f.quarter, f.month, start)
}

// buildCPOSnapshot is service._snapshot over a freshly built dataset (the
// existing page reads a cached one; Go reads the records each time).
func buildCPOSnapshot(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, f cpoFilters, today time.Time) (*cpoSnapshot, error) {
	w := cpoWindowOf(f)
	d, err := buildCPODataset(ctx, db, scope, w, today)
	if err != nil {
		return nil, err
	}
	m := &monitor{db: db}
	roster, err := m.roster(ctx, lensOf(scope))
	if err != nil {
		return nil, err
	}
	owners := []cpoRosterOwner{}
	leads := [][2]string{}
	for _, t := range roster {
		key, name := t.lead.Key, t.lead.Name
		if !t.noLead {
			leads = append(leads, [2]string{key, name})
		}
		for _, p := range t.people {
			role := rules.CCEORole
			if p.lead {
				role = rules.ProgramLeadRole
			}
			owners = append(owners, cpoRosterOwner{key: p.key, name: p.name, role: role, leadKey: key})
		}
	}
	var keep []string
	if f.planningStatus != "" || f.partner != "" {
		keep = []string{}
		var only *string
		if f.partner != "" {
			only = &f.partner
		}
		for _, s := range d.schools {
			o := d.owners[s.ownerKey]
			lead := rules.CountryOversight.NoLead[0]
			if o != nil {
				lead = o.leadKey
			}
			if !s.governed() || !keepsPlace(f, s, lead) {
				continue
			}
			if statusMatches(claimsFor(s, d.allocations[s.id], w, f.channel, only), f) {
				keep = append(keep, s.id)
			}
		}
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	people, err := cpoPeoplePlan(ctx, db, scope, d.schools, peopleWindow(w), cpoNarrow{region: f.region, district: f.district,
		schoolType: f.schoolType, clusterStatus: f.clusterStatus, channel: f.channel, partner: f.partner, schoolIDs: keep}, outside)
	if err != nil {
		return nil, err
	}
	return &cpoSnapshot{tree: foldTree(d, f, people, owners, leads), filters: f, data: d, leads: leads, people: people, roster: owners}, nil
}
