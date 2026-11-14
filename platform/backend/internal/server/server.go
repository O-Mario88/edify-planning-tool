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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/messaging/v1/messagingv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1/schoolsv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accounts"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/acting"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ccelead"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closurequality"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusteroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreoversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coverage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dataquality"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/escalations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/extrawork"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feed"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fyplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/health"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/httpmw"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iaframework"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/leavepolicies"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/leavetracker"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
	loanschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/messaging"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myactions"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/navigation"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/oversightportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownership"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerusers"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/peopledirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/perfcycle"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningoversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/policycompliance"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/programmeschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectmonitoring"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/qualityflags"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/reports"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rolesmatrix"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/screens"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/signin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ssaverify"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/staffactivity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/staffsetup"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teamperformance"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teams"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workplan"
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
	// The signed-in person's own account, and account administration.
	accountService := accountsService(cfg, pool, logger)
	accountHandler := accounts.NewHandler(accountService, logger)
	mux.Handle(identityv1connect.NewAccountServiceHandler(accountHandler, options...))
	mux.Handle(identityv1connect.NewAccountAdminServiceHandler(accountHandler, options...))
	// Staff and partner teams; member logins are accounts.
	teamStore := teams.NewStore(pool)
	teamHandler := teams.NewHandler(
		teams.NewStaffService(teamStore, time.Now, accountService.StaffChanged),
		teams.NewPartnerService(teamStore, accountService, time.Now), logger)
	mux.Handle(identityv1connect.NewStaffTeamServiceHandler(teamHandler, options...))
	mux.Handle(identityv1connect.NewPartnerTeamServiceHandler(teamHandler, options...))
	actingHandler := acting.NewHandler(acting.NewService(acting.NewStore(pool), time.Now, accountService.ActingNotice, accountService.IssueToken), logger)
	mux.Handle(identityv1connect.NewActingLeadershipServiceHandler(actingHandler, options...))
	// Signing in needs no session: structured errors, no authentication.
	mux.Handle(identityv1connect.NewSignInServiceHandler(signInHandler(cfg, pool, logger),
		connect.WithInterceptors(apierr.Interceptor(logger)), connect.WithReadMaxBytes(maxRequestBytes)))
	mux.Handle(schoolsv1connect.NewSchoolServiceHandler(
		schools.NewService(schools.NewStore(pool), summarizer, logger), options...,
	))
	var existingApp screens.Fetcher
	if cfg.ExistingAppURL != "" {
		existingApp = feed.NewClient(cfg.ExistingAppURL, logger)
	}
	screenService := screens.NewService(existingApp).
		WithDirectory(schooldirectory.NewService(pool, time.Now), logger).
		WithProfile(schoolprofile.NewService(pool, time.Now), logger).
		WithNavigation(navigation.NewService(pool)).
		WithPages(logger,
			clusterpage.NewService(pool, time.Now),
			closedschools.NewService(pool, time.Now),
			programmeschools.NewService(pool, time.Now),
			clusteroversight.NewService(pool, time.Now),
			planningpage.NewService(pool, time.Now),
			decisionlog.NewService(pool, time.Now),
			escalations.NewService(pool, time.Now),
			qualityflags.NewService(pool, time.Now),
			projectcapacity.NewService(pool, time.Now),
			adminops.NewService(pool),
			fyplanning.NewService(pool, time.Now),
			policycompliance.NewService(pool, time.Now),
			partnerusers.NewService(teams.NewPartnerService(teamStore, accountService, time.Now)),
			staffsetup.NewService(pool),
			rolesmatrix.NewService(pool),
			plreview.NewService(pool, time.Now),
			perfcycle.NewService(pool, time.Now),
			closurequality.NewService(pool, time.Now),
			iaframework.NewService(pool),
			ownership.NewService(pool),
			dataquality.NewService(pool),
			coverage.NewService(pool, time.Now),
			ssaverify.NewService(pool, time.Now),
			peopledirectory.NewService(pool, time.Now),
			reports.NewService(pool, time.Now),
			leavetracker.NewService(pool, time.Now),
			partnerassigned.NewService(pool),
			myactions.NewService(pool, time.Now),
			coreoversight.NewService(pool, time.Now),
			myplan.NewService(pool, time.Now).WithTrainingSummary(trainingsummary.OwnSummary),
			calendarpage.NewService(pool, time.Now),
			todos.NewService(pool, time.Now),
			workplan.NewService(pool, time.Now),
			staffactivity.NewService(pool, time.Now),
			trainingsummary.NewService(pool, time.Now),
			teamperformance.NewService(pool, time.Now),
			projectmonitoring.NewService(pool, time.Now),
			planningoversight.NewService(pool, time.Now),
			oversightportfolio.NewService(pool, time.Now),
			partneroversight.NewService(pool, time.Now),
			hrregister.NewService(pool, time.Now),
			leavepolicies.NewService(pool, time.Now),
			iapages.NewService(pool, time.Now),
			ccelead.NewService(pool, time.Now),
			extrawork.NewService(pool, time.Now),
		)
	if cfg.GoSaves.ScheduleVisit || cfg.GoSaves.RescheduleVisit || cfg.GoSaves.CancelVisit || cfg.GoSaves.EditVisit ||
		cfg.GoSaves.ScheduleTrainingPair || cfg.GoSaves.GroupReschedule || cfg.GoSaves.GroupCancel ||
		cfg.GoSaves.ScheduleGroupTraining || cfg.GoSaves.ScheduleClusterMeeting {
		save := visitSave(cfg, pool, logger)
		if cfg.GoSaves.ScheduleVisit {
			screenService.WithVisitSave(save, logger)
		}
		if cfg.GoSaves.RescheduleVisit {
			screenService.WithMoveSave(save, logger)
		}
		if cfg.GoSaves.CancelVisit {
			screenService.WithCancelSave(save, logger)
		}
		if cfg.GoSaves.EditVisit {
			screenService.WithEditSave(save, logger)
		}
		if cfg.GoSaves.ScheduleTrainingPair {
			screenService.WithTrainingPairSave(save, logger)
		}
		if cfg.GoSaves.GroupReschedule {
			screenService.WithGroupMoveSave(save, logger)
		}
		if cfg.GoSaves.GroupCancel {
			screenService.WithGroupCancelSave(save, logger)
		}
		if cfg.GoSaves.ScheduleGroupTraining {
			screenService.WithGroupTrainingSave(save, logger)
		}
		if cfg.GoSaves.ScheduleClusterMeeting {
			screenService.WithClusterMeetingSave(save, logger)
		}
	}
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
	mux.Handle(screensv1connect.NewNotificationCenterServiceHandler(notificationcenter.NewHandler(notificationcenter.NewService(pool, notificationcenter.EmailConfigured(nil)), logger), options...))
	mux.Handle(messagingv1connect.NewMessagingServiceHandler(messaging.NewService(pool, time.Now, logger), options...))
	clusterStore := clusterlead.NewStore(pool)
	leadership := clusterlead.NewService(clusterStore, time.Now, clusterSchemaReady(pool), logger).
		WithOnboarder(clusterlead.NewHTTPOnboarder(cfg.ExistingAppURL), cfg.ExistingAppURL)
	mux.Handle(clustersv1connect.NewClusterLeadershipServiceHandler(leadership, options...))
	operations := clusterlead.NewOperations(leadership, clusterStore)
	mux.Handle(clustersv1connect.NewClusterMobilizationServiceHandler(operations, options...))
	mux.Handle(clustersv1connect.NewClusterActionServiceHandler(
		clusterlead.NewActions(operations, clusterStore, clusterActionConfig(cfg)), options...,
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
	mux.Handle(loansv1connect.NewLoanFollowUpServiceHandler(loans.NewFollowUpService(lending), options...))
	mux.Handle("POST /sms/delivery-report/{secret}", loanStore.DeliveryReports(cfg.Loans.SMSCallbackSecret, logger))
	return httpmw.Chain(logger, httpmw.CORS(cfg.CORSAllowedOrigins, mux))
}

// visitSave is the Go visit save (docs/migration/27 §27.10), switched on by
// EDIFY_GO_SAVES=schedule_visit only (development or staging, config.Load).
// Its pricing is asked of, and settled by, the existing application.
func visitSave(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger) *activities.Service {
	pricing := activities.NewHTTPPricing(cfg.ExistingAppURL, cfg.ClusterActions.InternalKey, nil)
	service, err := activities.NewService(pool, pricing, logger, time.Now)
	if err != nil {
		// Only a machine without the time zone database fails here: the
		// gateway refuses to start rather than run with the switch quietly off.
		panic(err)
	}
	return service
}

// signInHandler assembles sign-in: the existing accounts, the existing
// policy, and the same mail and SMS providers the portal uses.
func signInHandler(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger) *signin.Handler {
	key, err := signin.ParseFieldKey(cfg.SignIn.FieldEncryptionKey)
	if err != nil {
		// config.Load validated the format; a failure here is a broken build.
		panic(err)
	}
	policy := signin.DefaultPolicy()
	policy.MFARequiredForAll = cfg.SignIn.MFARequiredForAll
	policy.MFARequiredRoles = cfg.SignIn.MFARequiredRoles
	deps := signin.Deps{
		Store: signin.NewStore(pool), Policy: policy, JWTSecret: []byte(cfg.JWTSecret), FieldKey: key,
		AppBaseURL: cfg.SignIn.AppBaseURL, Logger: logger, Now: time.Now,
	}
	if mailer := loans.NewMailer(cfg.Loans); mailer != nil {
		deps.Mail = mailAdapter{mailer}
	}
	if provider := loans.NewSMSProvider(cfg.Loans); provider != nil {
		deps.SMS = smsAdapter{provider}
	}
	if relay := signin.NewHTTPRelay(cfg.ExistingAppURL, cfg.ClusterActions.InternalKey); relay != nil {
		deps.Relay = relay
	}
	return signin.NewHandler(signin.NewService(deps), loans.NewLimiter(time.Now), cfg.Loans.TrustProxyHeaders, logger)
}

// accountsService assembles accounts: the existing records and rules, the
// portal's mail provider, and the relay for what the existing application
// still follows up (re-pricing after a role change, releasing a removed
// organisation login).
func accountsService(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger) *accounts.Service {
	deps := accounts.Deps{
		Store: accounts.NewStore(pool), JWTSecret: []byte(cfg.JWTSecret), AppBaseURL: cfg.SignIn.AppBaseURL,
		Logger: logger, Now: time.Now,
	}
	if mailer := loans.NewMailer(cfg.Loans); mailer != nil {
		deps.Mail = mailAdapter{mailer}
	}
	if relay := accounts.NewHTTPRelay(cfg.ExistingAppURL, cfg.ClusterActions.InternalKey); relay != nil {
		deps.Relay = relay
	}
	return accounts.NewService(deps)
}

type mailAdapter struct{ mailer loans.Mailer }

func (m mailAdapter) SendMail(ctx context.Context, to, subject, text string) error {
	_, err := m.mailer.Send(ctx, loans.Message{To: to, Subject: subject, Text: text})
	return err
}

type smsAdapter struct{ provider loans.SMSProvider }

func (s smsAdapter) SendText(ctx context.Context, to, text string) error {
	_, err := s.provider.Send(ctx, to, text)
	return err
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

// clusterActionConfig is the Cluster Action Register's follow-up policy.
func clusterActionConfig(cfg config.Config) clusterlead.ActionConfig {
	return clusterlead.ActionConfig{
		RemindAfterDays:   cfg.ClusterActions.RemindAfterDays,
		EscalateAfterDays: cfg.ClusterActions.EscalateAfterDays,
	}
}

// ClusterActionFollowUp is the register's follow-up worker, for main to run.
func ClusterActionFollowUp(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger) (*clusterlead.ActionService, clusterlead.NoticeSender, func(context.Context) error) {
	store := clusterlead.NewStore(pool)
	lead := clusterlead.NewService(store, time.Now, nil, logger)
	actions := clusterlead.NewActions(clusterlead.NewOperations(lead, store), store, clusterActionConfig(cfg))
	return actions, clusterlead.NewHTTPNoticeSender(cfg.ExistingAppURL, cfg.ClusterActions.InternalKey), clusterSchemaReady(pool)
}
