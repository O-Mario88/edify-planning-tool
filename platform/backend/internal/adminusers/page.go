// Package adminusers builds the Admin's User Management page
// (/admin-panel/users: apps.frontend.views.extended_views.admin_users_view and
// pages/admin/users.html, as the existing feed reads them): the partner
// organisations with their logins' doors, then every account with its role,
// status and doors, filtered by role, status and the search, a table page at
// a time.
//
// It reads; it never writes. It hands on the Add User drawer (?drawer=add),
// a query it does not know, a deleted partner organisation (drawn through a
// template tag Go does not draw yet), a reader who is not the Admin and a
// role shown a workspace strip. The doors and words are exported to
// rules.json by `manage.py export_admin_users_rules`;
// apps/accounts/test_admin_users_rules_export.py fails when the two differ.
package adminusers

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
	"unicode"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/admin-panel/users"

//go:embed rules.json
var rulesJSON []byte

type role struct {
	Page                bool            `json:"page"`
	Strip               json.RawMessage `json:"strip"`
	ReadsEveryone       bool            `json:"reads_everyone"`
	ManagesPartners     bool            `json:"manages_partners"`
	ManagesPartnerUsers bool            `json:"manages_partner_users"`
	PurgesPartners      bool            `json:"purges_partners"`
}

var rules = func() (r struct {
	Roles              map[string]role   `json:"roles"`
	FilterRoles        []string          `json:"filter_roles"`
	UserSetupStates    map[string]string `json:"user_setup_states"`
	Interventions      map[string]string `json:"interventions"`
	PageSize           int               `json:"page_size"`
	QueryKeysNotPassed []string          `json:"query_keys_not_passed"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("adminusers: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.FilterRoles) == 0 || r.PageSize == 0 {
		panic("adminusers: rules.json lacks the doors, the roles or the page size")
	}
	return r
}()

// Service builds the page.
type Service struct{ db schooldirectory.Querier }

// NewService is the page over db.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

var known = map[string]bool{"q": true, "role": true, "status": true, "page": true, "partners_page": true}

// Build answers /admin-panel/users; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	r, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !r.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if !r.ReadsEveryone || (len(r.Strip) > 0 && string(r.Strip) != "null") {
		return nil, false, nil
	}
	for key, values := range query {
		if !known[key] || len(values) != 1 {
			return nil, false, nil
		}
	}
	var partners []partner
	if r.ManagesPartners {
		list, deleted, err := s.partners(ctx)
		if err != nil {
			return nil, true, err
		}
		if deleted {
			return nil, false, nil
		}
		partners = list
	}
	search := strings.TrimSpace(query.Get("q"))
	selectedRole := strings.TrimSpace(query.Get("role"))
	selectedStatus := strings.TrimSpace(query.Get("status"))
	total, number, users, err := s.users(ctx, search, selectedRole, selectedStatus, query.Get("page"))
	if err != nil {
		return nil, true, err
	}
	blocks := []*screensv1.PageBlock{}
	if r.ManagesPartners {
		blocks = append(blocks, partnerBlocks(partners, r, query)...)
	}
	blocks = append(blocks, filters(selectedRole, selectedStatus))
	blocks = append(blocks, userBlocks(users, total, number, query)...)
	h := &screensv1.PageHeader{Eyebrow: "Administration", Title: "User Management",
		Description: "Create and configure system users, reporting lines, and partner organisations"}
	if r.ManagesPartners {
		h.Actions = append(h.Actions, &screensv1.PageAction{Key: "add_partner", Label: "Add Partner", Enabled: true, Href: "/partners/create", Drawer: true})
	}
	h.Actions = append(h.Actions, &screensv1.PageAction{Key: "add_user", Label: "Add User", Enabled: true, Href: Path + "?drawer=add", Drawer: true})
	out := &screensv1.GetPageResponse{Header: h, Blocks: blocks, WebPath: Path}
	if r.PurgesPartners {
		out.Dialogs = []*screensv1.PageDialog{{Key: "showPartnerDeleteModal", Title: "Delete ?", Blocks: []*screensv1.PageBlock{
			{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Delete ?", Subtitle: "Delete permanently"}}}}}}
	}
	return out, true, nil
}

// partner is one organisation as its row shows it.
type partner struct {
	id, name, contact, phone, email, intervention, setup string
	regions, expertise, trainsOn                         []string
	active                                               bool
	loginID                                              string
}

// partners is every live organisation, the active first then by name, and
// whether any has been deleted.
func (s *Service) partners(ctx context.Context) ([]partner, bool, error) {
	rows, err := s.db.Query(ctx, `
SELECT p.id, p.name, COALESCE(p.contact_person, ''), COALESCE(p.phone, ''), COALESCE(p.email, ''),
  COALESCE(p.ssa_intervention, ''), COALESCE(p.user_setup_status, ''),
  CASE WHEN cardinality(COALESCE(p.region_names, '{}')) > 0 THEN p.region_names
       WHEN COALESCE(p.region_name, '') <> '' THEN ARRAY[p.region_name] ELSE '{}' END,
  COALESCE(p.expertise_areas, '{}'), COALESCE(p.trains_on, '{}'), p.active_status,
  COALESCE(u.id, ''), p.deleted_at IS NOT NULL
FROM partner p LEFT JOIN "user" u ON u.id = p.user_id AND u.deleted_at IS NULL
ORDER BY p.deleted_at ASC NULLS FIRST, p.active_status DESC, p.name, p.id`)
	if err != nil {
		return nil, false, fmt.Errorf("adminusers: reading the partners: %w", err)
	}
	deleted := false
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (partner, error) {
		var pa partner
		var gone bool
		err := row.Scan(&pa.id, &pa.name, &pa.contact, &pa.phone, &pa.email, &pa.intervention, &pa.setup,
			&pa.regions, &pa.expertise, &pa.trainsOn, &pa.active, &pa.loginID, &gone)
		deleted = deleted || gone
		return pa, err
	})
	if err != nil {
		return nil, false, fmt.Errorf("adminusers: reading the partners: %w", err)
	}
	return list, deleted, nil
}

// account is one user as its row shows it.
type account struct {
	id, name, email, role, status string
	active                        bool
}

// users is the accounts under the filters: how many, and the page asked,
// read as the paginator reads it — ordered by name alone, then a LIMIT and
// an OFFSET — so accounts sharing a name come in the database's own order,
// as on the existing page.
func (s *Service) users(ctx context.Context, search, role, status, page string) (int, int, []account, error) {
	where, args := []string{"u.deleted_at IS NULL"}, []any{}
	arg := func(v any) string { args = append(args, v); return fmt.Sprintf("$%d", len(args)) }
	if search != "" {
		t := arg("%" + strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(search) + "%")
		where = append(where, "(u.name ILIKE "+t+" OR u.email ILIKE "+t+" OR u.active_role ILIKE "+t+")")
	}
	if role != "" {
		r := arg(role)
		where = append(where, "(u.active_role = "+r+" OR u.roles @> ARRAY["+r+"]::varchar[])")
	}
	switch status {
	case "active":
		where = append(where, "u.is_active AND u.status = 'active'")
	case "inactive":
		where = append(where, "(NOT u.is_active OR u.status = 'inactive')")
	}
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM "user" u WHERE `+strings.Join(where, " AND "), args...).Scan(&total); err != nil {
		return 0, 0, nil, fmt.Errorf("adminusers: counting the accounts: %w", err)
	}
	number, _ := closedschools.PageOf(page, total, rules.PageSize)
	rows, err := s.db.Query(ctx, `SELECT u.id, COALESCE(u.name, ''), COALESCE(u.email, ''), COALESCE(u.active_role, ''),
  COALESCE(u.status, ''), u.is_active FROM "user" u WHERE `+strings.Join(where, " AND ")+
		fmt.Sprintf(` ORDER BY u.name ASC LIMIT %d OFFSET %d`, rules.PageSize, (number-1)*rules.PageSize), args...)
	if err != nil {
		return 0, 0, nil, fmt.Errorf("adminusers: reading the accounts: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (account, error) {
		var a account
		err := row.Scan(&a.id, &a.name, &a.email, &a.role, &a.status, &a.active)
		return a, err
	})
	if err != nil {
		return 0, 0, nil, fmt.Errorf("adminusers: reading the accounts: %w", err)
	}
	return total, number, list, nil
}

func cell(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: t} }

func badge(t string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: t, Tone: "primary", Badge: true}
}

func or(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

func title(s string) string {
	if s == "" {
		return s
	}
	r := []rune(strings.ToLower(s))
	r[0] = unicode.ToUpper(r[0])
	return string(r)
}

func menu(label, href string, drawer bool) *screensv1.PageAction {
	return &screensv1.PageAction{Key: "menu", Label: label, Enabled: true, Href: href, Drawer: drawer}
}

func partnerBlocks(list []partner, r role, query url.Values) []*screensv1.PageBlock {
	active := 0
	for _, pa := range list {
		if pa.active {
			active++
		}
	}
	head := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Partner Organisations", Subtitle: "External access",
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: fmt.Sprintf("%d active · %d total", active, len(list))}}}}}}
	columns := []*screensv1.PageColumn{{Label: "Organization"}, {Label: "Regions"}, {Label: "Contact"}, {Label: "Phone"},
		{Label: "Email"}, {Label: "Expertise"}, {Label: "SSA Intervention"}, {Label: "Status"}, {Label: "Actions", Numeric: true}}
	number, pages := closedschools.PageOf(query.Get("partners_page"), len(list), rules.PageSize)
	start := (number - 1) * rules.PageSize
	rows := []*screensv1.PageRow{}
	for _, pa := range list[start:min(start+rules.PageSize, len(list))] {
		expertise := strings.Join(pa.expertise, ", ")
		if expertise == "" {
			expertise = or(strings.Join(pa.trainsOn, ", "), "—")
		}
		intervention := "General Support"
		if pa.intervention != "" {
			intervention = rules.Interventions[pa.intervention]
			if intervention == "" {
				intervention = title(strings.ReplaceAll(pa.intervention, "_", " "))
			}
		}
		state := "Inactive"
		if pa.active {
			state = "Active"
		}
		actions := &screensv1.PageCell{}
		if r.ManagesPartnerUsers {
			if pa.loginID != "" {
				actions.Actions = append(actions.Actions,
					menu("Configure login", Path+"/"+pa.loginID, false),
					menu("Reset password", Path+"/"+pa.loginID+"?drawer=password", true),
					menu("Change login", "/partners/"+pa.id+"/user-setup", true))
			} else {
				actions.Actions = append(actions.Actions, menu("Configure login", "/partners/"+pa.id+"/user-setup", true))
			}
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: pa.name, Href: "/partners/" + pa.id}, cell(or(strings.Join(pa.regions, ", "), "—")),
			cell(or(pa.contact, "Not recorded")), cell(or(pa.phone, "—")), cell(or(pa.email, "—")), cell(expertise),
			badge(intervention), cell(state + " " + rules.UserSetupStates[pa.setup]), actions}})
	}
	if len(list) == 0 {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell("No partner organisations yet Use Add Partner to create the first organisation.")}})
	}
	out := []*screensv1.PageBlock{head, {Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: columns, Rows: rows}}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel("partners_page", number, pages, len(list), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return out
}

func filters(role, status string) *screensv1.PageBlock {
	roles := []*screensv1.PageFilterOption{{Value: "", Label: "All Roles"}}
	for _, r := range rules.FilterRoles {
		roles = append(roles, &screensv1.PageFilterOption{Value: r, Label: r})
	}
	statuses := []*screensv1.PageFilterOption{{Value: "", Label: "All Statuses"}, {Value: "active", Label: "Active"}, {Value: "inactive", Label: "Inactive"}}
	if role != "" && !in(rules.FilterRoles, role) {
		role = ""
	}
	if status != "active" && status != "inactive" {
		status = ""
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
		{Name: "role", Value: role, Options: roles, Caption: "Role:"},
		{Name: "status", Value: status, Options: statuses, Caption: "Status:"},
	}}}}
}

func in(set []string, v string) bool {
	for _, s := range set {
		if s == v {
			return true
		}
	}
	return false
}

func initials(name string) string {
	r := []rune(name)
	return strings.ToUpper(string(r[:min(2, len(r))]))
}

func userBlocks(list []account, total, number int, query url.Values) []*screensv1.PageBlock {
	columns := []*screensv1.PageColumn{{Label: "User Details"}, {Label: "Email Address"}, {Label: "Primary Role"},
		{Label: "Status"}, {Label: "Actions", Numeric: true}}
	_, pages := closedschools.PageOf(query.Get("page"), total, rules.PageSize)
	rows := []*screensv1.PageRow{}
	for _, a := range list {
		who := initials(a.name) + " " + a.name
		if strings.Contains(a.email, "pending.") {
			who += " Needs Real Email"
		}
		status := "Active"
		if !a.active {
			status = title(a.status)
			if a.status != "" {
				r := []rune(a.status)
				status = strings.ToUpper(string(r[0])) + string(r[1:])
			}
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(who), cell(a.email), badge(or(a.role, "CCEO")), badge(status),
			{Actions: []*screensv1.PageAction{menu("Configure", Path+"/"+a.id, false), menu("Reset password", Path+"/"+a.id+"?drawer=password", true)}},
		}})
	}
	if len(list) == 0 {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell("No user accounts found matching your query.")}})
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: columns, Rows: rows}}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel("page", number, pages, total, rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return out
}
