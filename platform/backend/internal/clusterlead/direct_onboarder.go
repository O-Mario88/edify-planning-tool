package clusterlead

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http"
	"net/mail"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// InviteMailer delivers cluster-leader invitation emails when SMTP or a dev
// mailbox is configured.
type InviteMailer interface {
	SendMail(ctx context.Context, to, subject, text string) error
}

// DirectOnboarder replaces HTTPOnboarder when Django is absent: it enforces
// apps/clusters/leader_onboarding.py parity directly in PostgreSQL via
// gateway_cluster_onboard.ensure_leader_account (conflict check on non-leader
// email, pending_invited user + user_invitation token hash + audit_log) and
// optionally sends the invitation email.
type DirectOnboarder struct {
	pool       *pgxpool.Pool
	mailer     InviteMailer
	appBaseURL string
}

// NewDirectOnboarder constructs a Django-independent cluster leader onboarder.
func NewDirectOnboarder(pool *pgxpool.Pool) *DirectOnboarder {
	if pool == nil {
		return nil
	}
	return &DirectOnboarder{pool: pool}
}

// WithMailer configures invitation email delivery and the app base URL used in
// set-password links.
func (d *DirectOnboarder) WithMailer(mailer InviteMailer, appBaseURL string) *DirectOnboarder {
	if d != nil {
		d.mailer = mailer
		d.appBaseURL = strings.TrimRight(strings.TrimSpace(appBaseURL), "/")
	}
	return d
}

// Onboard ensures an account exists for the cluster leader in PostgreSQL.
func (d *DirectOnboarder) Onboard(ctx context.Context, clusterID string, in OnboardInput) (Onboarded, error) {
	email := strings.ToLower(strings.TrimSpace(in.Email))
	name := strings.TrimSpace(in.Name)
	phone := strings.TrimSpace(in.Phone)
	if name == "" {
		return Onboarded{}, &OnboardRefusal{Status: http.StatusBadRequest, Message: "The leader's name is required."}
	}
	if email == "" {
		return Onboarded{}, &OnboardRefusal{Status: http.StatusBadRequest, Message: "An email address is required: the invitation goes there."}
	}
	if _, err := mail.ParseAddress(email); err != nil {
		return Onboarded{}, &OnboardRefusal{Status: http.StatusBadRequest, Message: "Enter a valid email address."}
	}
	var tokenBytes [24]byte
	if _, err := rand.Read(tokenBytes[:]); err != nil {
		return Onboarded{}, fmt.Errorf("clusterlead: generating invite token: %w", err)
	}
	inviteToken := hex.EncodeToString(tokenBytes[:])
	tokenHashSum := sha256.Sum256([]byte(inviteToken))
	tokenHash := hex.EncodeToString(tokenHashSum[:])

	actorID, actorRole, actorName := "", "", "Edify"
	if p, ok := auth.PrincipalFrom(ctx); ok {
		actorID = p.UserID
		actorRole = p.ActiveRole
		if p.Name != "" {
			actorName = p.Name
		}
	}

	tx, err := d.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return Onboarded{}, fmt.Errorf("clusterlead: begin onboard tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var userID string
	var existing, conflict bool
	if err := tx.QueryRow(ctx,
		`SELECT user_id, existing, conflict
		   FROM gateway_cluster_onboard.ensure_leader_account($1, $2, $3, $4, $5, $6, $7)`,
		name, email, phone, tokenHash, clusterID, actorID, actorRole).Scan(&userID, &existing, &conflict); err != nil {
		return Onboarded{}, fmt.Errorf("clusterlead: direct onboard: %w", err)
	}
	if conflict {
		return Onboarded{}, &OnboardRefusal{
			Status:  http.StatusConflict,
			Message: "This email belongs to an Edify staff or partner account. A Cluster Leader needs their own email.",
		}
	}
	if !existing {
		auditActor := actorID
		if auditActor == "" {
			auditActor = "system"
		}
		if _, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "cluster_leader.onboarded",
			SubjectKind: audit.Text("user"),
			SubjectID:   audit.Text(userID),
			ActorID:     audit.Text(auditActor),
			ActorRole:   audit.Text(actorRole),
			Success:     true,
			Payload: map[string]any{
				"email":     email,
				"clusterId": clusterID,
			},
		}, time.Now().UTC()); err != nil {
			return Onboarded{}, fmt.Errorf("clusterlead: appending onboard audit row: %w", err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return Onboarded{}, fmt.Errorf("clusterlead: commit onboard tx: %w", err)
	}
	out := Onboarded{UserID: userID, Existing: existing}
	if !existing {
		if d.mailer != nil {
			link := "/set-password?token=" + inviteToken
			if d.appBaseURL != "" {
				link = d.appBaseURL + link
			}
			body := fmt.Sprintf("Hello %s,\n\n%s invited you to join Edify as a Cluster Leader.\nSet your password here: %s\n", name, actorName, link)
			if mailErr := d.mailer.SendMail(ctx, email, "You are invited to Edify as a Cluster Leader", body); mailErr != nil {
				// If mail fails, hand back the invite token so the staff member can still share it.
				out.InviteToken = inviteToken
			}
		} else {
			out.InviteToken = inviteToken
		}
	}
	return out, nil
}
