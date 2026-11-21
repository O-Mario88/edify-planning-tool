package notificationcenter

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// PreferencesInput is the payload for updating a user's notification delivery
// preferences (email toggle, push toggle, muted categories).
type PreferencesInput struct {
	EmailEnabled    bool     `json:"emailEnabled"`
	PushEnabled     bool     `json:"pushEnabled"`
	MutedCategories []string `json:"mutedCategories"`
}

// UpdatePreferences persists the caller's notification delivery preferences
// natively via gateway_notifications.update_preferences.
func (w *Writer) UpdatePreferences(ctx context.Context, userID string, in PreferencesInput) error {
	clean := make([]string, 0, len(in.MutedCategories))
	seen := map[string]bool{}
	for _, c := range in.MutedCategories {
		c = strings.TrimSpace(c)
		if c != "" && !seen[c] {
			seen[c] = true
			clean = append(clean, c)
		}
	}
	mutedJSON, _ := json.Marshal(clean)

	tx, err := w.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var ok bool
	if err := tx.QueryRow(ctx,
		`SELECT gateway_notifications.update_preferences($1, $2, $3, $4::jsonb, $5)`,
		userID, in.EmailEnabled, in.PushEnabled, string(mutedJSON), w.now().UTC(),
	).Scan(&ok); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// RegisterPreferencesHTTP mounts POST /api/v1/notifications/preferences on mux.
func RegisterPreferencesHTTP(mux *http.ServeMux, auther Authenticator, pool *pgxpool.Pool, now func() time.Time) {
	writer := NewWriter(pool, now)
	mux.HandleFunc("POST /api/v1/notifications/preferences", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Sign in first."})
			return
		}
		var in PreferencesInput
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&in); err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadRequest)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Invalid JSON body."})
			return
		}
		if err := writer.UpdatePreferences(r.Context(), p.UserID, in); err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Could not save notification preferences."})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]any{"saved": true})
	})
}
