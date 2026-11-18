package personaltimeoff

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// Temporary Leave Coverage Assignments (leave_views.leave_coverage_view,
// pages/leave/leave_coverage.html): every coverage assignment, newest
// first, a Programme Lead's narrowed to those they are part of, searched by
// either side's name or email. Revoking one is the existing application's.

// CoveragePath is the page.
const CoveragePath = "/leave/coverage"

const (
	coveragePageParam = "coverages_page"
	coveragePageSize  = 50
	coverageEmpty     = "No coverage assignments configured."
	// revokeText is the Revoke confirmation as the feed reads it: the
	// trigger, the question, its body and the two buttons.
	revokeText = "Revoke Revoke this delegated access? It ends immediately. Anything the coverer has already done " +
		"stays as it is, and they lose access to the work from now on. Cancel Revoke access"
)

// coverageRole is what a role is given on the page.
type coverageRole struct {
	Page  bool               `json:"page"`
	Strip *decisionlog.Strip `json:"strip"`
}

// coverage is one TemporaryCoverageAssignment.
type coverage struct {
	covering, coveringRole, original, originalRole string
	start, end                                     time.Time
	scope, status                                  string
	revoked                                        bool
}

// state is the template's status pill: live, else revoked, else expired.
func (c coverage) state(now time.Time) (label string, live bool) {
	if c.status == "active" && !c.start.After(now) && !now.After(c.end) {
		return "active", true
	}
	if c.revoked {
		return "revoked", false
	}
	return "expired", false
}

// staffProfileOf is user.staff_profile_id: the reader's staff profile, or "".
func (s *Service) staffProfileOf(ctx context.Context, userID string) (string, error) {
	var id string
	err := s.db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1`, userID).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("personaltimeoff: reading the reader's staff profile: %w", err)
	}
	return id, nil
}

// readCoverages is the view's queryset: newest first, a Programme Lead's
// those they cover or are covered in, then the search over both sides.
func (s *Service) readCoverages(ctx context.Context, narrowTo *string, search string) ([]coverage, error) {
	args := []any{}
	where := []string{"true"}
	if narrowTo != nil {
		args = append(args, *narrowTo)
		where = append(where, fmt.Sprintf("(c.original_staff_id = $%[1]d OR c.covering_staff_id = $%[1]d)", len(args)))
	}
	if search != "" {
		args = append(args, likeContains(search))
		where = append(where, fmt.Sprintf(`(UPPER(cu.name::text) LIKE UPPER($%[1]d) OR UPPER(ou.name::text) LIKE UPPER($%[1]d)
  OR UPPER(ou.email::text) LIKE UPPER($%[1]d) OR UPPER(cu.email::text) LIKE UPPER($%[1]d))`, len(args)))
	}
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(cu.name, ''), COALESCE(cu.active_role, ''), COALESCE(ou.name, ''), COALESCE(ou.active_role, ''),
  c.start_datetime, c.end_datetime, c.scope, c.status, c.revoked_at IS NOT NULL
FROM temporary_coverage_assignment c
JOIN staff_profile cs ON cs.id = c.covering_staff_id JOIN "user" cu ON cu.id = cs.user_id
JOIN staff_profile os ON os.id = c.original_staff_id JOIN "user" ou ON ou.id = os.user_id
WHERE `+strings.Join(where, " AND ")+`
ORDER BY c.created_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("personaltimeoff: reading the coverage assignments: %w", err)
	}
	defer rows.Close()
	out := []coverage{}
	for rows.Next() {
		var c coverage
		if err := rows.Scan(&c.covering, &c.coveringRole, &c.original, &c.originalRole, &c.start, &c.end, &c.scope,
			&c.status, &c.revoked); err != nil {
			return nil, fmt.Errorf("personaltimeoff: reading a coverage assignment: %w", err)
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// likeContains is Django's icontains argument: the text with its LIKE
// wildcards escaped, inside wildcards.
func likeContains(text string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(text) + "%"
}

// coveragePage draws the page.
func (s *Service) coveragePage(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	r, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !r.Coverage.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	var narrowTo *string
	if r.Slug == "PL" {
		// Scoped by staff profile, which an account may not have yet:
		// without one, nothing.
		id, err := s.staffProfileOf(ctx, p.UserID)
		if err != nil {
			return nil, true, err
		}
		narrowTo = &id
	}
	list, err := s.readCoverages(ctx, narrowTo, strings.TrimSpace(query.Get("q")))
	if err != nil {
		return nil, true, err
	}
	blocks := []*screensv1.PageBlock{}
	if st := r.Coverage.Strip; st != nil {
		blocks = append(blocks, stripBlock(st))
	}
	blocks = append(blocks, panel("Coverage Assignments & Auditing", ""))
	blocks = append(blocks, coverageTable(list, query, s.now())...)
	header := &screensv1.PageHeader{Eyebrow: "Time & Availability", Title: "Temporary Leave Coverage Assignments",
		Description: "Audit temporary delegated permissions and revoke access windows manually",
		Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: CoveragePath}, true, nil
}

// stripBlock is the Leave workspace strip.
func stripBlock(st *decisionlog.Strip) *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Label: st.Label, Scrolls: st.Scrolls}
	for _, t := range st.Tabs {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

// person is a name over its role, as the feed joins the two lines.
func person(name, role string) string {
	return strings.TrimSpace(strings.TrimSpace(name) + " " + strings.TrimSpace(role))
}

// coverageTable is the assignments' table, fifty a page, and its pager.
func coverageTable(list []coverage, query url.Values, now time.Time) []*screensv1.PageBlock {
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Covering Staff"}, {Label: "Acting For (Absent)"},
		{Label: "Start Time"}, {Label: "End Time"}, {Label: "Permission Scope"}, {Label: "Status"},
		{Label: "Actions", Numeric: true}}}
	if len(list) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: coverageEmpty}}}}
	}
	page := tablepager.Paginate(len(list), coveragePageSize, query, coveragePageParam)
	stamp := func(t time.Time) string { return t.In(kampala).Format("2006-01-02 15:04") }
	for _, c := range list[page.Start:page.End] {
		label, live := c.state(now)
		action := "No actions"
		if live {
			action = revokeText
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: person(c.covering, c.coveringRole)}, {Text: person(c.original, c.originalRole)},
			{Text: stamp(c.start)}, {Text: stamp(c.end)},
			{Text: c.scope, Tone: "primary", Badge: true}, {Text: label, Tone: "primary", Badge: true}, {Text: action},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(list), coveragePageSize, query, coveragePageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
