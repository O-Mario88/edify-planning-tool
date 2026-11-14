// Package partnerusers is the Partner Admin's Users page (/partner/users):
// the organisation's team as its leader sees it, each person's role,
// contact, login and schools, with the menu that assigns their schools and
// sets up their login, as the existing page draws it
// (apps.frontend.views.partner_views.partner_users_view, _team_roster,
// pages/partner/users.html and partials/partners/team_table.html) and the
// app's feed reads it. Whose team it is and what each member holds come from
// the gateway's partner team service (internal/teams); adding, removing and
// changing members stay with the drawers.
//
// The doors, labels and limits are exported to rules.json by
// `manage.py export_partner_users_rules`;
// apps/partners/test_partner_users_rules_export.py fails when the two differ.
package partnerusers

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teams"
)

// Path is the page.
const Path = "/partner/users"

// dashboard is where render_access_denied sends a plain page load.
const dashboard = "/dashboard"

const pageParam = "roster_page"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles          []string          `json:"page_roles"`
	MemberRoles        map[string]string `json:"member_roles"`
	PageSize           int               `json:"page_size"`
	QueryKeysNotPassed []string          `json:"query_keys_not_passed"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.MemberRoles) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("partnerusers: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Teams reads a partner organisation's team: the caller's own when
// partnerID is empty (teams.PartnerService.Team).
type Teams interface {
	Team(ctx context.Context, principal auth.Principal, partnerID string) (teams.PartnerTeam, error)
}

// Service answers the page.
type Service struct{ teams Teams }

// NewService is the page over the partner team service.
func NewService(t Teams) *Service { return &Service{teams: t} }

// Build answers /partner/users; every other path is not this page's.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	team, err := s.teams.Team(ctx, p, "")
	var refused *teams.Refused
	switch {
	case errors.As(err, &refused):
		// No organisation of their own, or not one they lead: the view's
		// render_access_denied sends a page load to the dashboard.
		return &screensv1.GetPageResponse{Redirect: dashboard}, true, nil
	case err != nil:
		return nil, true, fmt.Errorf("partnerusers: reading the team: %w", err)
	case !team.LeadsTeam:
		return &screensv1.GetPageResponse{Redirect: dashboard}, true, nil
	}
	return page(team, query), true, nil
}

func collapse(text string) string { return closedschools.Collapse(text) }

// contact is the member's phone and email as the cell writes them side by
// side (the feed reads them as one run of text), the email its link.
func contact(m teams.Member) *screensv1.PageCell {
	if m.Phone == "" && m.Email == "" {
		return &screensv1.PageCell{Text: "—"}
	}
	cell := &screensv1.PageCell{Text: collapse(m.Phone + m.Email)}
	if m.Email != "" {
		cell.Href = "mailto:" + m.Email
	}
	return cell
}

// login is the member's sign-in: its email and state, or none.
func login(m teams.Member) string {
	switch {
	case m.Login == nil:
		return "No login"
	case m.Login.IsActive:
		return collapse(m.Login.Email + " · Active")
	case m.Login.Status == "pending_invited":
		return collapse(m.Login.Email + " · Invited")
	}
	return collapse(m.Login.Email + " · Deactivated")
}

// menu is the row's Actions menu as the feed reads it: its drawer buttons
// (the schools the member looks after, and their login), not its forms
// (activate or deactivate the login, remove from the roster). The page's
// reader leads the team, so both drawers are offered.
func menu(partnerID string, m teams.Member) *screensv1.PageCell {
	base := "/partners/" + partnerID + "/members/" + m.ID
	loginLabel := "Set up login"
	if m.Login != nil {
		loginLabel = "Reset password"
	}
	return &screensv1.PageCell{Actions: []*screensv1.PageAction{
		{Key: "menu", Label: "Assign schools", Enabled: true, Href: base + "/schools", Drawer: true},
		{Key: "menu", Label: loginLabel, Enabled: true, Href: base + "/login", Drawer: true},
	}}
}

func role(value string) string {
	if l, ok := rules.MemberRoles[value]; ok {
		return l
	}
	return value
}

func page(team teams.PartnerTeam, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Field Work", Title: "Users",
		Description: collapse(team.PartnerName + "'s team: add a member, give them a login, and choose the schools they schedule.")}
	if team.Roster {
		header.Actions = []*screensv1.PageAction{pageheader.Drawer("Add member", "/partners/"+team.PartnerID+"/members/drawer", false)}
	}
	line := strconv.Itoa(len(team.Members)) + " on the roster. A member with a login sees only the schools assigned to them, and schedules them."
	if len(team.Members) == 0 {
		// The empty state's message under the card's title and line.
		return &screensv1.GetPageResponse{Header: header, WebPath: Path, Blocks: []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "Team members", Subtitle: line,
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: "Nobody on the roster yet."}}},
		}}}}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Team members", Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: line}}},
	}}}}
	t := &screensv1.PageTable{}
	for _, c := range []string{"Name", "Role", "Contact", "Login", "Schools"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	if team.Roster {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Numeric: true})
	}
	number, pages := closedschools.PageOf(query.Get(pageParam), len(team.Members), rules.PageSize)
	for _, m := range team.Members[(number-1)*rules.PageSize : min(number*rules.PageSize, len(team.Members))] {
		cells := []*screensv1.PageCell{
			{Text: collapse(m.Name + m.Title)},
			{Text: collapse(role(m.Role))},
			contact(m),
			{Text: login(m)},
			{Text: strconv.Itoa(m.Schools)},
		}
		if team.Roster {
			cells = append(cells, menu(team.PartnerID, m))
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(pageParam, number, pages, len(team.Members), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}
