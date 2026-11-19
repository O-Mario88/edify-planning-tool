package adminpanel

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// NotificationsPath is Notification & Alert Logs
// (extended_views.admin_notifications_mgmt_view,
// pages/admin/notifications_mgmt.html): the newest fifty notifications sent
// to anyone, each its title, words and time, its recipient and role, its
// priority and whether it was read.
const NotificationsPath = "/admin-panel/notifications-mgmt"

const (
	notificationsLimit    = 50
	notificationsPageSize = 50
)

type notice struct {
	title, body, recipient, name, role, priority, status string
	known                                                bool
	at                                                   time.Time
}

func (s *Service) notifications(ctx context.Context, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, `SELECT n.title, COALESCE(n.body, ''), n.recipient_id, COALESCE(u.name, ''), u.id IS NOT NULL,
  COALESCE(n.recipient_role, ''), COALESCE(n.priority, ''), COALESCE(n.status, ''), n.created_at
FROM notification n LEFT JOIN "user" u ON u.id = n.recipient_id
ORDER BY n.created_at DESC LIMIT $1`, notificationsLimit)
	if err != nil {
		return nil, true, fmt.Errorf("adminpanel: reading the notifications: %w", err)
	}
	logs, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (notice, error) {
		var n notice
		return n, r.Scan(&n.title, &n.body, &n.recipient, &n.name, &n.known, &n.role, &n.priority, &n.status, &n.at)
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminpanel: reading the notifications: %w", err)
	}
	t := &screensv1.PageTable{}
	for i, c := range []string{"Alert Summary", "Recipient Details", "Priority", "Delivery Status", "Action"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: i == 4})
	}
	pg := tablepager.Paginate(len(logs), notificationsPageSize, query, "logs_page")
	for _, n := range logs[pg.Start:pg.End] {
		summary := n.title
		if n.body != "" {
			summary += " " + n.body
		}
		summary += " Generated: " + n.at.In(zone).Format("Jan 02, 2006 15:04")
		recipient := n.recipient
		if n.known {
			recipient = n.name
		}
		if n.role != "" {
			recipient += " Role: " + strings.ToUpper(n.role)
		}
		delivery := "Sent (Unread)"
		if n.status == "read" {
			delivery = "Delivered & Read"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(summary)}, {Text: closedschools.Collapse(recipient)},
			{Text: closedschools.Collapse(n.priority), Tone: "primary", Badge: true},
			{Text: delivery, Tone: "primary", Badge: true}, {Actions: []*screensv1.PageAction{}},
		}})
	}
	if len(logs) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No notification delivery logs registered in the database database."}}}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if panel := tablepager.Panel(len(logs), notificationsPageSize, query, "logs_page"); panel != nil {
		blocks = append(blocks, panel)
	}
	return page(header("Administration", "Notification & Alert Logs",
		"Monitor system-generated notifications, trigger dates, delivery states, and error codes"),
		NotificationsPath, blocks...), true, nil
}
