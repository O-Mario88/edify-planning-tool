// Package ownership is Ownership Transfers (/ownership-transfers/): the
// targets a transfer left to reconcile, the district transfer card and the
// transfer history, as the existing page draws them
// (apps.frontend.views.ownership_views.ownership_transfers_view and
// pages/schools/ownership_transfers.html) and the app's feed reads them. A
// transfer's preview (?district=…&from_staff=…) is counted by the existing
// application, which also takes every transfer and reconciliation.
//
// The doors, link roles, labels and limits are exported to rules.json by
// `manage.py export_ownership_transfers_rules`;
// apps/schools/test_ownership_transfers_rules_export.py fails when the two
// differ.
package ownership

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/ownership-transfers/"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles             []string          `json:"page_roles"`
	DistrictTransferRoles []string          `json:"district_transfer_roles"`
	DistrictProfileRoles  []string          `json:"district_profile_roles"`
	OpenActivityDecisions map[string]string `json:"open_activity_decisions"`
	RequiredReconcile     string            `json:"required_reconciliation"`
	Limits                struct {
		Batches         int `json:"batches"`
		Transfers       int `json:"transfers"`
		Reconciliations int `json:"reconciliations"`
	} `json:"limits"`
	PageSize int `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || r.Limits.Transfers == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("ownership: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Service answers the page from the existing database.
type Service struct{ db schooldirectory.Querier }

// NewService is the page over db.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

// moved is one history or reconciliation row.
type moved struct {
	districtID, district, schoolCode, school string
	from                                     *string
	to, decision, reason, note               string
	effective                                time.Time
	count, activities                        int
}

// Build answers Path. A preview asks the existing application to count it.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if strings.TrimSpace(query.Get("district")) != "" && strings.TrimSpace(query.Get("from_staff")) != "" {
		return nil, false, nil
	}
	staffName := func(alias string) string {
		return fmt.Sprintf(`(SELECT u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.id = %s)`, alias)
	}
	batches, err := s.read(ctx, `SELECT d.id, d.name, '', '', `+staffName("b.from_staff_id")+`, COALESCE(`+staffName("b.to_staff_id")+`, ''),
  b.open_activity_decision, b.reason, '', b.effective_date, b.school_count, b.activities_transferred
FROM district_portfolio_transfer b JOIN district d ON d.id = b.district_id ORDER BY b.created_at DESC LIMIT $1`, rules.Limits.Batches)
	if err != nil {
		return nil, true, err
	}
	transfers, err := s.read(ctx, `SELECT '', '', COALESCE(s.school_id, ''), s.name, `+staffName("t.from_staff_id")+`, COALESCE(`+staffName("t.to_staff_id")+`, ''),
  t.open_activity_decision, t.reason, '', t.effective_date, 0, COALESCE(jsonb_array_length(t.transferred_activity_ids), 0)
FROM school_ownership_transfer t JOIN school s ON s.id = t.school_id WHERE t.batch_id IS NULL ORDER BY t.created_at DESC LIMIT $1`, rules.Limits.Transfers)
	if err != nil {
		return nil, true, err
	}
	reconcile, err := s.read(ctx, `SELECT '', '', COALESCE(s.school_id, ''), s.name, NULL, COALESCE(`+staffName("t.to_staff_id")+`, ''),
  '', '', t.target_reconciliation_note, t.effective_date, 0, 0
FROM school_ownership_transfer t JOIN school s ON s.id = t.school_id WHERE t.target_reconciliation_status = $2 ORDER BY t.created_at DESC LIMIT $1`,
		rules.Limits.Reconciliations, rules.RequiredReconcile)
	if err != nil {
		return nil, true, err
	}
	return page(p, batches, transfers, reconcile, query), true, nil
}

func (s *Service) read(ctx context.Context, sql string, args ...any) ([]moved, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("ownership: reading the transfers: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (moved, error) {
		var m moved
		return m, r.Scan(&m.districtID, &m.district, &m.schoolCode, &m.school, &m.from, &m.to, &m.decision, &m.reason, &m.note,
			&m.effective, &m.count, &m.activities)
	})
	if err != nil {
		return nil, fmt.Errorf("ownership: reading the transfers: %w", err)
	}
	return list, nil
}

func cell(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: closedschools.Collapse(t)} }

func columns(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, len(labels))
	for i, l := range labels {
		out[i] = &screensv1.PageColumn{Label: l}
	}
	return out
}

func panel(title string, lines ...string) *screensv1.PageBlock {
	p := &screensv1.PagePanel{Title: title}
	for _, l := range lines {
		p.Items = append(p.Items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: l}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: p}}
}

func plural(n int, word string) string {
	if n == 1 {
		return strconv.Itoa(n) + " " + word
	}
	return strconv.Itoa(n) + " " + word + "s"
}

func decision(m moved) string {
	if l, ok := rules.OpenActivityDecisions[m.decision]; ok {
		return l
	}
	return m.decision
}

// paged is a table a page at a time, its pager past one page; lead rows
// (the batches) head every page.
func paged(t *screensv1.PageTable, lead, rows []*screensv1.PageRow, param string, query url.Values) []*screensv1.PageBlock {
	number, pages := closedschools.PageOf(query.Get(param), len(rows), rules.PageSize)
	t.Rows = append(lead, rows[min((number-1)*rules.PageSize, len(rows)):min(number*rules.PageSize, len(rows))]...)
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(param, number, pages, len(rows), rules.PageSize, query, nil))
	}
	return out
}

// page is pages/schools/ownership_transfers.html as the feed reads it. The
// preview form and a reconciliation's form are not read.
func page(p auth.Principal, batches, transfers, reconcile []moved, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Portfolio administration", Title: "Ownership Transfers",
		Description: "Move a district portfolio between staff, and reconcile the targets a transfer affects. A school's own owner is reassigned from its profile."}
	blocks := []*screensv1.PageBlock{}
	if len(reconcile) > 0 {
		rows := []*screensv1.PageRow{}
		for _, m := range reconcile {
			code := m.schoolCode
			if code == "" {
				code = "—"
			}
			rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				cell(code), {Text: closedschools.Collapse(m.school), Href: "/schools/" + m.schoolCode}, cell(m.to),
				cell(m.effective.Format("2 Jan 2006")), cell(m.note), {},
			}})
		}
		blocks = append(blocks, panel("Target Reconciliation Required", "Approved allocations counted a portfolio that has moved. The figures are unchanged; reconcile them through the amendment workflow, then record it here."))
		blocks = append(blocks, paged(&screensv1.PageTable{Columns: columns("School ID", "School", "Moved to", "Effective", "Note", "Record")}, nil, rows, "reconcile_page", query)...)
	}
	if slices.Contains(rules.DistrictTransferRoles, p.ActiveRole) {
		blocks = append(blocks, panel("Reassign District Portfolio Owner"))
	}
	from := func(m moved) string {
		if m.from == nil || *m.from == "" {
			return "Unassigned"
		}
		return *m.from
	}
	lead := []*screensv1.PageRow{}
	links := slices.Contains(rules.DistrictProfileRoles, p.ActiveRole)
	for _, m := range batches {
		what := &screensv1.PageCell{Text: closedschools.Collapse(plural(m.count, "school") + " · " + m.district)}
		if links {
			what.Href = "/districts/" + m.districtID
		}
		lead = append(lead, &screensv1.PageRow{Cells: []*screensv1.PageCell{what, cell(from(m)), cell(m.to),
			cell(m.effective.Format("2 Jan 2006")), cell(decision(m) + " · " + strconv.Itoa(m.activities) + " moved"), cell(m.reason)}})
	}
	rows := []*screensv1.PageRow{}
	for _, m := range transfers {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(m.school), Href: "/schools/" + m.schoolCode}, cell(from(m)), cell(m.to),
			cell(m.effective.Format("2 Jan 2006")), cell(decision(m) + " · " + strconv.Itoa(m.activities) + " moved"), cell(m.reason)}})
	}
	history := &screensv1.PageTable{Columns: columns("What moved", "From", "To", "Effective", "Open work", "Reason")}
	blocks = append(blocks, panel("Transfer history"))
	if len(batches) == 0 && len(transfers) == 0 {
		history.EmptyMessage = "No ownership transfer has been recorded yet."
		history.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{cell("No ownership transfer has been recorded yet.")}}}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: history}})
	} else {
		blocks = append(blocks, paged(history, lead, rows, "transfers_page", query)...)
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}
