package signin

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
)

// DirectRelay replaces HTTPRelay when Django is absent: it writes the exact
// Admin security incident (matching apps/admin_ops/services.py SecurityAlertService)
// and notifies active Admin accounts natively through notificationcenter.Writer.
type DirectRelay struct {
	pool   *pgxpool.Pool
	writer *notificationcenter.Writer
	env    string
	now    func() time.Time
}

// NewDirectRelay constructs a Django-independent SecurityEvent reporter.
func NewDirectRelay(pool *pgxpool.Pool, writer *notificationcenter.Writer) *DirectRelay {
	if pool == nil || writer == nil {
		return nil
	}
	return &DirectRelay{pool: pool, writer: writer, env: "local", now: time.Now}
}

// WithEnv records the environment name in the incident signature (matching
// SystemIncidentService.signature_of).
func (r *DirectRelay) WithEnv(env string) *DirectRelay {
	if r != nil && strings.TrimSpace(env) != "" {
		r.env = strings.TrimSpace(env)
	}
	return r
}

func maskAlertEmail(email string) string {
	name, domain, ok := strings.Cut(strings.TrimSpace(email), "@")
	if !ok || domain == "" {
		return "unknown"
	}
	keep := name
	if len(keep) > 2 {
		keep = keep[:2]
	}
	stars := len(name) - len(keep)
	if stars < 1 {
		stars = 1
	}
	return keep + strings.Repeat("*", stars) + "@" + domain
}

func incidentSignature(env, category, route, errKey string) string {
	sum := sha256.Sum256([]byte(strings.Join([]string{env, category, route, errKey}, "|")))
	return hex.EncodeToString(sum[:])[:40]
}

// Report executes the full security side effects natively in Go:
//   - failed_login_threshold: upserts an admin_system_incident via
//     gateway_relay_ops.record_security_incident and notifies active Admins.
//   - lockout_escalated: notifies active Admins of the escalated lockout.
func (r *DirectRelay) Report(ctx context.Context, event SecurityEvent) error {
	now := r.now().UTC()
	var userEmail, userName string
	_ = r.pool.QueryRow(ctx, `SELECT COALESCE(email, ''), COALESCE(name, '') FROM "user" WHERE id = $1`, event.UserID).
		Scan(&userEmail, &userName)
	masked := maskAlertEmail(userEmail)

	var (
		title       string
		body        string
		category    string
		contextType string
		contextID   string
		eventType   string
		eventID     string
	)

	switch event.Kind {
	case "failed_login_threshold":
		sig := incidentSignature(r.env, "security", "/login", "failed_login_threshold:"+event.UserID)
		incTitle := fmt.Sprintf("Failed-login threshold reached for %s", masked)
		detailJSON, _ := json.Marshal(map[string]any{
			"masked_identifier": masked,
			"streak":            event.Streak,
			"locked":            event.Locked,
		})
		tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
		if err != nil {
			return fmt.Errorf("signin: begin incident tx: %w", err)
		}
		defer func() { _ = tx.Rollback(ctx) }()
		var incID, ref string
		var created, reopened bool
		var occ int
		if err := tx.QueryRow(ctx,
			`SELECT incident_id, reference, created, reopened, occurrence_count
			   FROM gateway_relay_ops.record_security_incident($1, $2, $3, $4, $5, $6, $7::jsonb, $8)`,
			sig, incTitle, "security", "high", "/login", "authentication", string(detailJSON), now,
		).Scan(&incID, &ref, &created, &reopened, &occ); err != nil {
			return fmt.Errorf("signin: recording security incident: %w", err)
		}
		if created || reopened {
			action := "admin_ops.incident.detected"
			if !created && reopened {
				action = "admin_ops.incident.reopened"
			}
			if _, err := audit.Append(ctx, tx, audit.Entry{
				Action:      action,
				SubjectKind: audit.Text("system_incident"),
				SubjectID:   audit.Text(incID),
				ActorID:     audit.Text("system"),
				Success:     true,
				Payload: map[string]any{
					"reference": ref,
					"signature": sig,
				},
			}, now); err != nil {
				return fmt.Errorf("signin: appending incident audit row: %w", err)
			}
		}
		if err := tx.Commit(ctx); err != nil {
			return fmt.Errorf("signin: committing security incident: %w", err)
		}
		title = fmt.Sprintf("%s: %s", ref, incTitle)
		body = fmt.Sprintf("High · /login · seen %d× (streak=%d, locked=%v)", occ, event.Streak, event.Locked)
		category = "availability"
		contextType = "system_incident"
		contextID = incID
		eventType = "admin_ops.incident.detected"
		eventID = fmt.Sprintf("%s:%d", ref, occ)
	case "lockout_escalated":
		if userName == "" {
			userName = masked
		}
		title = fmt.Sprintf("Account Locked: %s", userName)
		body = fmt.Sprintf("%s has been locked after repeated failed-login lockout cycles and requires an administrator to unlock it.", masked)
		category = "general"
		contextType = "User"
		contextID = event.UserID
		eventType = "account_lockout"
		eventID = fmt.Sprintf("lock:%s:%d", event.UserID, now.Unix()/60)
	default:
		title = "Security alert: " + event.Kind
		body = fmt.Sprintf("Security event (%s) for account %s (streak=%d, locked=%v).", event.Kind, masked, event.Streak, event.Locked)
		category = "security"
		contextType = "user"
		contextID = event.UserID
		eventType = "security." + event.Kind
		eventID = fmt.Sprintf("%s:%s", event.Kind, event.UserID)
	}

	rows, err := r.pool.Query(ctx, `SELECT id FROM "user"
WHERE deleted_at IS NULL AND is_active AND status = 'active'
  AND (active_role = 'Admin' OR 'Admin' = ANY(roles))`)
	if err != nil {
		return fmt.Errorf("signin: listing admins for security event: %w", err)
	}
	defer rows.Close()
	var adminIDs []string
	for rows.Next() {
		var adminID string
		if scanErr := rows.Scan(&adminID); scanErr != nil {
			return scanErr
		}
		if adminID != "" {
			adminIDs = append(adminIDs, adminID)
		}
	}
	if err := rows.Err(); err != nil {
		return err
	}
	for _, adminID := range adminIDs {
		if _, err := r.writer.Deliver(ctx, notificationcenter.Delivery{
			RecipientID:     adminID,
			Title:           title,
			Body:            body,
			Category:        category,
			ContextType:     contextType,
			ContextID:       contextID,
			TargetRoute:     "/admin-panel/users",
			ActionLabel:     "Inspect",
			ActionRequired:  event.Locked || event.Kind == "lockout_escalated",
			Priority:        "high",
			SourceEventType: eventType,
			SourceEventID:   eventID,
		}); err != nil {
			return fmt.Errorf("signin: delivering security alert to %s: %w", adminID, err)
		}
	}
	return nil
}
