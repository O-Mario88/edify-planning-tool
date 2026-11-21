package fieldops

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// RegisterHTTP mounts native Go Field Operations REST endpoints (M7/M8/M9/M10)
// on mux so web and mobile clients execute writes directly in Go.
func (s *Service) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("POST /api/v1/ops/evidence", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFieldReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			ActivityID   string `json:"activity_id"`
			Kind         string `json:"kind"`
			URI          string `json:"uri"`
			OriginalName string `json:"original_name"`
			MimeType     string `json:"mime_type"`
			Extension    string `json:"extension"`
			FileSize     int    `json:"file_size"`
			Provider     string `json:"provider"`
			Notes        string `json:"notes"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		id, err := s.RecordUpload(r.Context(), p, EvidenceUpload{
			ActivityID: req.ActivityID, Kind: req.Kind, URI: req.URI,
			OriginalName: req.OriginalName, MimeType: req.MimeType, Extension: req.Extension,
			FileSize: req.FileSize, Provider: req.Provider, Notes: req.Notes,
		})
		if err != nil {
			writeFieldErr(w, err)
			return
		}
		writeFieldJSON(w, http.StatusCreated, map[string]any{"id": id, "saved": true})
	})

	mux.HandleFunc("GET /api/v1/ops/evidence/{id}/authorize", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFieldReq(w, r, auther)
		if !ok {
			return
		}
		uri, err := s.AuthorizeEvidenceRead(r.Context(), p, r.PathValue("id"))
		if err != nil {
			writeFieldErr(w, err)
			return
		}
		writeFieldJSON(w, http.StatusOK, map[string]any{"authorized": true, "uri": uri})
	})

	mux.HandleFunc("POST /api/v1/ops/ia/{activityId}/decide", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFieldReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Decision string `json:"decision"`
			Note     string `json:"note"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		status, err := s.IADecideActivity(r.Context(), p, r.PathValue("activityId"), req.Decision, req.Note)
		if err != nil {
			writeFieldErr(w, err)
			return
		}
		writeFieldJSON(w, http.StatusOK, map[string]any{"status": status, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/ssa", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFieldReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			SchoolID      string          `json:"school_id"`
			FY            string          `json:"fy"`
			Quarter       string          `json:"quarter"`
			Date          string          `json:"date"`
			NewEnrollment int             `json:"new_enrollment"`
			Scores        []SSAScoreInput `json:"scores"`
			CollectorType string          `json:"collector_type"`
			ActivityID    string          `json:"activity_id"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		d := time.Now().UTC()
		if strings.TrimSpace(req.Date) != "" {
			parsed, err := time.Parse(time.DateOnly, strings.TrimSpace(req.Date))
			if err != nil {
				writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "date must be YYYY-MM-DD."})
				return
			}
			d = parsed
		}
		id, err := s.EnterSSA(r.Context(), p, SSAEntryRequest{
			SchoolID: req.SchoolID, FY: req.FY, Quarter: req.Quarter, Date: d,
			NewEnrollment: req.NewEnrollment, Scores: req.Scores,
			CollectorType: req.CollectorType, ActivityID: req.ActivityID,
		})
		if err != nil {
			writeFieldErr(w, err)
			return
		}
		writeFieldJSON(w, http.StatusCreated, map[string]any{"id": id, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/ssa/{id}/decide", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFieldReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Decision string `json:"decision"`
			Reason   string `json:"reason"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		status, err := s.DecideSSA(r.Context(), p, r.PathValue("id"), req.Decision, req.Reason)
		if err != nil {
			writeFieldErr(w, err)
			return
		}
		writeFieldJSON(w, http.StatusOK, map[string]any{"status": status, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/partners/handover", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFieldReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			PartnerID    string `json:"partner_id"`
			SchoolID     string `json:"school_id"`
			Purpose      string `json:"purpose"`
			Intervention string `json:"intervention"`
			ActivityType string `json:"activity_type"`
			Notes        string `json:"notes"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		id, err := s.HandOverToPartner(r.Context(), p, req.PartnerID, req.SchoolID, req.Purpose, req.Intervention, req.ActivityType, req.Notes)
		if err != nil {
			writeFieldErr(w, err)
			return
		}
		writeFieldJSON(w, http.StatusCreated, map[string]any{"id": id, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/partners/{id}/date", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFieldReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Date string `json:"date"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<14)).Decode(&req); err != nil {
			writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		d, err := time.Parse(time.DateOnly, strings.TrimSpace(req.Date))
		if err != nil {
			writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "date must be YYYY-MM-DD."})
			return
		}
		status, err := s.DatePartnerAssignment(r.Context(), p, r.PathValue("id"), d)
		if err != nil {
			writeFieldErr(w, err)
			return
		}
		writeFieldJSON(w, http.StatusOK, map[string]any{"status": status, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/partners/{id}/return", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFieldReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Reason string `json:"reason"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<14)).Decode(&req); err != nil {
			writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		status, err := s.ReturnPartnerAssignment(r.Context(), p, r.PathValue("id"), req.Reason)
		if err != nil {
			writeFieldErr(w, err)
			return
		}
		writeFieldJSON(w, http.StatusOK, map[string]any{"status": status, "saved": true})
	})
}

func authFieldReq(w http.ResponseWriter, r *http.Request, auther Authenticator) (auth.Principal, bool) {
	p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
	if err != nil {
		writeFieldJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
		return auth.Principal{}, false
	}
	return p, true
}

func writeFieldErr(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrForbidden), errors.Is(err, ErrQuarantined):
		writeFieldJSON(w, http.StatusForbidden, map[string]string{"error": err.Error()})
	case errors.Is(err, ErrInvalidInput):
		writeFieldJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
	default:
		writeFieldJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not complete field operation."})
	}
}

func writeFieldJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
