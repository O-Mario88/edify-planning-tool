// Package health serves the gateway's liveness and readiness endpoints.
//
//	GET /healthz  the process is up. Never touches a dependency.
//	GET /readyz   the process can serve: the database answers.
package health

import (
	"context"
	"net/http"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/httpmw"
)

const (
	checkTimeout = 2 * time.Second
	statusOK     = "ok"
	statusFailed = "failed"
)

// Pinger is a dependency that can be asked whether it is reachable.
type Pinger interface {
	Ping(ctx context.Context) error
}

// Handler serves the two endpoints.
type Handler struct {
	environment string
	release     string
	database    Pinger
}

// NewHandler returns the health handler for a gateway process.
func NewHandler(environment, release string, database Pinger) *Handler {
	return &Handler{environment: environment, release: release, database: database}
}

// Register mounts the endpoints on mux.
func (h *Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /healthz", h.live)
	mux.HandleFunc("GET /readyz", h.ready)
}

func (h *Handler) live(writer http.ResponseWriter, _ *http.Request) {
	httpmw.WriteJSON(writer, http.StatusOK, map[string]string{
		"status":      statusOK,
		"environment": h.environment,
		"release":     h.release,
	})
}

func (h *Handler) ready(writer http.ResponseWriter, request *http.Request) {
	ctx, cancel := context.WithTimeout(request.Context(), checkTimeout)
	defer cancel()

	status, code, database := statusOK, http.StatusOK, statusOK
	// A readiness probe's caller gets no connection details.
	if err := h.database.Ping(ctx); err != nil {
		status, code, database = statusFailed, http.StatusServiceUnavailable, statusFailed
	}
	httpmw.WriteJSON(writer, code, map[string]any{
		"status":      status,
		"environment": h.environment,
		"release":     h.release,
		"checks":      map[string]string{"database": database},
	})
}
