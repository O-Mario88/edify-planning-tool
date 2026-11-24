// Package server assembles the gateway's HTTP handler from its parts, so the
// process entry point and the integration tests serve exactly the same thing.
package server

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	"connectrpc.com/connect"
	"connectrpc.com/grpchealth"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1/clustersv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1/countriesv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1/loansv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/messaging/v1/messagingv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1/routesv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1/schoolsv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accounts"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/acting"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminpanel"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminusers"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/approvalhistory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/batchpayments"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btpages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cache"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/catalogue"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ccelead"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closurepages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closurequality"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clustercreate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterfacilitation"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clustermembership"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusteroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreoversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costsettings"
	countryschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/countryconfig"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coverage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cpdlearning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dashboard"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dataquality"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/debriefs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/detailpages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/disbursements"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/escalations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/evidence"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/exports"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/extrawork"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feed"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fieldops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fieldpages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/financedesks"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/financeops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundapprovals"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fyplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/health"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/helpcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/helpcontext"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/home"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrtoday"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/httpmw"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iaframework"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/leaveapprovals"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/leavepolicies"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/leavetracker"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
	loanschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/messaging"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mscs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myactions"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mypd"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myperformance"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mytargets"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myteam"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/navigation"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/oversightportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownedschema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownership"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerpayments"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerusers"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerworkspace"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/peopledirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/perfconversation"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/perfcycle"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/personaltimeoff"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningoversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/platformhealth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/policycompliance"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/presence"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/prioritiesmaster"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/privatestore"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/profilepage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/programmerollout"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/programmeschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectmonitoring"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectmyplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectspage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/qualityflags"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/recentchanges"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/reports"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rolesmatrix"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/routeplan"
	routeschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/routeplan/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolevidence"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/screens"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/settingspage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/signin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ssadecision"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ssaverify"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/staffactivity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/stafflogs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/staffsetup"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/support"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targetdistribution"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teamperformance"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teams"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todaypage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/uploadcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/uploads"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitrequests"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/weeklyrequest"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workforceops"
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
	weeklyPage := weeklyrequest.NewService(pool, time.Now)
	debriefPage := debriefs.NewService(pool, time.Now)
	extraWorkPage := extrawork.NewService(pool, time.Now)
	// Files people upload as evidence, kept where the existing application
	// keeps them (local disk in development, private Spaces in production).
	evidenceSvc := evidence.NewService(pool, privatestore.FromEnv(os.Getenv, privateUploadsDir(os.Getenv)),
		evidence.ScannerFromEnv(os.Getenv), time.Now, logger)
	var existingApp screens.Fetcher
	if cfg.ExistingAppURL != "" {
		existingApp = feed.NewClient(cfg.ExistingAppURL, logger)
	}
	clusterOversightSvc := clusteroversight.NewService(pool, time.Now)
	countryMapSvc := oversightportfolio.NewCountryMap(oversightportfolio.NewService(pool, time.Now))
	detailPagesSvc := detailpages.NewService(pool, time.Now)
	screenService := screens.NewService(existingApp).TrustProxyHeaders(cfg.Loans.TrustProxyHeaders).
		WithStrictReads(cfg.StrictReads).
		WithDirectory(schooldirectory.NewService(pool, time.Now), logger).
		WithProfile(schoolprofile.NewService(pool, time.Now), logger).
		WithHome(home.NewService(pool, time.Now), logger).
		WithNavigation(navigation.NewService(pool)).
		WithPages(logger,
			clusterpage.NewService(pool, time.Now),
			closedschools.NewService(pool, time.Now),
			programmeschools.NewService(pool, time.Now),
			clusterOversightSvc,
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
			perfconversation.NewService(pool, time.Now),
			catalogue.NewService(pool, time.Now),
			schoolevidence.NewService(pool, time.Now),
			helpcenter.NewService(pool, time.Now),
			todaypage.NewService(pool, time.Now),
			closurequality.NewService(pool, time.Now),
			iaframework.NewService(pool),
			ownership.NewService(pool),
			dataquality.NewService(pool),
			coverage.NewService(pool, time.Now),
			ssaverify.NewService(pool, time.Now),
			peopledirectory.NewService(pool, time.Now),
			reports.NewService(pool, time.Now),
			leavetracker.NewService(pool, time.Now),
			leaveapprovals.NewService(pool, time.Now),
			hrtoday.NewService(pool, time.Now),
			btpages.NewService(pool, time.Now),
			partnerassigned.NewService(pool),
			partnerworkspace.NewService(pool, time.Now),
			myteam.NewService(pool, time.Now),
			myperformance.NewService(pool, time.Now),
			costsettings.NewService(pool, time.Now),
			budgetpage.NewService(pool, time.Now),
			platformhealth.NewService(pool, platformhealth.Facts{
				Env: string(cfg.Env), Release: cfg.Release, Started: time.Now(), GoSaves: cfg.GoSaves.Names(),
				ExistingApp: cfg.ExistingAppURL != "", RoutingProvider: cfg.Routing.Provider, OSRMURL: cfg.Routing.OSRMURL,
				AnalyticsAddr: cfg.AnalyticsAddr, MailConfigured: cfg.Loans.SMTPAddr != "", DevMailbx: cfg.Loans.DevMailboxDir != "",
			}, platformhealth.Probe{Pool: poolStat(pool), Reach: reach}, map[string]ownedschema.Spec{
				schema.Name: schema.Spec, loanschema.Name: loanschema.Spec, routeschema.Name: routeschema.Spec,
				countryschema.Name: countryschema.Spec,
			}, time.Now),
			myactions.NewService(pool, time.Now),
			coreoversight.NewService(pool, time.Now),
			myplan.NewService(pool, time.Now).
				WithTrainingSummary(trainingsummary.OwnSummary).
				WithReadiness(planningmonitor.OwnReadiness),
			calendarpage.NewService(pool, time.Now),
			todos.NewService(pool, time.Now),
			workplan.NewService(pool, time.Now),
			staffactivity.NewService(pool, time.Now),
			trainingsummary.NewService(pool, time.Now),
			teamperformance.NewService(pool, time.Now),
			projectmonitoring.NewService(pool, time.Now),
			projectspage.NewService(pool, time.Now),
			disbursements.NewService(pool, time.Now),
			fundapprovals.NewService(pool, time.Now),
			uploadcenter.NewService(pool, time.Now),
			debriefPage,
			cpdlearning.NewService(pool, time.Now),
			approvalhistory.NewService(pool),
			batchpayments.NewService(pool, time.Now),
			partnerpayments.NewService(pool),
			projectmyplan.NewService(pool, time.Now),
			projectplanning.NewService(pool, time.Now),
			mypd.NewService(pool, time.Now, cfg.PageWrites.MyProfessionalDevelopment),
			planningoversight.NewService(pool, time.Now),
			oversightportfolio.NewService(pool, time.Now),
			countryMapSvc,
			weeklyPage,
			adminusers.NewService(pool),
			personaltimeoff.NewService(pool, time.Now),
			dashboard.NewService(pool, time.Now),
			mytargets.NewService(pool, time.Now),
			targetdistribution.NewService(pool, time.Now),
			prioritiesmaster.NewService(pool, time.Now),
			coreschools.NewService(pool, time.Now),
			acting.NewPage(pool, time.Now),
			planningmonitor.NewPage(pool, time.Now),
			programmerollout.NewService(pool, time.Now),
			partneroversight.NewService(pool, time.Now).WithTarget(planningmonitor.PartnerTargetReader(pool)),
			schoolprofile.NewScopePages(pool, time.Now).WithClusterCards(clusterCards{clusteroversight.CardReader{DB: pool}}).
				WithClusterWorkspace(clusterpage.NewService(pool, time.Now)),
			hrregister.NewService(pool, time.Now).WithAccessLog(pool, logger),
			leavepolicies.NewService(pool, time.Now),
			visitrequests.NewService(pool, time.Now),
			stafflogs.NewService(pool, time.Now),
			closurepages.NewService(pool, time.Now),
			iapages.NewService(pool, time.Now),
			ccelead.NewService(pool, time.Now),
			extraWorkPage,
			financedesks.NewService(pool, time.Now),
			fieldpages.NewService(pool, time.Now),
			adminpanel.NewService(pool, time.Now),
			profilepage.NewService(pool),
			helpcontext.NewService(pool),
			detailPagesSvc,
		)
	realtimeBroker := realtime.NewBroker(time.Now)
	if cfg.RedisURL != "" {
		if err := realtimeBroker.WithRedisPubSub(context.Background(), cfg.RedisURL, logger); err != nil {
			logger.Warn("realtime: invalid redis pubsub configuration, staying single-node", slog.String("error", err.Error()))
		}
	}
	effectiveSaves := cfg.GoSaves
	// In pure-Go Django-absent mode (EDIFY_EXISTING_APP_URL == ""), every native
	// Go writer is wired automatically so zero save paths depend on Django.
	if cfg.ExistingAppURL == "" {
		effectiveSaves = config.AllGoSaves()
		screenService.WithPresence(presence.NewStamper(pool), logger)
	}
	if effectiveSaves.ScheduleVisit || effectiveSaves.RescheduleVisit || effectiveSaves.CancelVisit || effectiveSaves.EditVisit ||
		effectiveSaves.ScheduleTrainingPair || effectiveSaves.GroupReschedule || effectiveSaves.GroupCancel ||
		effectiveSaves.ScheduleGroupTraining || effectiveSaves.ScheduleClusterMeeting || effectiveSaves.CompleteVisit {
		save := visitSave(cfg, pool, logger, realtimeBroker)
		if effectiveSaves.ScheduleVisit {
			screenService.WithVisitSave(save, logger).WithCoreVisitSave(save, logger).WithClientAssign(save).WithBulkSchedule(save).WithBulkAssign(save).WithVisitDecisions(save).
				WithActivityLifecycle(save).WithWeekOwner(save).WithAccountability(save.WithEvidence(evidenceSvc)).WithReimbursement(save)
			weeklyPage.WithOwnerButtons(existingApp == nil)
			if existingApp == nil {
				debriefPage.WithSaves(pool, plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy, realtimeBroker, logger)
				screenService.WithDailyDebrief(debriefPage)
				extraWorkPage.WithSaves(pool, plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy, realtimeBroker, logger)
				screenService.WithExtraWork(extraWorkPage)
				screenService.WithClusterFacilitation(clusterfacilitation.New(pool, plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy,
					realtimeBroker, logger, time.Now))
				membership := clustermembership.New(pool, clusterpage.NewService(pool, time.Now),
					plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy, realtimeBroker, logger, time.Now)
				creator := clustercreate.New(pool, membership, logger, time.Now)
				membership.WithClusterMaker(creator)
				screenService.WithClusterMembership(membership)
				screenService.WithClusterCreate(creator)
				enroller := projectcapacity.NewService(pool, time.Now).
					WithSaves(pool, plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy, realtimeBroker, logger)
				screenService.WithEnroller(enroller)
				screenService.WithBulkEnroller(enroller)
				screenService.WithRecentChanges(recentchanges.New(pool, time.Now))
				screenService.WithStories(mscs.New(pool, time.Now))
			}
		}
		if effectiveSaves.RescheduleVisit {
			screenService.WithMoveSave(save, logger)
		}
		if effectiveSaves.CancelVisit {
			screenService.WithCancelSave(save, logger)
		}
		if effectiveSaves.EditVisit {
			screenService.WithEditSave(save, logger)
		}
		if effectiveSaves.ScheduleTrainingPair {
			screenService.WithTrainingPairSave(save, logger)
		}
		if effectiveSaves.GroupReschedule {
			screenService.WithGroupMoveSave(save, logger)
		}
		if effectiveSaves.GroupCancel {
			screenService.WithGroupCancelSave(save, logger)
		}
		if effectiveSaves.ScheduleGroupTraining {
			screenService.WithGroupTrainingSave(save, logger)
		}
		if effectiveSaves.ScheduleClusterMeeting {
			screenService.WithClusterMeetingSave(save, logger)
		}
		if effectiveSaves.CompleteVisit {
			screenService.WithCompleteSave(save, logger)
		}
	}
	exportsMgr := exports.NewManager(pool, time.Now)
	if effectiveSaves.PLReview {
		screenService.WithPLReviewSave(plreview.NewReviewService(pool, time.Now).
			WithRealtime(realtimeBroker).WithSalesforceSync(cfg.SalesforceSync).
			WithPush(plreview.PushReadinessFrom(os.Getenv, os.ReadFile)).WithLogger(logger), logger)
	}
	uploadsSvc := uploads.NewService(pool, time.Now).WithRealtime(realtimeBroker)
	fieldOpsSvc := fieldops.NewService(pool).WithRealtime(realtimeBroker)
	financeOpsSvc := financeops.NewService(pool).WithRealtime(realtimeBroker)
	workforceOpsSvc := workforceops.NewService(pool).WithRealtime(realtimeBroker)
	screenService.WithExports(exportsMgr).
		WithOpsSaves(fieldOpsSvc, financeOpsSvc, workforceOpsSvc)
	if effectiveSaves.SchoolActions {
		screenService.WithSchoolDB(pool, time.Now)
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
	exportsMgr.RegisterHTTP(mux, authenticator)
	uploadsSvc.RegisterHTTP(mux, authenticator)
	evidenceSvc.RegisterHTTP(mux, authenticator)
	ssadecision.NewService(pool, time.Now).RegisterHTTP(mux, authenticator)
	clusterOversightSvc.RegisterHTTP(mux, authenticator)
	countryMapSvc.RegisterMapHTTP(mux, authenticator)
	detailPagesSvc.RegisterHTTP(mux, authenticator)
	realtimeBroker.RegisterHTTP(mux, authenticator)
	// The operational writers' direct endpoints exist only with the existing
	// application absent: beside it they would be a second writer of the same
	// records, past its rules.
	if cfg.ExistingAppURL == "" {
		fieldOpsSvc.RegisterHTTP(mux, authenticator)
		financeOpsSvc.RegisterHTTP(mux, authenticator)
		workforceOpsSvc.RegisterHTTP(mux, authenticator)
	}
	mux.Handle(screensv1connect.NewNotificationCenterServiceHandler(notificationcenter.NewHandler(notificationcenter.NewService(pool, notificationcenter.EmailConfigured(nil)), logger), options...))
	notificationcenter.RegisterPreferencesHTTP(mux, authenticator, pool, time.Now)
	support.NewService(pool, notificationcenter.NewWriter(pool, time.Now), time.Now).Register(mux, authenticator)
	messaging.NewNativeStore(pool, notificationcenter.NewWriter(pool, time.Now), time.Now).RegisterHTTP(mux, authenticator)
	activities.NewBulkHTTPHandler(visitSave(cfg, pool, logger, realtimeBroker)).Register(mux, authenticator)
	// Settings (/settings): the reader's own account, read through the
	// sign-in grant, with the same two-step policy sign-in applies.
	settingsFieldKey, _ := signin.ParseFieldKey(cfg.SignIn.FieldEncryptionKey)
	settingsSvc := settingspage.NewService(pool,
		settingspage.Policy{RequiredForAll: cfg.SignIn.MFARequiredForAll, RequiredRoles: cfg.SignIn.MFARequiredRoles}, nil)
	mux.Handle(screensv1connect.NewSettingsScreenServiceHandler(settingspage.NewHandler(settingsSvc, logger), options...))
	settingspage.RegisterHTTP(mux, authenticator, pool, settingsSvc, settingsFieldKey, time.Now)
	// Edify Global's countries and their versioned settings
	// (docs/migration/80 §8), from the Go-owned country_registry.
	mux.Handle(countriesv1connect.NewCountryServiceHandler(countryconfig.NewService(pool,
		func(ctx context.Context) error { return countryschema.Spec.Ready(ctx, pool) }, logger), options...))
	routePlanSvc := routeplan.NewService(pool,
		routeplan.RouterFor(cfg.Routing.Provider, cfg.Routing.OSRMURL, cfg.Routing.GoogleKey, cfg.Routing.DailyLimit, time.Now),
		time.Now, logger).WithVerification(pool, routesSchemaReady(pool)).WithLocationInvalidator(countryMapSvc.InvalidateMapCache)
	mux.Handle(routesv1connect.NewRoutePlannerServiceHandler(routePlanSvc, options...))
	routePlanSvc.RegisterHTTP(mux, authenticator, realtimeBroker)
	mux.Handle(messagingv1connect.NewMessagingServiceHandler(messaging.NewService(pool, time.Now, logger), options...))
	mailer := loans.NewMailer(cfg.Loans)
	clusterStore := clusterlead.NewStore(pool)
	onboardBaseURL := cfg.ExistingAppURL
	if onboardBaseURL == "" {
		onboardBaseURL = cfg.SignIn.AppBaseURL
	}
	var onboarder clusterlead.Onboarder = clusterlead.NewHTTPOnboarder(cfg.ExistingAppURL)
	if cfg.ExistingAppURL == "" {
		directOnboard := clusterlead.NewDirectOnboarder(pool)
		if mailer != nil {
			directOnboard = directOnboard.WithMailer(mailAdapter{mailer}, onboardBaseURL)
		}
		onboarder = directOnboard
	}
	leadership := clusterlead.NewService(clusterStore, time.Now, clusterSchemaReady(pool), logger).
		WithOnboarder(onboarder, onboardBaseURL)
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
	public.RegisterLender(mux, mailer)
	mux.Handle(loansv1connect.NewLoanReferralServiceHandler(
		loans.NewService(loanStore, cfg.Loans, mailer, LoansSchemaReady(pool), logger, time.Now), options...,
	))
	// Loan origination and servicing: native Go ledger when Django is absent,
	// or HTTP ledger relay when co-deployed with Django.
	var loanLedger loans.Ledger = loans.NewLedgerClient(cfg.ExistingAppURL)
	if cfg.ExistingAppURL == "" {
		loanLedger = loans.NewNativeLedger(pool)
	}
	lending := loans.NewLending(loanStore, loanLedger, loanKeys, cfg.Loans, mailer,
		loans.NewSMSProvider(cfg.Loans), LoansSchemaReady(pool), logger, time.Now)
	public.RegisterSchool(mux, lending)
	public.RegisterShare(mux)
	mux.Handle(loansv1connect.NewLoanShareServiceHandler(loans.NewShareService(loanStore,
		loanLedger, cfg.Loans.PublicBaseURL, LoansSchemaReady(pool), logger, time.Now), options...))
	mux.Handle(loansv1connect.NewLendingServiceHandler(loans.NewLendingService(lending), options...))
	mux.Handle(loansv1connect.NewLoanFollowUpServiceHandler(loans.NewFollowUpService(lending), options...))
	mux.Handle("POST /sms/delivery-report/{secret}", loanStore.DeliveryReports(cfg.Loans.SMSCallbackSecret, logger))
	return httpmw.Chain(logger, httpmw.CORS(cfg.CORSAllowedOrigins, mux))
}

// visitSave is the Go visit save (docs/migration/27 §27.10), switched on by
// EDIFY_GO_SAVES in development or staging. Uses native Go pricing and
// notifications when Django is absent.
// privateUploadsDir is where development keeps private files: the existing
// application's BASE_DIR/uploads, named by EDIFY_PRIVATE_UPLOADS_DIR.
func privateUploadsDir(getenv func(string) string) string {
	if dir := getenv("EDIFY_PRIVATE_UPLOADS_DIR"); dir != "" {
		return dir
	}
	return "uploads"
}

func visitSave(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger, live activities.NoticePublisher) *activities.Service {
	var pricing activities.Pricing
	if cfg.ExistingAppURL == "" {
		pricing = activities.NewNativePricing(pool, notificationcenter.NewWriter(pool, time.Now)).
			WithNotices(plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy, live)
	} else {
		pricing = activities.NewHTTPPricing(cfg.ExistingAppURL, cfg.ClusterActions.InternalKey, nil)
	}
	service, err := activities.NewService(pool, pricing, logger, time.Now)
	if err != nil {
		// Only a machine without the time zone database fails here: the
		// gateway refuses to start rather than run with the switch quietly off.
		panic(err)
	}
	forms := coreforms.NewService(pool, time.Now)
	return service.WithOwnerNotices(plreview.PushReadinessFrom(os.Getenv, os.ReadFile).QueueCopy, live).
		WithVisitRequests(forms).WithGovernedSupport(forms)
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
	} else if direct := signin.NewDirectRelay(pool, notificationcenter.NewWriter(pool, time.Now)); direct != nil {
		deps.Relay = direct.WithEnv(string(cfg.Env))
	}
	limiter, err := cache.NewFromURL(cfg.RedisURL, logger)
	if err != nil {
		logger.Warn("cache: invalid redis configuration, falling back to memory", slog.String("error", err.Error()))
		limiter = cache.NewMemory(time.Now)
	}
	return signin.NewHandler(signin.NewService(deps), limiter, cfg.Loans.TrustProxyHeaders, logger)
}

// accountsService assembles accounts: the existing records and rules, the
// portal's mail provider, and either the Django HTTP relay or direct native Go
// notifications and day-pool repricing when Django is absent.
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
	} else if direct := accounts.NewDirectRelay(pool, notificationcenter.NewWriter(pool, time.Now)); direct != nil {
		deps.Relay = direct.WithCostSettler(activities.NewNativePricing(pool, notificationcenter.NewWriter(pool, time.Now)))
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
// routesSchemaReady checks field_routes (Verify Location) is at this
// build's version; the gateway never migrates it.
func routesSchemaReady(pool *pgxpool.Pool) func(context.Context) error {
	return func(ctx context.Context) error { return routeschema.Spec.Ready(ctx, pool) }
}

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
// When EDIFY_EXISTING_APP_URL is unset (Django absent), notices are delivered
// directly to PostgreSQL through gateway_notifications.deliver (M11).
func ClusterActionFollowUp(cfg config.Config, pool *pgxpool.Pool, logger *slog.Logger) (*clusterlead.ActionService, clusterlead.NoticeSender, func(context.Context) error) {
	store := clusterlead.NewStore(pool)
	lead := clusterlead.NewService(store, time.Now, nil, logger)
	actions := clusterlead.NewActions(clusterlead.NewOperations(lead, store), store, clusterActionConfig(cfg))
	var sender clusterlead.NoticeSender = clusterlead.NewHTTPNoticeSender(cfg.ExistingAppURL, cfg.ClusterActions.InternalKey)
	if sender == nil && cfg.ExistingAppURL == "" {
		sender = clusterlead.NewDirectNoticeSender(pool)
	}
	return actions, sender, clusterSchemaReady(pool)
}

// poolStat is the pool's figures for Platform Health.
func poolStat(pool *pgxpool.Pool) func() platformhealth.PoolStat {
	return func() platformhealth.PoolStat {
		st := pool.Stat()
		return platformhealth.PoolStat{Total: st.TotalConns(), Acquired: st.AcquiredConns(), Idle: st.IdleConns(), Max: st.MaxConns()}
	}
}

// reach is whether an address answers within two seconds: any HTTP answer
// for an http(s) URL, an open connection for tcp://host:port.
func reach(ctx context.Context, rawURL string) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	if address, ok := strings.CutPrefix(rawURL, "tcp://"); ok {
		conn, err := (&net.Dialer{}).DialContext(ctx, "tcp", address)
		if err != nil {
			return err
		}
		return conn.Close()
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return err
	}
	return response.Body.Close()
}

// clusterCards lends the profiles of many schools Cluster Oversight's
// cluster cards (schoolprofile cannot import clusteroversight).
type clusterCards struct{ clusteroversight.CardReader }

func (c clusterCards) Cards(ctx context.Context, ids []string, fy, today string) (map[string]schoolprofile.ClusterCard, error) {
	cards, err := c.CardReader.Cards(ctx, ids, fy, today)
	if err != nil {
		return nil, err
	}
	out := make(map[string]schoolprofile.ClusterCard, len(cards))
	for id, card := range cards {
		out[id] = schoolprofile.ClusterCard(card)
	}
	return out, nil
}
