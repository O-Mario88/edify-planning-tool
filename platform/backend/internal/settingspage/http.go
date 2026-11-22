package settingspage

import (
	"context"
	"crypto/rand"
	"encoding/base32"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/signin"
)

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// TwoStepUpdateInput is the JSON body for POST /api/v1/settings/two-step.
type TwoStepUpdateInput struct {
	Enabled bool   `json:"enabled"`
	Channel string `json:"channel"`
}

// RegisterHTTP mounts native Settings mutation routes on mux so Next.js and
// mobile clients can update two-step verification and enroll TOTP without Django.
func RegisterHTTP(mux *http.ServeMux, auther Authenticator, pool *pgxpool.Pool, svc *Service, fieldKey signin.FieldKey, now func() time.Time) {
	if now == nil {
		now = time.Now
	}

	mux.HandleFunc("POST /api/v1/settings/two-step", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeSettingsJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		if role, ok := rules.Roles[p.ActiveRole]; !ok || !role.Page {
			writeSettingsJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot change these settings."})
			return
		}
		var in TwoStepUpdateInput
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&in); err != nil {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		channel := strings.ToLower(strings.TrimSpace(in.Channel))
		if channel == "" {
			channel = rules.Channels.Email
		}
		if channel != rules.Channels.Email && channel != rules.Channels.SMS && channel != rules.Channels.App {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "Choose email, sms, or authenticator app."})
			return
		}

		var a account
		err = pool.QueryRow(r.Context(), `
SELECT u.email, COALESCE(u.phone, ''), u.mfa_enabled, COALESCE(u.mfa_channel, ''),
       COALESCE(u.mfa_secret, '') <> '', u.must_change_password, u.roles, COALESCE(u.active_role, '')
FROM "user" u WHERE u.id = $1 AND u.deleted_at IS NULL`, p.UserID).Scan(
			&a.email, &a.phone, &a.enrolled, &a.channel, &a.appEnrolled, &a.mustChange, &a.roles, &a.activeRole)
		if errors.Is(err, pgx.ErrNoRows) {
			writeSettingsJSON(w, http.StatusNotFound, map[string]string{"error": "Account not found."})
			return
		}
		if err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not load account settings."})
			return
		}

		required := svc.requiredByPolicy(a)
		if !in.Enabled && required {
			writeSettingsJSON(w, http.StatusForbidden, map[string]string{
				"error": "Your organisation requires two-step verification, so it cannot be turned off.",
			})
			return
		}
		if channel == rules.Channels.SMS && (a.phone == "" || !svc.smsConfigured()) {
			reason := rules.SMSNotConfigured
			if a.phone == "" {
				reason = rules.SMSNeedsPhone
			}
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": reason})
			return
		}
		if channel == rules.Channels.App && !a.appEnrolled {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{
				"error": "Set up an authenticator app first before choosing it.",
			})
			return
		}

		tx, err := pool.BeginTx(r.Context(), pgx.TxOptions{AccessMode: pgx.ReadWrite})
		if err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not start settings update."})
			return
		}
		defer func() { _ = tx.Rollback(r.Context()) }()
		ts := now().UTC()
		var ok bool
		if err := tx.QueryRow(r.Context(),
			`SELECT gateway_settings.update_two_step($1, $2, $3, $4)`,
			p.UserID, in.Enabled || required, channel, ts,
		).Scan(&ok); err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not save two-step verification settings."})
			return
		}
		if !ok {
			writeSettingsJSON(w, http.StatusNotFound, map[string]string{"error": "Account not found."})
			return
		}
		if _, err := audit.Append(r.Context(), tx, audit.Entry{
			Action:      "auth.mfa_settings_updated",
			SubjectKind: audit.Text("user"),
			SubjectID:   audit.Text(p.UserID),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"mfa_enabled": in.Enabled || required,
				"mfa_channel": channel,
			},
		}, ts); err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not record two-step verification audit entry."})
			return
		}
		if err := tx.Commit(r.Context()); err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not commit settings update."})
			return
		}

		a.enrolled = in.Enabled || required
		a.channel = channel
		updated := svc.twoStep(a)
		writeSettingsJSON(w, http.StatusOK, map[string]any{
			"saved":              true,
			"in_force":           updated.GetInForce(),
			"required_by_policy": updated.GetRequiredByPolicy(),
			"channel":            updated.GetChannel(),
			"sms_available":      updated.GetSmsAvailable(),
			"app_available":      updated.GetAppAvailable(),
		})
	})

	// Native TOTP authenticator app setup (Batch 24).
	mux.HandleFunc("POST /api/v1/settings/two-step/totp/setup", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeSettingsJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		if role, ok := rules.Roles[p.ActiveRole]; !ok || !role.Page {
			writeSettingsJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot enroll an authenticator app."})
			return
		}
		raw := make([]byte, 20)
		if _, err := rand.Read(raw); err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not generate authenticator key."})
			return
		}
		secret := base32.StdEncoding.WithPadding(base32.NoPadding).EncodeToString(raw)
		label := url.PathEscape("Edify:" + p.Email)
		uri := fmt.Sprintf("otpauth://totp/%s?secret=%s&issuer=Edify&digits=6&period=30", label, secret)
		writeSettingsJSON(w, http.StatusOK, map[string]any{
			"secret":      secret,
			"otpauth_uri": uri,
		})
	})

	mux.HandleFunc("POST /api/v1/settings/two-step/totp/confirm", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeSettingsJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		if role, ok := rules.Roles[p.ActiveRole]; !ok || !role.Page {
			writeSettingsJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot enroll an authenticator app."})
			return
		}
		var req struct {
			Secret string `json:"secret"`
			Code   string `json:"code"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<14)).Decode(&req); err != nil {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		secret := strings.ToUpper(strings.TrimSpace(req.Secret))
		if secret == "" || !signin.VerifyTOTP(secret, req.Code, now().UTC()) {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "That 6-digit code did not match. Check your authenticator app and try again."})
			return
		}
		if len(fieldKey) == 0 {
			writeSettingsJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Authenticator app enrollment is unavailable until EDIFY_FIELD_ENCRYPTION_KEY is configured."})
			return
		}
		stored, err := fieldKey.Seal(secret)
		if err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not seal authenticator secret."})
			return
		}
		tx, err := pool.BeginTx(r.Context(), pgx.TxOptions{AccessMode: pgx.ReadWrite})
		if err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not start enrollment transaction."})
			return
		}
		defer func() { _ = tx.Rollback(r.Context()) }()
		ts := now().UTC()
		var ok bool
		if err := tx.QueryRow(r.Context(),
			`SELECT gateway_settings.enroll_totp($1, $2, $3)`,
			p.UserID, stored, ts,
		).Scan(&ok); err != nil || !ok {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not save authenticator enrollment."})
			return
		}
		if _, err := audit.Append(r.Context(), tx, audit.Entry{
			Action:      "auth.mfa_totp_enrolled",
			SubjectKind: audit.Text("user"),
			SubjectID:   audit.Text(p.UserID),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"mfa_channel": "app",
			},
		}, ts); err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not record authenticator enrollment audit entry."})
			return
		}
		if err := tx.Commit(r.Context()); err != nil {
			writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not commit authenticator enrollment."})
			return
		}
		writeSettingsJSON(w, http.StatusOK, map[string]any{
			"enrolled": true,
			"channel":  "app",
		})
	})
}

func writeSettingsJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
