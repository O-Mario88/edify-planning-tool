package trainingsummary

import (
	"context"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// TeamMember is one officer a Programme Lead leads.
type TeamMember struct {
	StaffID, UserID string
	// Name is user.name ("" when blank).
	Name string
}

// TeamMembers is hr.team_roster.team_members for a lead working in their own
// role (the To-Do page's coaching rows read it): the live CCEOs they, and any
// Programme Lead they cover, supervise, by name.
func TeamMembers(ctx context.Context, q schooldirectory.Querier, profileID string, now time.Time) ([]TeamMember, error) {
	found, err := teamMembers(ctx, q, profileID, now)
	if err != nil {
		return nil, err
	}
	out := make([]TeamMember, len(found))
	for i, p := range found {
		out[i] = TeamMember{StaffID: p.id, UserID: p.userID, Name: p.name}
	}
	return out, nil
}
