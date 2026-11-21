// Package helpcontext serves /help/context natively in Go, matching
// apps.help_center.views.contextual without Django settings or cache.
package helpcontext

import (
	"context"
	"errors"
	"net/url"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const Path = "/help/context"

type Service struct {
	db schooldirectory.Querier
}

func NewService(db schooldirectory.Querier) *Service {
	return &Service{db: db}
}

func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if strings.TrimRight(path, "/") != Path {
		return nil, false, nil
	}
	target := strings.TrimSpace(query.Get("for"))
	if target == "" {
		target = "/"
	}
	status := strings.TrimSpace(query.Get("status"))

	var id, title, slug, summary, categoryName string
	err := s.db.QueryRow(ctx, `
SELECT a.id, a.title, a.slug, COALESCE(a.summary, ''), COALESCE(c.name, 'Help Center')
FROM help_center_helparticleroutecontext rc
JOIN help_center_helparticle a ON a.id = rc.article_id
LEFT JOIN help_center_helpcategory c ON c.id = a.category_id
WHERE a.state = 'published'
  AND ($1 LIKE rc.route_pattern OR $1 = rc.route_pattern OR rc.route_pattern = '/')
  AND (rc.workflow_status = '' OR rc.workflow_status = $2)
  AND (
    NOT EXISTS (SELECT 1 FROM help_center_helparticleroleaccess ra WHERE ra.article_id = a.id)
    OR EXISTS (SELECT 1 FROM help_center_helparticleroleaccess ra WHERE ra.article_id = a.id AND ra.role = $3)
  )
ORDER BY
  CASE WHEN rc.route_pattern = $1 THEN 0 WHEN rc.route_pattern = '/' THEN 2 ELSE 1 END,
  CASE WHEN rc.workflow_status = $2 AND $2 <> '' THEN 0 ELSE 1 END,
  rc.priority ASC,
  a.updated_at DESC
LIMIT 1`, target, status, p.ActiveRole).Scan(&id, &title, &slug, &summary, &categoryName)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrForbidden
	}
	if err != nil {
		return nil, true, err
	}

	items := []*screensv1.PagePanelItem{}
	if summary != "" {
		items = append(items, &screensv1.PagePanelItem{
			Kind: &screensv1.PagePanelItem_Text{Text: summary},
		})
	}
	items = append(items, &screensv1.PagePanelItem{
		Kind: &screensv1.PagePanelItem_Text{Text: "Context: " + target},
	})
	return &screensv1.GetPageResponse{
		WebPath: Path,
		Header: &screensv1.PageHeader{
			Eyebrow:     categoryName,
			Title:       title,
			Description: summary,
			Actions: []*screensv1.PageAction{{
				Key: "article", Label: "Open Full Guide", Enabled: true, Href: "/help/" + slug,
			}},
		},
		Blocks: []*screensv1.PageBlock{{
			Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
				Title: title,
				Items: items,
			}},
		}},
	}, true, nil
}
