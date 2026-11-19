package adminpanel

import (
	"context"
	"fmt"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectspage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// AuditLogPath is the Audit Log (extended_views.audit_log_view,
// pages/admin/audit_log.html): the newest hundred audit rows, each its action
// and time, fifty a page.
const AuditLogPath = "/admin-panel/audit-log"

const (
	auditLimit    = 100
	auditPageSize = 50
)

func (s *Service) auditLog(ctx context.Context, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, `SELECT action, created_at FROM audit_log ORDER BY created_at DESC LIMIT $1`, auditLimit)
	if err != nil {
		return nil, true, fmt.Errorf("adminpanel: reading the audit log: %w", err)
	}
	type entry struct {
		action string
		at     time.Time
	}
	logs, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (entry, error) {
		var e entry
		return e, r.Scan(&e.action, &e.at)
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminpanel: reading the audit log: %w", err)
	}
	h := header("Administration", "Audit Log", "Edify Operations · Audit Log")
	if len(logs) == 0 {
		return page(h, AuditLogPath, titled("", text("No audit records"))), true, nil
	}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Action"}, {Label: "Time"}}}
	pg := tablepager.Paginate(len(logs), auditPageSize, query, "logs_page")
	for _, e := range logs[pg.Start:pg.End] {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(e.action)}, {Text: projectspage.DjangoDateTime(e.at.In(zone))}}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if panel := tablepager.Panel(len(logs), auditPageSize, query, "logs_page"); panel != nil {
		blocks = append(blocks, panel)
	}
	return page(h, AuditLogPath, blocks...), true, nil
}
