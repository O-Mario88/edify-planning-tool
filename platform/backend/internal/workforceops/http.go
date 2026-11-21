package workforceops

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// RegisterHTTP mounts native Go Workforce Operations REST endpoints on mux.
func (s *Service) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("POST /api/v1/ops/profile", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authWfReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Name  string `json:"name"`
			Phone string `json:"phone"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<14)).Decode(&req); err != nil {
			writeWfJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		if err := s.UpdateOwnProfile(r.Context(), p, req.Name, req.Phone); err != nil {
			writeWfErr(w, err)
			return
		}
		writeWfJSON(w, http.StatusOK, map[string]any{"saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/leave/{id}/decide", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authWfReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Decision string `json:"decision"`
			Note     string `json:"note"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<14)).Decode(&req); err != nil {
			writeWfJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		status, err := s.DecideLeave(r.Context(), p, r.PathValue("id"), req.Decision, req.Note)
		if err != nil {
			writeWfErr(w, err)
			return
		}
		writeWfJSON(w, http.StatusOK, map[string]any{"status": status, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/escalations/{id}/decide", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authWfReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Decision string `json:"decision"`
			Note     string `json:"note"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<14)).Decode(&req); err != nil {
			writeWfJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		status, err := s.DecideEscalation(r.Context(), p, r.PathValue("id"), req.Decision, req.Note)
		if err != nil {
			writeWfErr(w, err)
			return
		}
		writeWfJSON(w, http.StatusOK, map[string]any{"status": status, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/help-feedback", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authWfReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			ArticleID    string `json:"article_id"`
			Helpful      bool   `json:"helpful"`
			FeedbackType string `json:"feedback_type"`
			Comment      string `json:"comment"`
			PageContext  string `json:"page_context"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeWfJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		id, err := s.RecordHelpFeedback(r.Context(), p, req.ArticleID, req.Helpful, req.FeedbackType, req.Comment, req.PageContext)
		if err != nil {
			writeWfErr(w, err)
			return
		}
		writeWfJSON(w, http.StatusCreated, map[string]any{"id": id, "saved": true})
	})
}

func authWfReq(w http.ResponseWriter, r *http.Request, auther Authenticator) (auth.Principal, bool) {
	p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
	if err != nil {
		writeWfJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
		return auth.Principal{}, false
	}
	return p, true
}

func writeWfErr(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrForbidden):
		writeWfJSON(w, http.StatusForbidden, map[string]string{"error": err.Error()})
	case errors.Is(err, ErrInvalidInput):
		writeWfJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
	default:
		writeWfJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not complete workforce operation."})
	}
}

func writeWfJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
