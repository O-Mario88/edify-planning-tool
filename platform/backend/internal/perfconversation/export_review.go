package perfconversation

import (
	"context"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ReviewerRoles is REVIEWER_ROLE_FOR: the roles that review someone working
// in role.
func ReviewerRoles(role string) []string { return rules.ReviewerRoles[role] }

// ReviewedRoles is reviewees_of's reviewable roles: those a reader working in
// role reviews.
func ReviewedRoles(role string) []string {
	out := []string{}
	for reviewee, reviewers := range rules.ReviewerRoles {
		if slices.Contains(reviewers, role) {
			out = append(out, reviewee)
		}
	}
	slices.Sort(out)
	return out
}

// Reviews is review_authority.is_reviewer_of for the People record target
// (working in targetRole) and the reader's own People record viewer.
func Reviews(ctx context.Context, db schooldirectory.Querier, target, targetRole, viewer string, now time.Time) (bool, error) {
	if viewer == "" {
		return false, nil
	}
	return (&Service{db: db}).reviews(ctx, person{id: target, role: targetRole}, viewer, now)
}
