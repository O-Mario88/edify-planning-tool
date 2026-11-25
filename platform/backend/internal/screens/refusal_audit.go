package screens

// require_page_permission's audit for the pages, drawers and drawer saves Go
// answers itself: when the page gate refuses the reader, the
// unauthorized_page_access row Django writes before it refuses (owner,
// 2026-11-14: a read writes nothing but an audit record). A page Go hands on
// is Django's to audit.

import (
	"context"
	"fmt"
	"log/slog"
	"strings"

	"github.com/jackc/pgx/v5"

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
	now := s.clock()
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("screens: opening the refusal's audit: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := audit.CoverageStamp(ctx, tx, p.UserID, now)
	if err != nil {
		return err
	}
	var payload any
	if cover != nil {
		payload = cover
	}
	role := p.ActiveRole
	reason := fmt.Sprintf("Role '%s' attempted to access page: %s", role, strings.Join(pages, " or "))
	if _, err := audit.Append(ctx, tx, audit.Entry{Action: "unauthorized_page_access", SubjectKind: audit.Text("Page"),
		SubjectID: audit.Text(pages[0]), ActorID: audit.Text(p.UserID), ActorRole: audit.Text(role), Success: false,
		Reason: &reason, Payload: payload, IPAddress: audit.Text(o.IP), UserAgent: audit.Text(o.UserAgent),
		CorrelationID: audit.Text(o.CorrelationID)}, now); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("screens: committing the refusal's audit: %w", err)
	}
	return nil
}
