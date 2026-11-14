// Package dataquality is the Data Quality Center
// (/admin-panel/data-quality-center): the schools' quality tiles, where each
// kind of issue is resolved, and the open issues by kind, as the existing
// page draws them (apps.frontend.views.extended_views
// .admin_data_quality_center_view and pages/admin/data_quality_center.html)
// and the app's feed reads them. Assigning and resolving stay with the
// existing application.
//
// The doors, tiles, sections and page size are exported to rules.json by
// `manage.py export_data_quality_center_rules`;
// apps/schools/test_data_quality_center_rules_export.py fails when the two
// differ.
package dataquality

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/admin-panel/data-quality-center"

const pageParam = "issues_page"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page           bool               `json:"page"`
		Strip          *decisionlog.Strip `json:"strip"`
		SetupQueue     bool               `json:"setup_queue"`
		SchoolProfiles bool               `json:"school_profiles"`
	} `json:"roles"`
	Tiles                [][3]string `json:"tiles"`
	Sections             [][2]string `json:"sections"`
	OperatingStatuses    []string    `json:"operating_statuses"`
	UnmatchedSSAStatuses []string    `json:"unmatched_ssa_statuses"`
	PageSize             int         `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.Tiles) == 0 || len(r.Sections) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("dataquality: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Service answers the page from the existing database.
type Service struct{ db schooldirectory.Querier }

// NewService is the page over db.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

// issue is one open issue's row.
type issue struct {
	schoolPK, code, school, field, value, fix string
	assigned                                  bool
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: t}}
}

func link(t, href string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{{Text: t, Href: href}}}}}
}

// Build answers Path.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	metrics := []*screensv1.PageMetric{}
	for _, t := range rules.Tiles {
		var n int
		if err := s.db.QueryRow(ctx, `SELECT count(*) FROM school WHERE deleted_at IS NULL AND operational_status = ANY($1) AND data_quality_status = $2`,
			rules.OperatingStatuses, t[1]).Scan(&n); err != nil {
			return nil, true, fmt.Errorf("dataquality: counting the schools: %w", err)
		}
		metrics = append(metrics, &screensv1.PageMetric{Label: t[0], Value: strconv.Itoa(n), Note: t[2]})
	}
	var unmatched int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM unmatched_ssa_record WHERE status = ANY($1)`, rules.UnmatchedSSAStatuses).Scan(&unmatched); err != nil {
		return nil, true, fmt.Errorf("dataquality: counting the unmatched SSA uploads: %w", err)
	}
	blocks := []*screensv1.PageBlock{}
	if role.Strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: role.Strip.Label, Scrolls: role.Strip.Scrolls}
		for _, x := range role.Strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: x.Label, Href: x.Href, Active: x.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	guides := []*screensv1.PagePanelItem{heading("Link Raw Staff Names"), text("Match schools imported via CSV with active staff profiles in the staff setup queue.")}
	if role.SetupQueue {
		guides = append(guides, link("Open setup queue →", "/admin-panel/staff-setup-queue"))
	}
	ssaHeading := "Link Unmatched SSAs"
	if unmatched > 0 {
		ssaHeading += " " + strconv.Itoa(unmatched)
	}
	guides = append(guides,
		heading("Cluster Client Schools"), text("Every client school must belong to a cluster group before scheduling training or meetings."),
		link("Open school directory →", "/schools?filter=unclustered"),
		heading("Resolve Duplicate Risks"), text("Review name and location duplicate risk flags to ensure directory accuracy."),
		link("Open duplicate review →", "/data-quality/duplicates"),
		heading(ssaHeading), text("Resolve SSA uploads mapped to nonexistent School IDs by linking them manually."),
		link("Open unmatched queue →", "/ssa/unmatched"))
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Data quality context", Metrics: metrics}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Quality Actions Needed", Subtitle: "Where each kind of issue below is resolved.", Items: guides}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: "Open Data Quality Issues"}})
	for _, sec := range rules.Sections {
		section, err := s.section(ctx, sec[0], sec[1], role.SchoolProfiles, query)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, section...)
	}
	header := &screensv1.PageHeader{Eyebrow: "Data assurance", Title: "Data Quality",
		Description: "Resolve coverage gaps, invalid relationships, duplicate risks and records that cannot yet support operational decisions."}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}, true, nil
}

// section is one issue type's card: its heading, a page of its open issues
// at operating schools, newest first (the model's order), and its pager. A
// kind with none is not drawn.
func (s *Service) section(ctx context.Context, title, kind string, links bool, query url.Values) ([]*screensv1.PageBlock, error) {
	const where = `FROM data_quality_issue i JOIN school s ON s.id = i.school_id
WHERE i.status = 'open' AND s.deleted_at IS NULL AND s.operational_status = ANY($1) AND i.issue_type = $2`
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*) `+where, rules.OperatingStatuses, kind).Scan(&total); err != nil {
		return nil, fmt.Errorf("dataquality: counting the %s issues: %w", kind, err)
	}
	if total == 0 {
		return nil, nil
	}
	size := rules.PageSize
	number, pages := closedschools.PageOf(query.Get(pageParam), total, size)
	rows, err := s.db.Query(ctx, `SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(i.field_name, ''), COALESCE(i.current_value, ''),
  COALESCE(i.suggested_fix, ''), COALESCE(i.assigned_to, '') <> '' `+where+` ORDER BY i.created_at DESC LIMIT $3 OFFSET $4`, rules.OperatingStatuses, kind, size, (number-1)*size)
	if err != nil {
		return nil, fmt.Errorf("dataquality: reading the %s issues: %w", kind, err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (issue, error) {
		var x issue
		return x, r.Scan(&x.schoolPK, &x.code, &x.school, &x.field, &x.value, &x.fix, &x.assigned)
	})
	if err != nil {
		return nil, fmt.Errorf("dataquality: reading the %s issues: %w", kind, err)
	}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "School ID"}, {Label: "School"}, {Label: "Suggested Fix"}, {Label: "Status"}, {Label: "Actions", Numeric: true}}}
	for _, x := range list {
		t.Rows = append(t.Rows, issueRow(x, links))
	}
	out := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title}}},
		{Kind: &screensv1.PageBlock_Table{Table: t}},
	}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(pageParam, number, pages, total, size, query, nil))
	}
	return out, nil
}

// issueRow is partials/data_quality/issue_row.html for an open issue: the
// school with the value that is wrong, the fix, whether someone holds it,
// and the row's two forms read as their buttons' words.
func issueRow(x issue, links bool) *screensv1.PageRow {
	dash := func(v string) string {
		if v == "" {
			return "—"
		}
		return v
	}
	name := x.school
	if x.value != "" {
		name += " " + x.field + ": " + x.value
	}
	school := &screensv1.PageCell{Text: closedschools.Collapse(name)}
	if links {
		school.Href = "/schools/" + x.schoolPK
	}
	status := "Unassigned"
	if x.assigned {
		status = "Assigned"
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: closedschools.Collapse(dash(x.code))}, school, {Text: closedschools.Collapse(dash(x.fix))}, {Text: status},
		{Text: "Assign to me Resolve"},
	}}
}
