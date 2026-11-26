package screens

// require_page_permission's audit for the pages, drawers and drawer saves Go
// answers itself: when the page gate refuses the reader, the
// unauthorized_page_access row Django writes before it refuses (owner,
// 2026-11-14: a read writes nothing but an audit record). A page Go hands on
// is Django's to audit.

import (
	"context"
	"log/slog"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

// auditRefusedPage writes the row when the gate refuses p at path. It is
// best-effort: a failure is logged and the answer stands.
func (s *Service) auditRefusedPage(ctx context.Context, p auth.Principal, path string, o origin.Origin) {
	pages := pageaccess.RefusedPages(p.ActiveRole, false, path)
	if len(pages) == 0 || s.db == nil || p.UserID == "" {
		return
	}
	if err := s.appendRefusal(ctx, p, pages, o); err != nil && s.logger != nil {
		s.logger.ErrorContext(ctx, "the refused page was not audited", slog.String("path", path), slog.String("error", err.Error()))
	}
}

func (s *Service) appendRefusal(ctx context.Context, p auth.Principal, pages []string, o origin.Origin) error {
	return audit.AppendRefusedPage(ctx, s.db, audit.RefusedPage{UserID: p.UserID, Role: p.ActiveRole, Pages: pages,
		IP: o.IP, UserAgent: o.UserAgent, CorrelationID: o.CorrelationID}, s.clock())
}
