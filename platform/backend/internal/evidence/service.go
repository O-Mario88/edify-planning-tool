package evidence

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/privatestore"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Namespace is EVIDENCE_NAMESPACE.
const Namespace = "evidence"

// StagePath is where the web sends a chosen file before the save that uses it.
const StagePath = "/api/v1/files/stage"

// validKinds is EvidenceKind's values.
var validKinds = []string{
	"visit_form", "school_stamp", "attendance_form", "meeting_minutes", "resolutions", "evaluation_form",
	"assessment_form", "photo", "pdf", "project_report", "coaching_notes",
}

// convertible is CONVERTIBLE_EXTENSIONS.
var convertible = []string{".docx", ".doc", ".xlsx", ".xls", ".csv"}

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// Service stages and keeps evidence.
type Service struct {
	db      *pgxpool.Pool
	store   privatestore.Store
	scanner Scanner
	now     func() time.Time
	logger  *slog.Logger
}

// NewService keeps files in store, scanned by scanner.
func NewService(db *pgxpool.Pool, store privatestore.Store, scanner Scanner, now func() time.Time, logger *slog.Logger) *Service {
	return &Service{db: db, store: store, scanner: scanner, now: now, logger: logger}
}

// Staged is a file kept and waiting for its save.
type Staged struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	Size int64  `json:"size"`
}

// storedName is record_upload's f"{uuid.uuid4().hex}{ext}".
func storedName(ext string) (string, error) {
	raw := make([]byte, 16)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	raw[6] = raw[6]&0x0f | 0x40
	raw[8] = raw[8]&0x3f | 0x80
	return hex.EncodeToString(raw) + ext, nil
}

// Stage checks the file and keeps it under a generated name, for p's own
// save to take; a refusal is in the existing gates' words.
func (s *Service) Stage(ctx context.Context, p auth.Principal, name, mime string, body []byte) (Staged, error) {
	ext, err := Check(name, mime, body, int64(len(body)))
	if err != nil {
		return Staged{}, err
	}
	stored, err := storedName(ext)
	if err != nil {
		return Staged{}, fmt.Errorf("evidence: naming the file: %w", err)
	}
	if err := s.store.Put(ctx, Namespace, stored, body, mime); err != nil {
		return Staged{}, fmt.Errorf("evidence: keeping the file: %w", err)
	}
	id := cuid.New()
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return Staged{}, fmt.Errorf("evidence: opening the staging: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT gateway_evidence.stage($1, $2, $3, $4, $5, $6, $7, $8)`,
		id, p.UserID, stored, name, mime, ext, len(body), s.now()); err != nil {
		_ = s.store.Delete(ctx, Namespace, stored)
		return Staged{}, fmt.Errorf("evidence: staging the file: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		_ = s.store.Delete(ctx, Namespace, stored)
		return Staged{}, fmt.Errorf("evidence: committing the staging: %w", err)
	}
	return Staged{ID: id, Name: name, Size: int64(len(body))}, nil
}

// RegisterHTTP serves the staging endpoint: one multipart "file".
func (s *Service) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("POST "+StagePath, func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil || p.UserID == "" {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, MaxFileSize+(1<<20))
		file, header, err := r.FormFile("file")
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "A file is required."})
			return
		}
		defer func() { _ = file.Close() }()
		body, err := io.ReadAll(io.LimitReader(file, MaxFileSize+1))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "The file could not be read."})
			return
		}
		staged, err := s.Stage(r.Context(), p, header.Filename, header.Header.Get("Content-Type"), body)
		var refusal *Refusal
		switch {
		case errors.As(err, &refusal):
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": refusal.Message})
		case err != nil:
			s.logger.ErrorContext(r.Context(), "evidence: the file was not staged", slog.String("error", err.Error()))
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "The file could not be kept. Try again."})
		default:
			writeJSON(w, http.StatusOK, staged)
		}
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// expiredWords is said when the staged file is gone, used, or someone else's.
const expiredWords = "The file you chose is no longer waiting. Choose it again."

// Keep is record_upload for a staged file: kind is the caller's purpose,
// or "" for infer_kind_from_upload's guess. The record's id, or a refusal.
func (s *Service) Keep(ctx context.Context, p auth.Principal, stagedID, activityID, kind string) (string, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", fmt.Errorf("evidence: opening the file: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var stored, original, mime, ext string
	var size int
	err = tx.QueryRow(ctx, `SELECT stored_name, original_name, mime_type, file_extension, file_size
  FROM gateway_evidence.take($1, $2, $3)`, stagedID, p.UserID, s.now()).Scan(&stored, &original, &mime, &ext, &size)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", refuse("%s", expiredWords)
	}
	if err != nil {
		return "", fmt.Errorf("evidence: taking the file: %w", err)
	}
	if kind == "" {
		kind = InferKind(original, mime, "photo")
	}
	if !slices.Contains(validKinds, kind) {
		return "", refuse("Invalid evidence kind: %s", kind)
	}
	if err := s.inScope(ctx, p, activityID); err != nil {
		return "", err
	}
	if (kind == "visit_form" || kind == "attendance_form") && !slices.Contains([]string{".pdf", ".jpg", ".jpeg", ".png", ".webp"}, ext) {
		label := "Visit Form"
		if kind == "attendance_form" {
			label = "Training Attendance"
		}
		return "", refuse("The %s must be uploaded as a PDF or photo (JPG, PNG) — other formats are not accepted for governed forms.", label)
	}
	body, err := s.store.Get(ctx, Namespace, stored)
	if err != nil {
		return "", fmt.Errorf("evidence: reading the kept file: %w", err)
	}
	scan, threat := s.scanner.Scan(body)
	isImage := len(mime) > 6 && mime[:6] == "image/"
	preview := "not_required"
	switch {
	case ext == ".pdf" || mime == "application/pdf" || isImage:
		preview = "ready"
	case slices.Contains(convertible, ext):
		preview = "pending"
	}
	id := cuid.New()
	var found bool
	if err := tx.QueryRow(ctx, `SELECT gateway_evidence.record($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)`,
		id, activityID, kind, stored, original, mime, ext, size, p.UserID, p.ActiveRole, scan, threat, preview,
		s.store.Provider(), s.now()).Scan(&found); err != nil {
		return "", fmt.Errorf("evidence: recording the file: %w", err)
	}
	if !found {
		return "", refuse("Activity not found")
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("evidence: committing the file: %w", err)
	}
	if scan == "infected" {
		return "", refuse("%s", "This file was flagged as a security threat by the malware scanner "+
			"and has been rejected. Contact IT if you believe this is an error.")
	}
	return id, nil
}

// inScope is _assert_activity_in_scope.
func (s *Service) inScope(ctx context.Context, p auth.Principal, activityID string) error {
	var staff, school, cluster, payment string
	var advances bool
	err := s.db.QueryRow(ctx, `SELECT COALESCE(responsible_staff_id, ''), COALESCE(school_id, ''), COALESCE(cluster_id, ''),
  COALESCE(payment_status, ''), EXISTS (SELECT 1 FROM advance_request r WHERE r.activity_id = a.id)
  FROM activity a WHERE a.id = $1 AND a.deleted_at IS NULL`, activityID).Scan(&staff, &school, &cluster, &payment, &advances)
	if errors.Is(err, pgx.ErrNoRows) {
		return refuse("Activity not found")
	}
	if err != nil {
		return fmt.Errorf("evidence: reading the activity: %w", err)
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return fmt.Errorf("evidence: resolving the scope: %w", err)
	}
	if scope.CountryScope {
		if p.ActiveRole == "Accountant" && (payment == "" || payment == "none") && !advances {
			return refuse("%s", "Accountant evidence access is limited to activities with financial involvement.")
		}
		return nil
	}
	switch {
	case staff != "" && (staff == scope.StaffID || staff == p.UserID):
		return nil
	case school != "" && slices.Contains(scope.SchoolIDs, school):
		return nil
	case cluster != "":
		var held bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school WHERE id = ANY($1) AND cluster_id = $2)`,
			scope.SchoolIDs, cluster).Scan(&held); err != nil {
			return fmt.Errorf("evidence: reading the cluster's schools: %w", err)
		}
		if held {
			return nil
		}
	}
	return refuse("Activity outside your scope.")
}
