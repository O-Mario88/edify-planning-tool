package support

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
)

// Authenticator authenticates a Bearer Authorization header into a Principal.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// forbiddenContextKeys mirrors apps/admin_ops/services.py _FORBIDDEN_CONTEXT_KEYS (§11).
var forbiddenContextKeys = map[string]bool{
	"password":      true,
	"token":         true,
	"secret":        true,
	"authorization": true,
	"cookie":        true,
}

// allowedTransitions mirrors apps/admin_ops/services.py _TICKET_TRANSITIONS (§12).
var allowedTransitions = map[string]map[string]bool{
	"submitted":       {"triaged": true, "duplicate": true, "invalid": true, "cancelled": true},
	"triaged":         {"more_info": true, "planned": true, "in_progress": true, "duplicate": true, "invalid": true},
	"more_info":       {"triaged": true, "cancelled": true},
	"planned":         {"in_progress": true, "cancelled": true},
	"in_progress":     {"waiting_on_user": true, "fix_ready": true},
	"waiting_on_user": {"in_progress": true, "cancelled": true},
	"fix_ready":       {"verification": true},
	"verification":    {"resolved": true, "in_progress": true},
	"resolved":        {"closed": true, "reopened": true},
	"closed":          {"reopened": true},
	"reopened":        {"triaged": true},
}

// Ticket is one support ticket visible to its reporter or an Admin.
type Ticket struct {
	ID           string     `json:"id"`
	Reference    string     `json:"reference"`
	Title        string     `json:"title"`
	Category     string     `json:"category"`
	Description  string     `json:"description"`
	Urgency      string     `json:"urgency"`
	Status       string     `json:"status"`
	ReporterID   string     `json:"reporterId"`
	ReporterRole string     `json:"reporterRole"`
	Route        string     `json:"route"`
	Resolution   string     `json:"resolution"`
	CreatedAt    time.Time  `json:"createdAt"`
	ResolvedAt   *time.Time `json:"resolvedAt,omitempty"`
}

// CreateInput is the request payload for creating a support ticket.
type CreateInput struct {
	Title       string            `json:"title"`
	Category    string            `json:"category"`
	Description string            `json:"description"`
	Urgency     string            `json:"urgency"`
	Context     map[string]string `json:"context"`
}

// Service owns the native Go support ticket workflow.
type Service struct {
	pool   *pgxpool.Pool
	writer *notificationcenter.Writer
	now    func() time.Time
}

// NewService constructs a native Go Support Ticket service.
func NewService(pool *pgxpool.Pool, writer *notificationcenter.Writer, now func() time.Time) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{pool: pool, writer: writer, now: now}
}

// Create submits a new support ticket, persists audit_log/domain_event_log,
// and notifies active Admins natively.
func (s *Service) Create(ctx context.Context, p auth.Principal, in CreateInput) (Ticket, error) {
	for k := range in.Context {
		if forbiddenContextKeys[strings.ToLower(strings.TrimSpace(k))] {
			return Ticket{}, fmt.Errorf("support context must never carry sensitive key %q", k)
		}
	}
	title := strings.TrimSpace(in.Title)
	if title == "" {
		return Ticket{}, fmt.Errorf("A short summary of the problem is required.")
	}
	cat := strings.TrimSpace(in.Category)
	if cat == "" {
		cat = "other"
	}
	urg := strings.ToLower(strings.TrimSpace(in.Urgency))
	switch urg {
	case "low", "medium", "high", "critical":
	default:
		urg = "medium"
	}
	now := s.now().UTC()
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return Ticket{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var id, ref string
	if err := tx.QueryRow(ctx, `
SELECT ticket_id, reference FROM gateway_support.create_ticket(
  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
)`,
		title, cat, strings.TrimSpace(in.Description), urg,
		p.UserID, p.ActiveRole,
		in.Context["route"], in.Context["page_title"],
		in.Context["object_type"], in.Context["object_id"],
		in.Context["browser"], in.Context["request_id"], now,
	).Scan(&id, &ref); err != nil {
		return Ticket{}, err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action:      "admin_ops.ticket.submitted",
		SubjectKind: audit.Text("support_ticket"),
		SubjectID:   audit.Text(id),
		ActorID:     audit.Text(p.UserID),
		ActorRole:   audit.Text(p.ActiveRole),
		Success:     true,
		Payload: map[string]any{
			"reference": ref,
			"category":  cat,
			"urgency":   urg,
		},
	}, now); err != nil {
		return Ticket{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Ticket{}, err
	}

	// Notify active Admins natively (matches SupportTicketService.create).
	if s.writer != nil {
		prio := "high"
		if urg == "critical" {
			prio = "urgent"
		}
		rows, err := s.pool.Query(ctx, `SELECT id FROM "user"
WHERE deleted_at IS NULL AND is_active = true AND (active_role = 'Admin' OR 'Admin' = ANY(roles))`)
		if err == nil {
			var adminIDs []string
			for rows.Next() {
				var aid string
				if scanErr := rows.Scan(&aid); scanErr == nil && aid != "" {
					adminIDs = append(adminIDs, aid)
				}
			}
			rows.Close()
			routeLabel := in.Context["route"]
			if routeLabel == "" {
				routeLabel = "the app"
			}
			for _, aid := range adminIDs {
				_, _ = s.writer.Deliver(ctx, notificationcenter.Delivery{
					RecipientID:     aid,
					SenderID:        p.UserID,
					Title:           fmt.Sprintf("Support ticket %s: %s", ref, title),
					Body:            fmt.Sprintf("%s reported %s on %s.", p.ActiveRole, cat, routeLabel),
					Category:        "support",
					ContextType:     "support_ticket",
					ContextID:       id,
					TargetRoute:     "/support",
					ActionLabel:     "Review ticket",
					ActionRequired:  true,
					Priority:        prio,
					SourceEventType: "admin_ops.ticket.created",
					SourceEventID:   id,
				})
			}
		}
	}

	return Ticket{
		ID: id, Reference: ref, Title: title, Category: cat, Description: strings.TrimSpace(in.Description),
		Urgency: urg, Status: "submitted", ReporterID: p.UserID, ReporterRole: p.ActiveRole,
		Route: in.Context["route"], CreatedAt: now,
	}, nil
}

// List returns the caller's own tickets (or all recent tickets when Admin).
func (s *Service) List(ctx context.Context, p auth.Principal, limit int) ([]Ticket, error) {
	isAdmin := p.ActiveRole == "Admin"
	rows, err := s.pool.Query(ctx,
		`SELECT id, reference, title, category, description, urgency, status,
		        reporter_id, reporter_role, route, resolution, created_at, resolved_at
		   FROM gateway_support.list_tickets($1, $2, $3)`,
		p.UserID, isAdmin, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Ticket{}
	for rows.Next() {
		var t Ticket
		if err := rows.Scan(
			&t.ID, &t.Reference, &t.Title, &t.Category, &t.Description, &t.Urgency, &t.Status,
			&t.ReporterID, &t.ReporterRole, &t.Route, &t.Resolution, &t.CreatedAt, &t.ResolvedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

// Transition moves a support ticket to a new status (Admin only) and notifies
// the reporter when resolved.
func (s *Service) Transition(ctx context.Context, p auth.Principal, ticketID, toStatus, note string) (Ticket, error) {
	if p.ActiveRole != "Admin" {
		return Ticket{}, fmt.Errorf("FORBIDDEN: Platform operations are Admin-only.")
	}
	var currentStatus string
	if err := s.pool.QueryRow(ctx, `SELECT status FROM admin_support_ticket WHERE id = $1`, ticketID).Scan(&currentStatus); err != nil {
		return Ticket{}, fmt.Errorf("NOT_FOUND: Support ticket not found.")
	}
	if !allowedTransitions[currentStatus][toStatus] {
		return Ticket{}, fmt.Errorf("A ticket in %q cannot move to %q.", currentStatus, toStatus)
	}

	now := s.now().UTC()
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return Ticket{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var id, ref, reporterID, fromSt, toSt string
	if err := tx.QueryRow(ctx,
		`SELECT ticket_id, reference, reporter_id, from_status, to_status
		   FROM gateway_support.transition_ticket($1, $2, $3, $4, $5)`,
		ticketID, toStatus, p.UserID, note, now,
	).Scan(&id, &ref, &reporterID, &fromSt, &toSt); err != nil {
		return Ticket{}, err
	}
	actorID := p.UserID
	if actorID == "" {
		actorID = "system"
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action:      "admin_ops.ticket." + toSt,
		SubjectKind: audit.Text("support_ticket"),
		SubjectID:   audit.Text(id),
		ActorID:     audit.Text(actorID),
		ActorRole:   audit.Text("Admin"),
		Success:     true,
		Reason:      audit.Text(strings.TrimSpace(note)),
		Payload: map[string]any{
			"from":      fromSt,
			"to":        toSt,
			"reference": ref,
		},
	}, now); err != nil {
		return Ticket{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Ticket{}, err
	}

	if s.writer != nil && toSt == "resolved" && reporterID != "" {
		body := strings.TrimSpace(note)
		if body == "" {
			body = "The reported problem has been fixed."
		}
		_, _ = s.writer.Deliver(ctx, notificationcenter.Delivery{
			RecipientID:     reporterID,
			SenderID:        p.UserID,
			Title:           fmt.Sprintf("Your support ticket %s is resolved", ref),
			Body:            body,
			Category:        "support",
			ContextType:     "support_ticket_reporter",
			ContextID:       id,
			TargetRoute:     "/support",
			ActionLabel:     "View ticket",
			Priority:        "normal",
			SourceEventType: "admin_ops.ticket.resolved",
			SourceEventID:   id,
		})
	}
	return Ticket{ID: id, Reference: ref, Status: toSt, ReporterID: reporterID, Resolution: note}, nil
}

// Register mounts the authenticated JSON HTTP endpoints on mux.
func (s *Service) Register(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("GET /api/v1/support/tickets", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		tickets, err := s.List(r.Context(), p, 50)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not load support tickets."})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"tickets": tickets, "isAdmin": p.ActiveRole == "Admin"})
	})

	mux.HandleFunc("POST /api/v1/support/tickets", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		var in CreateInput
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<18)).Decode(&in); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		ticket, err := s.Create(r.Context(), p, in)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusCreated, map[string]any{"ticket": ticket})
	})

	mux.HandleFunc("POST /api/v1/support/tickets/{id}/transition", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in to continue."})
			return
		}
		var body struct {
			ToStatus string `json:"toStatus"`
			Note     string `json:"note"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&body); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		ticket, err := s.Transition(r.Context(), p, r.PathValue("id"), body.ToStatus, body.Note)
		if err != nil {
			code := http.StatusBadRequest
			if strings.HasPrefix(err.Error(), "FORBIDDEN:") {
				code = http.StatusForbidden
			} else if strings.HasPrefix(err.Error(), "NOT_FOUND:") {
				code = http.StatusNotFound
			}
			writeJSON(w, code, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"ticket": ticket})
	})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
