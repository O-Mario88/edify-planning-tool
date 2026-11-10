// Package server assembles the gateway's HTTP handler from its parts, so the
// process entry point and the integration tests serve exactly the same thing.
package server

import (
	"log/slog"
	"net/http"
	"time"

	"connectrpc.com/connect"
	"connectrpc.com/grpchealth"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1/schoolsv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feed"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/health"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/httpmw"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/screens"
)

const maxRequestBytes = 1 << 20

// New returns the gateway handler. summarizer may be nil.
func New(cfg config.Config, pool *pgxpool.Pool, summarizer schools.Summarizer, logger *slog.Logger) http.Handler {
	authenticator := auth.NewAuthenticator(
		auth.NewVerifier(cfg.JWTSecret, time.Now),
		identity.NewStore(pool),
	)
	// Outermost first: errors are structured, then the caller is authenticated.
	options := []connect.HandlerOption{
		connect.WithInterceptors(apierr.Interceptor(logger), authenticator.Interceptor()),
		connect.WithReadMaxBytes(maxRequestBytes),
	}

	mux := http.NewServeMux()
	health.NewHandler(string(cfg.Env), cfg.Release, pool).Register(mux)
	mux.Handle(grpchealth.NewHandler(grpchealth.NewStaticChecker(
		identityv1connect.IdentityServiceName,
		schoolsv1connect.SchoolServiceName,
	)))
	mux.Handle(identityv1connect.NewIdentityServiceHandler(identity.NewService(), options...))
	mux.Handle(schoolsv1connect.NewSchoolServiceHandler(
		schools.NewService(schools.NewStore(pool), summarizer, logger), options...,
	))
	var existingApp screens.Fetcher
	if cfg.ExistingAppURL != "" {
		existingApp = feed.NewClient(cfg.ExistingAppURL, logger)
	}
	screenService := screens.NewService(existingApp)
	mux.Handle(screensv1connect.NewHomeScreenServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewNavigationServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewSchoolDirectoryScreenServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewSchoolActionServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewSchoolProfileServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewSchoolDrawerServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewPlanningDrawerServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewMyPlanScreenServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewPageScreenServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewPageDrawerServiceHandler(screenService, options...))
	mux.Handle(screensv1connect.NewExportServiceHandler(screenService, options...))
	return httpmw.Chain(logger, httpmw.CORS(cfg.CORSAllowedOrigins, mux))
}
