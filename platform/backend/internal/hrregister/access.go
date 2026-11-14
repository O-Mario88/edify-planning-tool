package hrregister

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
)

// auditedReads are the registers whose reading is itself recorded
// (employee_relations_service.record_access): the view each one names.
var auditedReads = map[string]string{"/employee-relations": "case_register"}

// TxBeginner opens the read-write transaction an audit row is appended in.
type TxBeginner interface {
	BeginTx(ctx context.Context, options pgx.TxOptions) (pgx.Tx, error)
}

// WithAccessLog lets the registers whose reading is audited be answered in
// Go: each read appends its row to the audit chain through db. Without it
// those registers stay with the existing application.
func (s *Service) WithAccessLog(db TxBeginner, logger *slog.Logger) *Service {
	s.writer, s.logger = db, logger
	return s
}

// recordAccess is record_access(reader, what=view): an hr.er_accessed row,
// the reader as its actor (with the cover they hold, as log() stamps it) and
// the request's address, browser and correlation id. Like the existing call
// it is best-effort: a failure is logged and the register is still shown.
func (s *Service) recordAccess(ctx context.Context, p auth.Principal, view string) {
	if err := s.appendAccess(ctx, p, view); err != nil && s.logger != nil {
		s.logger.ErrorContext(ctx, "the employee-relations read was not audited", slog.String("error", err.Error()))
	}
}

func (s *Service) appendAccess(ctx context.Context, p auth.Principal, view string) error {
	now := s.now()
	tx, err := s.writer.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("hrregister: opening the audit transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := audit.CoverageStamp(ctx, tx, p.UserID, now)
	if err != nil {
		return err
	}
	o, _ := origin.From(ctx)
	role := p.ActiveRole
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "hr.er_accessed", SubjectKind: audit.Text("employee_relations_case"),
		ActorID: audit.Text(p.UserID), ActorRole: &role, Success: true,
		Payload:   audit.WithStamps(map[string]any{"view": view}, cover),
		IPAddress: audit.Text(o.IP), UserAgent: audit.Text(o.UserAgent), CorrelationID: audit.Text(o.CorrelationID),
	}, now); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("hrregister: committing the audit row: %w", err)
	}
	return nil
}
