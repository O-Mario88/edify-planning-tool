package schoolprofile

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// RunnableActivity is what deciding whether the reader may run a piece of
// work reads of it, for the Calendar's tick boxes (internal/calendarpage).
type RunnableActivity struct {
	StaffID, MonitorID, SchoolID, SchoolOwner string
	ClusterID, ClusterDistrict, ClusterLead   string
	HasSchool, ClusterLive, InCountry         bool
}

// MayRun is profile_activities._may_run: the scope, scheduling and
// execution checks the complete, reschedule and cancel services run.
func MayRun(ctx context.Context, db Querier, p auth.Principal, scope schooldirectory.Scope, a RunnableActivity) (bool, error) {
	r := reader{p: p, scope: scope, s: &Service{db: db}}
	return r.mayRun(ctx, listedActivity{
		staffID: a.StaffID, monitorID: a.MonitorID, schoolID: a.SchoolID, schoolOwner: a.SchoolOwner,
		hasSchool: a.HasSchool, clusterID: a.ClusterID, clusterDistrict: a.ClusterDistrict,
		clusterLead: a.ClusterLead, clusterLive: a.ClusterLive, inCountry: a.InCountry,
	})
}

// ActivityInCountry is scoping.activity_country_q over an activity a with
// its school s and cluster cl, the country being argument n.
func ActivityInCountry(n int) string { return activityInCountry(n) }
