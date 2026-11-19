package planningmonitor

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// What Home's Priority actions read from the monitor (internal/home).

// Schools are the held schools of everybody on the monitor (each officer's
// schools, not the outreach-only ones): a Lead's team's, for Home's rows.
func (m *Monitor) Schools() []*School {
	var out []*School
	for _, o := range m.Officers() {
		out = append(out, o.Schools...)
	}
	return out
}

// ReadOwnSchools is own_monitor's schools: the ones a CCEO or a Programme
// Lead holds (under both their ids, owner_ids) of the monitored types, each
// with the year's work counted as the monitor counts it.
func ReadOwnSchools(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time) ([]*School, error) {
	ids := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			ids = append(ids, id)
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
	if err := m.readSchools(ctx, `s.account_owner_id = ANY($1)`, []any{ids}); err != nil {
		return nil, err
	}
	return m.schoolOrder, nil
}

// HomeListCounts are Home's school rows over schools (in_list): not in an
// active cluster, no visit completed this year, a school that takes training
// with none completed, and no confirmed SSA this year.
func HomeListCounts(schools []*School) map[string]int {
	out := map[string]int{"not_clustered": 0, "not_visited": 0, "not_trained": 0, "no_ssa": 0}
	for _, s := range schools {
		if !s.Clustered {
			out["not_clustered"]++
		}
		if !s.visitDone() {
			out["not_visited"]++
		}
		if s.needsTraining() && !s.TrainingDone {
			out["not_trained"]++
		}
		if !s.SSADone {
			out["no_ssa"]++
		}
	}
	return out
}
