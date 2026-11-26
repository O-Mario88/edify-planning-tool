package audit

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Beginner opens a transaction (a pool).
type Beginner interface {
	BeginTx(ctx context.Context, opts pgx.TxOptions) (pgx.Tx, error)
}

// RefusedPage is who the page gate refused, and where the request came from.
type RefusedPage struct {
	UserID, Role                 string
	Pages                        []string
	IP, UserAgent, CorrelationID string
}

// AppendRefusedPage writes require_page_permission's unauthorized_page_access
// row (and its domain event) in a short transaction of its own: the first
// page as its subject, the pages joined by " or " in the reason, the
// reader's cover stamped.
func AppendRefusedPage(ctx context.Context, db Beginner, r RefusedPage, now time.Time) error {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("audit: opening the refusal's audit: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := CoverageStamp(ctx, tx, r.UserID, now)
	if err != nil {
		return err
	}
	var payload any
	if cover != nil {
		payload = cover
	}
	reason := fmt.Sprintf("Role '%s' attempted to access page: %s", r.Role, strings.Join(r.Pages, " or "))
	if _, err := Append(ctx, tx, Entry{Action: "unauthorized_page_access", SubjectKind: Text("Page"),
		SubjectID: Text(r.Pages[0]), ActorID: Text(r.UserID), ActorRole: Text(r.Role), Success: false,
		Reason: &reason, Payload: payload, IPAddress: Text(r.IP), UserAgent: Text(r.UserAgent),
		CorrelationID: Text(r.CorrelationID)}, now); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("audit: committing the refusal's audit: %w", err)
	}
	return nil
}
