package financeops

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

// RegisterHTTP mounts native Go Finance Operations REST endpoints (M12) on mux.
func (s *Service) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("POST /api/v1/ops/weekly-requests", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFinReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			FY            string `json:"fy"`
			WeekStart     string `json:"week_start"`
			WeekEnd       string `json:"week_end"`
			TotalAmount   int64  `json:"total_amount"`
			FundingSource string `json:"funding_source"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFinJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		ws, err := time.Parse(time.DateOnly, strings.TrimSpace(req.WeekStart))
		if err != nil {
			writeFinJSON(w, http.StatusBadRequest, map[string]string{"error": "week_start must be YYYY-MM-DD."})
			return
		}
		we := ws.AddDate(0, 0, 6)
		if strings.TrimSpace(req.WeekEnd) != "" {
			if parsed, perr := time.Parse(time.DateOnly, strings.TrimSpace(req.WeekEnd)); perr == nil {
				we = parsed
			}
		}
		id, err := s.SubmitWeeklyRequest(r.Context(), p, WeeklySubmitRequest{
			FY: req.FY, WeekStart: ws, WeekEnd: we,
			TotalAmount: req.TotalAmount, FundingSource: req.FundingSource,
		})
		if err != nil {
			writeFinErr(w, err)
			return
		}
		writeFinJSON(w, http.StatusCreated, map[string]any{"id": id, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/weekly-requests/{id}/transition", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFinReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Action    string `json:"action"`
			Amount    int64  `json:"amount"`
			Returned  int64  `json:"returned"`
			Method    string `json:"method"`
			Reference string `json:"reference"`
			Reason    string `json:"reason"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFinJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		res, err := s.TransitionWeeklyRequest(r.Context(), p, r.PathValue("id"), req.Action,
			req.Amount, req.Returned, req.Method, req.Reference, req.Reason)
		if err != nil {
			writeFinErr(w, err)
			return
		}
		writeFinJSON(w, http.StatusOK, map[string]any{"status": res.Status, "applied": res.Applied, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/monthly-budgets/{id}/decide", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFinReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Status string `json:"status"`
			Note   string `json:"note"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFinJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		status, err := s.DecideMonthlyBudget(r.Context(), p, r.PathValue("id"), req.Status, req.Note)
		if err != nil {
			writeFinErr(w, err)
			return
		}
		writeFinJSON(w, http.StatusOK, map[string]any{"status": status, "saved": true})
	})

	mux.HandleFunc("POST /api/v1/ops/advances/{id}/transition", func(w http.ResponseWriter, r *http.Request) {
		p, ok := authFinReq(w, r, auther)
		if !ok {
			return
		}
		var req struct {
			Action    string `json:"action"`
			Amount    int64  `json:"amount"`
			Returned  int64  `json:"returned"`
			Method    string `json:"method"`
			Reference string `json:"reference"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
			writeFinJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON body."})
			return
		}
		res, err := s.TransitionAdvance(r.Context(), p, r.PathValue("id"), req.Action,
			req.Amount, req.Returned, req.Method, req.Reference)
		if err != nil {
			writeFinErr(w, err)
			return
		}
		writeFinJSON(w, http.StatusOK, map[string]any{"status": res.Status, "applied": res.Applied, "saved": true})
	})
}

func authFinReq(w http.ResponseWriter, r *http.Request, auther Authenticator) (auth.Principal, bool) {
	p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
	if err != nil {
		writeFinJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
		return auth.Principal{}, false
	}
	return p, true
}

func writeFinErr(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrForbidden):
		writeFinJSON(w, http.StatusForbidden, map[string]string{"error": err.Error()})
	case errors.Is(err, ErrInvalidInput):
		writeFinJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
	default:
		writeFinJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not complete finance operation."})
	}
}

func writeFinJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
