package hrregister

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PeopleReachProfiles is people_reach read through scope_profiles, for the
// pages outside the HR registers that ask it: a WHERE clause on
// staff_profile `sp` (the reach alone, without the registers' live-record
// conditions), its arguments appended to args, and whether the reach is the
// whole organisation (reach.is_everything).
func PeopleReachProfiles(ctx context.Context, db schooldirectory.Querier, p auth.Principal, args []any) (string, []any, bool, error) {
	r, err := peopleReach(ctx, db, p)
	if err != nil {
		return "", nil, false, err
	}
	where, args := r.profiles(args)
	return where, args, r.kind == reachAll, nil
}
