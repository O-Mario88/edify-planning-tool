// Package rolesmatrix is the Roles & Permissions matrix
// (/admin-panel/roles-permissions): every permission in the RBAC tables,
// grouped by its key's namespace, against every role that holds one, as the
// existing page draws it (apps.frontend.views.extended_views
// .admin_roles_permissions_view and pages/admin/roles_permissions.html) and
// the app's feed reads it. The page is read-only.
//
// The door, the roles' order and the page size are exported to rules.json by
// `manage.py export_roles_matrix_rules`;
// apps/accounts/test_roles_matrix_rules_export.py fails when the two differ.
package rolesmatrix

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/admin-panel/roles-permissions"

const pageParam = "permission_groups_page"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles []string `json:"page_roles"`
	RoleOrder []string `json:"role_order"`
	PageSize  int      `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.RoleOrder) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("rolesmatrix: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Service answers the matrix from the existing database.
type Service struct{ db schooldirectory.Querier }

// NewService is the matrix over db.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

// group is one key namespace and its permissions' labels, in key order.
type group struct {
	prefix, name string
	labels       []string
}

// Build answers Path; every other path is not this package's.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	roles, err := s.roles(ctx)
	if err != nil {
		return nil, true, err
	}
	rows, err := s.db.Query(ctx, `SELECT key FROM permission ORDER BY key`)
	if err != nil {
		return nil, true, fmt.Errorf("rolesmatrix: reading the permissions: %w", err)
	}
	defer rows.Close()
	byPrefix := map[string]*group{}
	for rows.Next() {
		var key string
		if err := rows.Scan(&key); err != nil {
			return nil, true, fmt.Errorf("rolesmatrix: reading the permissions: %w", err)
		}
		prefix, rest, _ := strings.Cut(key, ".")
		g, ok := byPrefix[prefix]
		if !ok {
			g = &group{prefix: prefix, name: humanize(prefix)}
			byPrefix[prefix] = g
		}
		label := humanize(prefix)
		if rest != "" {
			label = humanize(rest)
		}
		g.labels = append(g.labels, label)
	}
	if err := rows.Err(); err != nil {
		return nil, true, fmt.Errorf("rolesmatrix: reading the permissions: %w", err)
	}
	groups := make([]*group, 0, len(byPrefix))
	for _, g := range byPrefix {
		groups = append(groups, g)
	}
	slices.SortFunc(groups, func(a, b *group) int { return strings.Compare(a.prefix, b.prefix) })
	return page(roles, groups, query), true, nil
}

// roles are the roles that hold a permission, in EdifyRole's order, then any
// other in name order.
func (s *Service) roles(ctx context.Context) ([]string, error) {
	rows, err := s.db.Query(ctx, `SELECT DISTINCT role FROM role_permission`)
	if err != nil {
		return nil, fmt.Errorf("rolesmatrix: reading the roles: %w", err)
	}
	defer rows.Close()
	held := []string{}
	for rows.Next() {
		var role string
		if err := rows.Scan(&role); err != nil {
			return nil, fmt.Errorf("rolesmatrix: reading the roles: %w", err)
		}
		held = append(held, role)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("rolesmatrix: reading the roles: %w", err)
	}
	out := []string{}
	for _, r := range rules.RoleOrder {
		if slices.Contains(held, r) {
			out = append(out, r)
		}
	}
	extra := []string{}
	for _, r := range held {
		if !slices.Contains(rules.RoleOrder, r) {
			extra = append(extra, r)
		}
	}
	slices.Sort(extra)
	return append(out, extra...), nil
}

// humanize is _humanize_rbac_token: a space before each capital that
// follows a lower-case letter or digit, underscores as spaces, the first
// letter capitalised.
func humanize(token string) string {
	var b strings.Builder
	prev := rune(0)
	for _, r := range token {
		if r >= 'A' && r <= 'Z' && ((prev >= 'a' && prev <= 'z') || (prev >= '0' && prev <= '9')) {
			b.WriteRune(' ')
		}
		b.WriteRune(r)
		prev = r
	}
	spaced := strings.TrimSpace(strings.ReplaceAll(b.String(), "_", " "))
	if spaced == "" {
		return token
	}
	first := []rune(spaced)
	first[0] = unicode.ToUpper(first[0])
	return string(first)
}

// page is pages/admin/roles_permissions.html as the feed reads it: one
// table, each group's heading row then a row per permission. A role's cell
// is a pill holding only an icon, granted or not, which the feed reads as an
// empty badge either way.
func page(roles []string, groups []*group, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Administration", Title: "Roles & Permissions Matrix",
		Description: "Review operational boundaries, read/write access, and workflow approvals for every role"}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Permission"}}}
	for _, r := range roles {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: humanize(r)})
	}
	number, pages := closedschools.PageOf(query.Get(pageParam), len(groups), rules.PageSize)
	shown := groups[min((number-1)*rules.PageSize, len(groups)):min(number*rules.PageSize, len(groups))]
	for _, g := range shown {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: g.name}}})
		for _, l := range g.labels {
			cells := []*screensv1.PageCell{{Text: l}}
			for range roles {
				cells = append(cells, &screensv1.PageCell{Tone: "primary", Badge: true})
			}
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
		}
	}
	if len(groups) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No permissions defined."}}}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(pageParam, number, pages, len(groups), rules.PageSize, query, nil))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}
