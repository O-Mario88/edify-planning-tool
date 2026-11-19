package iapages

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// NotificationsPath is Verification Notifications
// (ia_views.ia_notifications_view, pages/ia/notifications.html): the newest
// fifty notices addressed to the reader under the verification categories,
// each its title (a link when it opens a record), its time and its words.
const NotificationsPath = "/ia/notifications/"

const notificationsLimit = 50

func (s *Service) notifications(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, `SELECT title, COALESCE(body, ''), COALESCE(target_route, ''), created_at
FROM notification WHERE recipient_id = $1 AND category = ANY($2)
ORDER BY created_at DESC LIMIT $3`, p.UserID, rules.NotificationCategories, notificationsLimit)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the reader's notices: %w", err)
	}
	type notice struct {
		title, body, route string
		at                 time.Time
	}
	notices, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (notice, error) {
		var n notice
		return n, r.Scan(&n.title, &n.body, &n.route, &n.at)
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the reader's notices: %w", err)
	}
	var items []*screensv1.PagePanelItem
	for _, n := range notices {
		items = append(items, noticeItems(n.title, n.body, n.route, n.at.In(zone).Format("Jan 02, 15:04"))...)
	}
	if len(items) == 0 {
		items = []*screensv1.PagePanelItem{text("Completions, returns and duplicate warnings that reach Impact Assessment appear here.")}
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Verification", Title: "Verification Notifications",
			Description: "Completions, resubmissions, returns and duplicate warnings that reached Impact Assessment.",
			Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}},
		Blocks: []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Badges: []*screensv1.PageBadge{}, Items: items}}}},
		Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}, WebPath: NotificationsPath,
	}, true, nil
}

func noticeItems(title, body, route string, at string) []*screensv1.PagePanelItem {
	t := closedschools.Collapse(title)
	first := text(t)
	if route != "" {
		first = &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: t, Href: route}}}}}
	}
	out := []*screensv1.PagePanelItem{first, text(at)}
	if b := closedschools.Collapse(body); b != "" {
		out = append(out, text(b))
	}
	return out
}
