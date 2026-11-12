package decisionlog

import (
	"context"
	"errors"
	"fmt"
	"slices"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PartnerTeam is what the existing pages withhold from a partner's team
// member (apps.partners.member_scope.page_withheld): whether this page is
// one, and which roles are a partner's.
type PartnerTeam struct {
	Withheld bool     `json:"withheld"`
	Roles    []string `json:"roles"`
}

// Member is how a partner login stands on a page withheld from team members.
type Member int

const (
	// NotAMember is a login that is not on a partner team it does not lead.
	NotAMember Member = iota
	// TeamMember is a field officer's own login on a team they do not lead:
	// the page is refused, as the existing feed refuses it.
	TeamMember
	// Undecided is a Partner Admin on a team whose partner record is not
	// theirs: whether they lead it is the existing partner scope's
	// (resolve_partner_ids), which Go does not read, so the page is left to
	// the existing application.
	Undecided
)

// PartnerTeamMember is member_scope.team_member's question for a page that
// withholds itself from team members: the reader's first active roster entry
// on an active partner (PartnerMember's order, role then name), led by them
// when the partner's own login is theirs.
func PartnerTeamMember(ctx context.Context, db schooldirectory.Querier, p auth.Principal, rule PartnerTeam) (Member, error) {
	if !rule.Withheld || !slices.Contains(rule.Roles, p.ActiveRole) {
		return NotAMember, nil
	}
	var owner *string
	err := db.QueryRow(ctx, `
SELECT p.user_id FROM partner_member m JOIN partner p ON p.id = m.partner_id
WHERE m.user_id = $1 AND m.active AND p.active_status
ORDER BY m.role, m.name, m.id LIMIT 1`, p.UserID).Scan(&owner)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return NotAMember, nil
	case err != nil:
		return NotAMember, fmt.Errorf("decisionlog: reading the reader's partner team: %w", err)
	case owner != nil && *owner == p.UserID:
		return NotAMember, nil
	case p.ActiveRole == "PartnerAdmin":
		return Undecided, nil
	}
	return TeamMember, nil
}
