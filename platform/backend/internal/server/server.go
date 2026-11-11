// Package server assembles the gateway's HTTP handler from its parts, so the
// process entry point and the integration tests serve exactly the same thing.
package server

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"connectrpc.com/connect"
	"connectrpc.com/grpchealth"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1/clustersv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1/loansv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1/schoolsv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feed"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/health"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/httpmw"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
	loanschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/schema"
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
	clusterStore := clusterlead.NewStore(pool)
	leadership := clusterlead.NewService(clusterStore, time.Now, clusterSchemaReady(pool), logger)
	mux.Handle(clustersv1connect.NewClusterLeadershipServiceHandler(leadership, options...))
	mux.Handle(clustersv1connect.NewClusterMobilizationServiceHandler(
		clusterlead.NewOperations(leadership, clusterStore), options...,
	))
	// The School Loan Application Portal's public pages: no sign-in, no
	// cookie, served as plain HTML for any phone browser.
	loanStore := loans.NewStore(pool)
	loanKeys := loans.DeriveKeys(cfg.JWTSecret)
	public, err := loans.NewPublic(loanStore, loanKeys, cfg.Loans, loans.NewLimiter(time.Now), logger, time.Now)
	if err != nil {
		// The templates are embedded at build time; a parse failure is a
		// broken build, caught by the package's own tests.
		panic(err)
	}
	public.Register(mux)
	mailer := loans.NewMailer(cfg.Loans)
	public.RegisterLender(mux, mailer)
	mux.Handle(loansv1connect.NewLoanReferralServiceHandler(
		loans.NewService(loanStore, cfg.Loans, mailer, LoansSchemaReady(pool), logger, time.Now), options...,
	))
	// Loan origination and servicing. Money is posted to the existing loan
	// ledger as the signed-in person; nothing here writes a balance.
	lending := loans.NewLending(loanStore, loans.NewLedgerClient(cfg.ExistingAppURL), loanKeys, cfg.Loans, mailer,
		loans.NewSMSProvider(cfg.Loans), LoansSchemaReady(pool), logger, time.Now)
	public.RegisterSchool(mux, lending)
	public.RegisterShare(mux)
	mux.Handle(loansv1connect.NewLoanShareServiceHandler(loans.NewShareService(loanStore,
		loans.NewLedgerClient(cfg.ExistingAppURL), cfg.Loans.PublicBaseURL, LoansSchemaReady(pool), logger, time.Now), options...))
	mux.Handle(loansv1connect.NewLendingServiceHandler(loans.NewLendingService(lending), options...))
	mux.Handle("POST /sms/delivery-report/{secret}", loanStore.DeliveryReports(cfg.Loans.SMSCallbackSecret, logger))
	return httpmw.Chain(logger, httpmw.CORS(cfg.CORSAllowedOrigins, mux))
}

// LoansSchemaReady says whether school_loans is at the version this build
// needs. It never migrates: `schemactl migrate --schema=school_loans` does.
func LoansSchemaReady(pool *pgxpool.Pool) func(context.Context) error {
	return func(ctx context.Context) error { return loanschema.Spec.Ready(ctx, pool) }
}

// clusterSchemaReady says whether the Cluster Leader Portal's schema is at the
// version this build needs. It never migrates: `clusterctl migrate` does.
func clusterSchemaReady(pool *pgxpool.Pool) func(context.Context) error {
	return func(ctx context.Context) error {
		applied, err := schema.Version(ctx, pool)
		if err != nil {
			return err
		}
		if applied < schema.Required() {
			return fmt.Errorf("cluster_leadership is at version %d, this build needs %d: run clusterctl migrate",
				applied, schema.Required())
		}
		return nil
	}
}
