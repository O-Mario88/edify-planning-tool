package audit

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// chainLockID is the existing application's advisory lock on the append
// point (_AUDIT_CHAIN_LOCK_ID, "EDIFYAUD"). Taking the same lock is what
// keeps the two systems from both appending after the same tail.
const chainLockID int64 = 0x4544494659415544

// Append writes one sealed row at the end of the chain, inside tx, and the
// row's projection to domain_event_log beside it, as the existing
// application does when it appends outside a caller's transaction. The chain
// lock is held until tx ends, so callers keep their transactions short.
func Append(ctx context.Context, tx pgx.Tx, e Entry, now time.Time) (int64, error) {
	canonical, err := Canonical(e)
	if err != nil {
		return 0, err
	}
	payload, err := jsonOrNull(e.Payload)
	if err != nil {
		return 0, err
	}
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock($1)`, chainLockID); err != nil {
		return 0, fmt.Errorf("audit: taking the chain lock: %w", err)
	}
	var (
		prevHash *string
		tailSeq  int64
	)
	// No FOR UPDATE: the advisory lock, which the existing application takes
	// around every append and seal, already serializes the tail, and leaving
	// the row lock out means this role needs no UPDATE right on audit_log —
	// it can add to the chain and never alter it.
	err = tx.QueryRow(ctx,
		`SELECT seq, hash FROM audit_log WHERE seq IS NOT NULL ORDER BY seq DESC LIMIT 1`,
	).Scan(&tailSeq, &prevHash)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return 0, fmt.Errorf("audit: reading the chain's tail: %w", err)
	}
	seq := tailSeq + 1
	previous := ""
	if prevHash != nil {
		previous = *prevHash
	}
	hash := ChainHash(previous, canonical)

	_, err = tx.Exec(ctx, `
INSERT INTO audit_log (id, seq, action, subject_kind, subject_id, actor_id, actor_role, payload,
                       ip_address, user_agent, correlation_id, success, reason, prev_hash, hash, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)`,
		cuid.New(), seq, e.Action, e.SubjectKind, e.SubjectID, e.ActorID, e.ActorRole, payload,
		e.IPAddress, e.UserAgent, e.CorrelationID, e.Success, e.Reason, prevHash, hash, now)
	if err != nil {
		return 0, fmt.Errorf("audit: appending %s: %w", e.Action, err)
	}
	if err := project(ctx, tx, e, seq, now); err != nil {
		return 0, err
	}
	return seq, nil
}

// project is the existing publish_audit_event's durable half: the event
// stream row. It is written in the same transaction, so a rolled-back sign-in
// leaves no phantom event (the existing code waits for the commit to the same
// end).
func project(ctx context.Context, tx pgx.Tx, e Entry, seq int64, now time.Time) error {
	// publish_audit_event: a dict payload as it is, anything else (a row
	// with no payload too) as {"value": payload}.
	data := e.Payload
	if _, ok := data.(map[string]any); !ok {
		data = map[string]any{"value": data}
	}
	payload, err := json.Marshal(map[string]any{
		"auditSeq": seq, "success": e.Success, "reason": e.Reason, "data": data,
	})
	if err != nil {
		return fmt.Errorf("audit: encoding the event: %w", err)
	}
	_, err = tx.Exec(ctx, `
INSERT INTO domain_event_log (id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $7)`,
		cuid.New(), e.Action, e.SubjectKind, e.SubjectID, e.ActorID, payload, now)
	if err != nil {
		return fmt.Errorf("audit: recording the event for %s: %w", e.Action, err)
	}
	return nil
}

func jsonOrNull(value any) ([]byte, error) {
	if value == nil {
		return nil, nil
	}
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, fmt.Errorf("audit: encoding the payload: %w", err)
	}
	return raw, nil
}
