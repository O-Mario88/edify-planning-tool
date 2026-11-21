package exports

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// Filename returns a clean CSV filename for a completed export job.
func (j *Job) Filename() string {
	return fmt.Sprintf("%s-%s.csv", j.Kind, j.CreatedAt.UTC().Format("2006-01-02"))
}

// RegisterHTTP mounts native Go CSV export endpoints:
//   - POST /api/v1/exports
//   - GET  /api/v1/exports/{id}/download
func (m *Manager) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("POST /api/v1/exports", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeExportJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		var req struct {
			Kind string `json:"kind"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<14)).Decode(&req); err != nil {
			writeExportJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		kind := strings.TrimSpace(req.Kind)
		job, err := m.CreateAndRun(r.Context(), p, kind)
		if err != nil {
			switch {
			case errors.Is(err, ErrUnknownKind):
				writeExportJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			case errors.Is(err, ErrForbidden):
				writeExportJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot run this export."})
			default:
				writeExportJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not generate export."})
			}
			return
		}
		writeExportJSON(w, http.StatusCreated, map[string]any{
			"id":           job.ID,
			"kind":         job.Kind,
			"status":       "ready",
			"filename":     job.Filename(),
			"row_count":    job.RowCount,
			"sha256":       job.SHA256,
			"download_url": "/api/v1/exports/" + job.ID + "/download",
		})
	})

	mux.HandleFunc("GET /api/v1/exports/{id}/download", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeExportJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		jobID := strings.TrimSpace(r.PathValue("id"))
		job, err := m.AuthorizeDownload(p, jobID)
		if err != nil {
			switch {
			case errors.Is(err, ErrNotFound):
				writeExportJSON(w, http.StatusNotFound, map[string]string{"error": "Export job not found."})
			case errors.Is(err, ErrForbidden):
				writeExportJSON(w, http.StatusForbidden, map[string]string{"error": "You are not authorized to download this export."})
			default:
				writeExportJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not load export."})
			}
			return
		}
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, job.Filename()))
		w.Header().Set("X-Content-SHA256", job.SHA256)
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(job.Payload)
	})
}

func writeExportJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
