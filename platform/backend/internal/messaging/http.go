package messaging

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
)

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// ThreadMessage is one message inside an opened conversation.
type ThreadMessage struct {
	ID                string    `json:"id"`
	SenderID          string    `json:"senderId"`
	SenderName        string    `json:"senderName"`
	Body              string    `json:"body"`
	IsSystemGenerated bool      `json:"isSystemGenerated"`
	CreatedAt         time.Time `json:"createdAt"`
}

// ThreadDetail is the full native Go conversation view (marks thread read).
type ThreadDetail struct {
	ID                string          `json:"id"`
	Subject           string          `json:"subject"`
	Priority          string          `json:"priority"`
	IsSystemGenerated bool            `json:"isSystemGenerated"`
	Starred           bool            `json:"starred"`
	Archived          bool            `json:"archived"`
	ContextType       string          `json:"contextType,omitempty"`
	ContextID         string          `json:"contextId,omitempty"`
	Participants      []string        `json:"participants"`
	Messages          []ThreadMessage `json:"messages"`
}

// RecipientOption is one active user the caller can start a conversation with.
type RecipientOption struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	ActiveRole string `json:"activeRole"`
}

// NativeStore executes native Go messaging reads & writes through gateway_messaging.
type NativeStore struct {
	pool   *pgxpool.Pool
	writer *notificationcenter.Writer
	now    func() time.Time
}

// NewNativeStore builds a Django-independent messaging store.
func NewNativeStore(pool *pgxpool.Pool, writer *notificationcenter.Writer, now func() time.Time) *NativeStore {
	if now == nil {
		now = time.Now
	}
	return &NativeStore{pool: pool, writer: writer, now: now}
}

// OpenThread verifies caller is a participant, marks the thread read, and
// returns its full message history. Unrelated accounts are refused.
func (s *NativeStore) OpenThread(ctx context.Context, p auth.Principal, threadID string) (ThreadDetail, error) {
	var detail ThreadDetail
	var archivedAt *time.Time
	err := s.pool.QueryRow(ctx, `
SELECT t.id, t.subject, COALESCE(t.priority, 'normal'), t.is_system_generated,
       COALESCE(t.context_type, ''), COALESCE(t.context_id, ''),
       mp.starred, mp.archived_at
  FROM messaging_messagethread t
  JOIN messaging_messageparticipant mp ON mp.thread_id = t.id AND mp.user_id = $2
 WHERE t.id = $1`, threadID, p.UserID).Scan(
		&detail.ID, &detail.Subject, &detail.Priority, &detail.IsSystemGenerated,
		&detail.ContextType, &detail.ContextID, &detail.Starred, &archivedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return ThreadDetail{}, fmt.Errorf("FORBIDDEN: Conversation not found or access denied.")
	}
	if err != nil {
		return ThreadDetail{}, err
	}
	detail.Archived = archivedAt != nil

	// Mark thread read for this participant atomically.
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return ThreadDetail{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var marked bool
	if err := tx.QueryRow(ctx, `SELECT gateway_messaging.mark_thread_read($1, $2, $3)`,
		threadID, p.UserID, s.now().UTC()).Scan(&marked); err != nil {
		return ThreadDetail{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return ThreadDetail{}, err
	}

	// Participants list.
	pRows, err := s.pool.Query(ctx, `
SELECT COALESCE(u.name, mp.user_id)
  FROM messaging_messageparticipant mp
  LEFT JOIN "user" u ON u.id = mp.user_id
 WHERE mp.thread_id = $1
 ORDER BY mp.created_at ASC`, threadID)
	if err != nil {
		return ThreadDetail{}, err
	}
	for pRows.Next() {
		var name string
		if scanErr := pRows.Scan(&name); scanErr == nil {
			detail.Participants = append(detail.Participants, name)
		}
	}
	pRows.Close()

	// Ordered messages via SECURITY DEFINER participant-gated reader.
	mRows, err := s.pool.Query(ctx, `
SELECT id, sender_id, sender_name, body, is_system_generated, created_at
  FROM gateway_messaging.read_thread_messages($1, $2)`, threadID, p.UserID)
	if err != nil {
		return ThreadDetail{}, err
	}
	defer mRows.Close()
	detail.Messages = []ThreadMessage{}
	for mRows.Next() {
		var msg ThreadMessage
		if err := mRows.Scan(&msg.ID, &msg.SenderID, &msg.SenderName, &msg.Body, &msg.IsSystemGenerated, &msg.CreatedAt); err != nil {
			return ThreadDetail{}, err
		}
		detail.Messages = append(detail.Messages, msg)
	}
	return detail, mRows.Err()
}

// Reply sends a reply in a non-system thread and notifies other participants.
func (s *NativeStore) Reply(ctx context.Context, p auth.Principal, threadID, body string) (string, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var msgID, subject string
	var recipients []string
	if err := tx.QueryRow(ctx,
		`SELECT message_id, recipient_ids, subject FROM gateway_messaging.send_reply($1, $2, $3, $4)`,
		threadID, p.UserID, body, s.now().UTC(),
	).Scan(&msgID, &recipients, &subject); err != nil {
		return "", err
	}
	if err := tx.Commit(ctx); err != nil {
		return "", err
	}
	s.notifyRecipients(ctx, p, recipients, threadID, msgID, subject, body)
	return msgID, nil
}

// Compose creates a new thread with recipients and delivers notifications.
func (s *NativeStore) Compose(
	ctx context.Context, p auth.Principal, recipientIDs []string, subject, body, priority, contextType, contextID string,
) (string, string, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", "", err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var threadID, msgID string
	var cleanRecipients []string
	if err := tx.QueryRow(ctx,
		`SELECT thread_id, message_id, recipient_ids
		   FROM gateway_messaging.create_thread($1, $2, $3, $4, $5, $6, $7, $8)`,
		p.UserID, recipientIDs, subject, body, priority, contextType, contextID, s.now().UTC(),
	).Scan(&threadID, &msgID, &cleanRecipients); err != nil {
		return "", "", err
	}
	if err := tx.Commit(ctx); err != nil {
		return "", "", err
	}
	s.notifyRecipients(ctx, p, cleanRecipients, threadID, msgID, subject, body)
	return threadID, msgID, nil
}

// UpdateState stars/unstars or archives/unarchives a thread for caller only.
func (s *NativeStore) UpdateState(ctx context.Context, p auth.Principal, threadID, action string) error {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var changed bool
	if err := tx.QueryRow(ctx,
		`SELECT gateway_messaging.update_participant_state($1, $2, $3, $4)`,
		threadID, p.UserID, action, s.now().UTC(),
	).Scan(&changed); err != nil {
		return err
	}
	if !changed {
		return fmt.Errorf("FORBIDDEN: Conversation not found or access denied.")
	}
	return tx.Commit(ctx)
}

// ListRecipients returns active same-country users available for messaging.
func (s *NativeStore) ListRecipients(ctx context.Context, p auth.Principal, q string) ([]RecipientOption, error) {
	pattern := "%" + strings.TrimSpace(q) + "%"
	rows, err := s.pool.Query(ctx, `
SELECT u.id, u.name, u.active_role
  FROM "user" u
 WHERE u.deleted_at IS NULL
   AND u.is_active = true
   AND u.id <> $1
   AND ($2 = '%%' OR u.name ILIKE $2 OR u.email ILIKE $2 OR u.active_role ILIKE $2)
   AND (
     NOT EXISTS (
       SELECT 1 FROM country_registry.country_membership cm
        WHERE cm.user_id = $1 AND cm.revoked_at IS NULL AND cm.effective_until IS NULL
     )
     OR EXISTS (
       SELECT 1
         FROM country_registry.country_membership mine
         JOIN country_registry.country_membership theirs
           ON theirs.country_id = mine.country_id
          AND theirs.user_id = u.id
          AND theirs.revoked_at IS NULL
          AND theirs.effective_until IS NULL
        WHERE mine.user_id = $1 AND mine.revoked_at IS NULL AND mine.effective_until IS NULL
     )
   )
 ORDER BY u.name ASC
 LIMIT 100`, p.UserID, pattern)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []RecipientOption{}
	for rows.Next() {
		var r RecipientOption
		if err := rows.Scan(&r.ID, &r.Name, &r.ActiveRole); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (s *NativeStore) notifyRecipients(ctx context.Context, sender auth.Principal, recipients []string, threadID, msgID, subject, body string) {
	if s.writer == nil {
		return
	}
	snippet := strings.TrimSpace(body)
	if len(snippet) > 160 {
		snippet = snippet[:157] + "..."
	}
	senderLabel := sender.Name
	if senderLabel == "" {
		senderLabel = sender.ActiveRole
	}
	for _, rec := range recipients {
		_, _ = s.writer.Deliver(ctx, notificationcenter.Delivery{
			RecipientID:     rec,
			SenderID:        sender.UserID,
			Title:           fmt.Sprintf("New message from %s: %s", senderLabel, subject),
			Body:            snippet,
			Category:        "message",
			ContextType:     "message_thread",
			ContextID:       threadID,
			TargetRoute:     "/messages?thread=" + threadID,
			ActionLabel:     "Open conversation",
			Priority:        "normal",
			SourceEventType: "messaging.reply",
			SourceEventID:   msgID,
		})
	}
}

// RegisterHTTP mounts the native Go messaging REST endpoints on mux.
func (s *NativeStore) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("GET /api/v1/messages/recipients", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeMsgJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		recs, err := s.ListRecipients(r.Context(), p, r.URL.Query().Get("q"))
		if err != nil {
			writeMsgJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not load recipients."})
			return
		}
		writeMsgJSON(w, http.StatusOK, map[string]any{"recipients": recs})
	})

	mux.HandleFunc("GET /api/v1/messages/threads/{id}", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeMsgJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		detail, err := s.OpenThread(r.Context(), p, r.PathValue("id"))
		if err != nil {
			code := http.StatusInternalServerError
			if strings.Contains(err.Error(), "FORBIDDEN:") {
				code = http.StatusForbidden
			}
			writeMsgJSON(w, code, map[string]string{"error": err.Error()})
			return
		}
		writeMsgJSON(w, http.StatusOK, detail)
	})

	mux.HandleFunc("POST /api/v1/messages/threads", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeMsgJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		var in struct {
			RecipientIDs []string `json:"recipientIds"`
			Subject      string   `json:"subject"`
			Body         string   `json:"body"`
			Priority     string   `json:"priority"`
			ContextType  string   `json:"contextType"`
			ContextID    string   `json:"contextId"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<18)).Decode(&in); err != nil {
			writeMsgJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		threadID, msgID, err := s.Compose(r.Context(), p, in.RecipientIDs, in.Subject, in.Body, in.Priority, in.ContextType, in.ContextID)
		if err != nil {
			writeMsgJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeMsgJSON(w, http.StatusCreated, map[string]string{"threadId": threadID, "messageId": msgID})
	})

	mux.HandleFunc("POST /api/v1/messages/threads/{id}/reply", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeMsgJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		var in struct {
			Body string `json:"body"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<18)).Decode(&in); err != nil {
			writeMsgJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		msgID, err := s.Reply(r.Context(), p, r.PathValue("id"), in.Body)
		if err != nil {
			code := http.StatusBadRequest
			if strings.Contains(err.Error(), "FORBIDDEN:") {
				code = http.StatusForbidden
			} else if strings.Contains(err.Error(), "READONLY:") {
				code = http.StatusConflict
			}
			writeMsgJSON(w, code, map[string]string{"error": err.Error()})
			return
		}
		writeMsgJSON(w, http.StatusCreated, map[string]string{"messageId": msgID})
	})

	mux.HandleFunc("POST /api/v1/messages/threads/{id}/state", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeMsgJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		var in struct {
			Action string `json:"action"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<14)).Decode(&in); err != nil {
			writeMsgJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		if err := s.UpdateState(r.Context(), p, r.PathValue("id"), in.Action); err != nil {
			code := http.StatusBadRequest
			if strings.Contains(err.Error(), "FORBIDDEN:") {
				code = http.StatusForbidden
			}
			writeMsgJSON(w, code, map[string]string{"error": err.Error()})
			return
		}
		writeMsgJSON(w, http.StatusOK, map[string]bool{"ok": true})
	})
}

func writeMsgJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
