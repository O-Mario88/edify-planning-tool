package navigation

import (
	"context"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Service builds the reader's navigation.
type Service struct {
	db    schooldirectory.Querier
	rules Rules
}

// NewService reads partner teams through db.
func NewService(db schooldirectory.Querier) *Service {
	return &Service{db: db, rules: rules}
}

// Build answers the reader's navigation. served is false where the existing
// application still answers: a role the rules do not name, and a Partner
// Admin on a team whose partner record is not theirs (whether they lead it
// is the existing partner scope's).
func (s *Service) Build(ctx context.Context, p auth.Principal) (*screensv1.GetNavigationResponse, bool, error) {
	menu, ok := s.rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	member, err := decisionlog.PartnerTeamMember(ctx, s.db, p, s.rules.PartnerTeam)
	switch {
	case err != nil:
		return nil, false, err
	case member == decisionlog.Undecided:
		return nil, false, nil
	case member == decisionlog.TeamMember:
		if menu, ok = s.rules.TeamMembers[p.ActiveRole]; !ok {
			return nil, false, nil
		}
	}
	return s.response(menu), true, nil
}

// response is a fresh message for one menu; nothing in it is shared.
func (s *Service) response(menu Menu) *screensv1.GetNavigationResponse {
	out := &screensv1.GetNavigationResponse{Bottom: s.items(menu.Bottom)}
	for _, section := range menu.Sections {
		out.Sections = append(out.Sections, &screensv1.NavSection{Label: section.Label, Items: s.items(section.Items)})
	}
	return out
}

func (s *Service) items(items []Item) []*screensv1.NavItem {
	out := make([]*screensv1.NavItem, 0, len(items))
	for _, item := range items {
		out = append(out, &screensv1.NavItem{
			Label:   item.Label,
			Url:     item.URL,
			IconSvg: s.rules.Icons[item.Icon],
			PageKey: item.PageKey,
			Native:  item.Native,
		})
	}
	return out
}
