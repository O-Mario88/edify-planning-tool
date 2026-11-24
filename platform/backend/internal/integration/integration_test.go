//go:build integration

// Package integration runs the whole gateway against a real PostgreSQL
// database carrying the existing Edify schema (built by the existing
// application's own migrations and demo seed).
//
// It needs EDIFY_TEST_ADMIN_DATABASE_URL, which must point at this machine
// and at a database whose name ends in "_test". Anything else is refused, so
// these tests cannot be aimed at a shared or production database.
//
//	go test -tags integration ./internal/integration/
package integration

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	schoolsv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/schools/v1/schoolsv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	countryschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/countryctx"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dbguard"
	loanschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/schema"
	routeschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/routeplan/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"

	"github.com/jackc/pgx/v5"
)

const (
	adminURLEnv   = "EDIFY_TEST_ADMIN_DATABASE_URL"
	testDBSuffix  = "_test"
	gatewayRole   = "edify_gateway"
	signingSecret = "integration-test-signing-secret-0123456789"
	rolesFile     = "../../../deploy/db/roles.sql"
	// The Cluster Leader Portal's schema and roles (Go-owned).
	clusterRolesFile = "../../../deploy/db/cluster_roles.sql"
	// The School Loan Application Portal's schema and roles (Go-owned).
	loanRolesFile = "../../../deploy/db/loan_roles.sql"
	// The Smart Route Planner's schema and roles (Go-owned).
	routesRolesFile = "../../../deploy/db/routes_roles.sql"
	// Edify Global's country registry.
	countryRolesFile = "../../../deploy/db/country_roles.sql"
	// Signing in, which Go owns: exactly the existing sign-in's columns.
	identityRolesFile = "../../../deploy/db/identity_roles.sql"
	// The Decision Log's narrow view of the audit chain.
	decisionLogRolesFile = "../../../deploy/db/decision_log_roles.sql"
	// Which forms an activity has in; after the file above.
	evidenceRolesFile = "../../../deploy/db/evidence_roles.sql"
	// Scheduling a school visit, the first save Go makes: exactly its writes.
	activitiesRolesFile = "../../../deploy/db/activities_roles.sql"
	// Cancelling a visit: the narrow function that withdraws its unmoved advances.
	advanceWithdrawRolesFile = "../../../deploy/db/advance_withdraw_roles.sql"
	// Completing a staff school visit: the narrow function that hands it in.
	completionRolesFile = "../../../deploy/db/completion_roles.sql"
	// Programme Lead approval and return: two narrow functions (M9).
	plReviewRolesFile = "../../../deploy/db/pl_review_roles.sql"
	// Native Go notification delivery and read-state transitions (M11).
	notificationRolesFile = "../../../deploy/db/notification_roles.sql"
	// Native Go day-pool costing settlement (Step 1).
	costingSettleRolesFile = "../../../deploy/db/costing_settle_roles.sql"
	// What follows a priced day: transport, advances, weekly and monthly requests.
	dayMoneyRolesFile = "../../../deploy/db/day_money_roles.sql"
	// Activity evidence uploaded through Go: the staged file and its record.
	evidenceUploadRolesFile = "../../../deploy/db/evidence_upload_roles.sql"
	// The Daily Debrief saved through Go.
	debriefsRolesFile = "../../../deploy/db/debriefs_roles.sql"
	// Extra Assigned Work saved through Go.
	extraworkRolesFile = "../../../deploy/db/extrawork_roles.sql"
	// Add to Project saved through Go.
	projectEnrolRolesFile = "../../../deploy/db/project_enrol_roles.sql"
	// SSA scores keyed on a visit through Go.
	ssaEntryRolesFile = "../../../deploy/db/ssa_entry_roles.sql"
	// The cluster facilitator saved through Go.
	clusterFacilitationRolesFile = "../../../deploy/db/cluster_facilitation_roles.sql"
	// Who facilitates a planned training or meeting, saved through Go.
	activityFacilitatorRolesFile = "../../../deploy/db/activity_facilitator_roles.sql"
	// A school joining a cluster, saved through Go.
	clusterMembershipRolesFile = "../../../deploy/db/cluster_membership_roles.sql"
	// A cluster created through Go.
	clusterCreateRolesFile = "../../../deploy/db/cluster_create_roles.sql"
	// A Most Significant Change Story submitted through Go.
	mscsRolesFile = "../../../deploy/db/mscs_roles.sql"
	// Native Go security/account relay side effects (Step 2).
	relayOpsRolesFile = "../../../deploy/db/relay_ops_roles.sql"
	// Native Go cluster leader account onboarding (Batch 10).
	clusterOnboardRolesFile = "../../../deploy/db/cluster_onboard_roles.sql"
	// Native Go loan ledger writer (Batch 10).
	loansLedgerRolesFile = "../../../deploy/db/loans_ledger_roles.sql"
	// Native Go field ops writers: evidence, IA verification, SSA, partners (Batch 11).
	fieldOpsRolesFile = "../../../deploy/db/field_ops_roles.sql"
	// Native Go finance & money writers (Batch 12).
	financeRolesFile = "../../../deploy/db/finance_roles.sql"
	// Native Go workforce ops writers (Batch 13).
	workforceOpsRolesFile = "../../../deploy/db/workforce_ops_roles.sql"
	// Native Go support ticket workflow (Step 3A).
	supportRolesFile = "../../../deploy/db/support_roles.sql"
	// Native Go messaging read-thread, reply, compose, star, archive (Step 3C).
	messagingRolesFile = "../../../deploy/db/messaging_roles.sql"
	// Native Go standalone scheduler operational jobs (Step 4).
	schedulerJobsRolesFile = "../../../deploy/db/scheduler_jobs_roles.sql"
	// Native Go Settings two-step verification update (Batch 19).
	settingsRolesFile = "../../../deploy/db/settings_roles.sql"
	// Native Go School Actions & School Profile Drawer writers (Batches 22-23).
	schoolActionsRolesFile = "../../../deploy/db/school_actions_roles.sql"
	// Snoozing a To-Do from Today: one table's insert and three updated columns.
	todoRolesFile = "../../../deploy/db/todo_roles.sql"
	// Undoing a snooze: the narrow function that removes that one row.
	todoUnsnoozeRolesFile = "../../../deploy/db/todo_unsnooze_roles.sql"
	// The presence stamp for requests Go answers: one narrow function.
	presenceRolesFile = "../../../deploy/db/presence_roles.sql"
	// My Professional Development's read writes (owner, 2026-11-16).
	mypdRolesFile = "../../../deploy/db/mypd_roles.sql"
	// Where the loan portal's emails go in this run.
	publicBaseURL = "http://127.0.0.1:9"
)

var (
	admin   *pgxpool.Pool // owner connection: reads expectations, flips fixtures
	gateway *pgxpool.Pool // the read-only role the gateway really uses
	baseURL string
	mailbox string // the loan portal's development mailbox for this run
	smsbox  string // and its development text messages
)

func TestMain(m *testing.M) {
	os.Exit(run(m))
}

func run(m *testing.M) int {
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()

	adminURL := os.Getenv(adminURLEnv)
	adminConfig, err := pgxpool.ParseConfig(adminURL)
	if adminURL == "" || err != nil {
		fmt.Fprintf(os.Stderr, "integration: %s is required and must be a valid URL\n", adminURLEnv)
		return 1
	}
	if err := requireLocalTestDatabase(adminConfig.ConnConfig.Host, adminConfig.ConnConfig.Database); err != nil {
		fmt.Fprintln(os.Stderr, "integration: refused:", err)
		return 1
	}

	admin, err = pgxpool.NewWithConfig(ctx, adminConfig)
	if err != nil {
		fmt.Fprintln(os.Stderr, "integration: connecting as admin:", err)
		return 1
	}
	defer admin.Close()

	password, err := prepareGatewayRole(ctx)
	if err != nil {
		fmt.Fprintln(os.Stderr, "integration: preparing the gateway role:", err)
		return 1
	}

	gatewayConfig := adminConfig.Copy()
	gatewayConfig.ConnConfig.User = gatewayRole
	gatewayConfig.ConnConfig.Password = password
	gatewayConfig.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	// As cmd/gateway: each connection carries its request's country.
	countryctx.Configure(gatewayConfig)
	gateway, err = pgxpool.NewWithConfig(ctx, gatewayConfig)
	if err != nil {
		fmt.Fprintln(os.Stderr, "integration: connecting as the gateway role:", err)
		return 1
	}
	defer gateway.Close()
	if err := gateway.Ping(ctx); err != nil {
		fmt.Fprintln(os.Stderr, "integration: the gateway role cannot connect:", err)
		return 1
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	mailbox, err = os.MkdirTemp("", "edify-loans-mail-")
	if err != nil {
		fmt.Fprintln(os.Stderr, "integration: making the mailbox:", err)
		return 1
	}
	defer func() { _ = os.RemoveAll(mailbox) }()
	smsbox, err = os.MkdirTemp("", "edify-loans-sms-")
	if err != nil {
		fmt.Fprintln(os.Stderr, "integration: making the SMS box:", err)
		return 1
	}
	defer func() { _ = os.RemoveAll(smsbox) }()
	cfg := config.Config{Env: config.Test, Release: "integration", JWTSecret: signingSecret,
		Loans: config.Loans{PublicBaseURL: publicBaseURL, DevMailboxDir: mailbox, MailFrom: "loans@edify.test",
			SMSProvider: "dev_file", SMSDevDir: smsbox,
			// Each test is its own client (testClient), so rate limits apply
			// per test rather than across the run.
			TrustProxyHeaders: true},
		SignIn: config.SignIn{AppBaseURL: publicBaseURL}}
	httpServer := httptest.NewServer(server.New(cfg, gateway, nil, logger))
	defer httpServer.Close()
	baseURL = httpServer.URL

	return m.Run()
}

func requireLocalTestDatabase(host, database string) error {
	local := host == "" || host == "localhost" || strings.HasPrefix(host, "/")
	if ip := net.ParseIP(host); ip != nil && ip.IsLoopback() {
		local = true
	}
	if !local {
		return fmt.Errorf("host %q is not this machine", host)
	}
	if !strings.HasSuffix(database, testDBSuffix) {
		return fmt.Errorf("database %q does not end in %q", database, testDBSuffix)
	}
	return nil
}

// prepareGatewayRole applies deploy/db/roles.sql (roles and grants only) and
// gives the login role a throwaway password for this run.
func prepareGatewayRole(ctx context.Context) (string, error) {
	roles, err := os.ReadFile(filepath.FromSlash(rolesFile))
	if err != nil {
		return "", err
	}
	conn, err := admin.Acquire(ctx)
	if err != nil {
		return "", err
	}
	defer conn.Release()
	if _, err := conn.Conn().PgConn().Exec(ctx, string(roles)).ReadAll(); err != nil {
		return "", err
	}
	// The Cluster Leader Portal's Go-owned schema: its roles, then its
	// migrations, exactly as clusterctl migrate applies them.
	clusterRoles, err := os.ReadFile(filepath.FromSlash(clusterRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(clusterRoles)).ReadAll(); err != nil {
		return "", err
	}
	if _, err := schema.Apply(ctx, conn.Conn(), conn.Conn().Config().Database); err != nil {
		return "", err
	}
	loanRoles, err := os.ReadFile(filepath.FromSlash(loanRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(loanRoles)).ReadAll(); err != nil {
		return "", err
	}
	if _, err := loanschema.Spec.Apply(ctx, conn.Conn(), conn.Conn().Config().Database); err != nil {
		return "", err
	}
	routesRoles, err := os.ReadFile(filepath.FromSlash(routesRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(routesRoles)).ReadAll(); err != nil {
		return "", err
	}
	if _, err := routeschema.Spec.Apply(ctx, conn.Conn(), conn.Conn().Config().Database); err != nil {
		return "", err
	}
	// Edify Global's country registry: its roles, its migrations, then the
	// legacy seed (every existing school and account in Uganda), exactly as
	// schemactl migrate and countryctl seed-legacy apply them.
	countryRoles, err := os.ReadFile(filepath.FromSlash(countryRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(countryRoles)).ReadAll(); err != nil {
		return "", err
	}
	if _, err := countryschema.Spec.Apply(ctx, conn.Conn(), conn.Conn().Config().Database); err != nil {
		return "", err
	}
	if err := seedCountries(ctx, conn.Conn()); err != nil {
		return "", err
	}
	identityRoles, err := os.ReadFile(filepath.FromSlash(identityRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(identityRoles)).ReadAll(); err != nil {
		return "", err
	}
	decisionLogRoles, err := os.ReadFile(filepath.FromSlash(decisionLogRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(decisionLogRoles)).ReadAll(); err != nil {
		return "", err
	}
	evidenceRoles, err := os.ReadFile(filepath.FromSlash(evidenceRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(evidenceRoles)).ReadAll(); err != nil {
		return "", err
	}
	activitiesRoles, err := os.ReadFile(filepath.FromSlash(activitiesRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(activitiesRoles)).ReadAll(); err != nil {
		return "", err
	}
	advanceWithdrawRoles, err := os.ReadFile(filepath.FromSlash(advanceWithdrawRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(advanceWithdrawRoles)).ReadAll(); err != nil {
		return "", err
	}
	completionRoles, err := os.ReadFile(filepath.FromSlash(completionRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(completionRoles)).ReadAll(); err != nil {
		return "", err
	}
	plReviewRoles, err := os.ReadFile(filepath.FromSlash(plReviewRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(plReviewRoles)).ReadAll(); err != nil {
		return "", err
	}
	notificationRoles, err := os.ReadFile(filepath.FromSlash(notificationRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(notificationRoles)).ReadAll(); err != nil {
		return "", err
	}
	costingSettleRoles, err := os.ReadFile(filepath.FromSlash(costingSettleRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(costingSettleRoles)).ReadAll(); err != nil {
		return "", err
	}
	dayMoneyRoles, err := os.ReadFile(filepath.FromSlash(dayMoneyRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(dayMoneyRoles)).ReadAll(); err != nil {
		return "", err
	}
	evidenceUploadRoles, err := os.ReadFile(filepath.FromSlash(evidenceUploadRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(evidenceUploadRoles)).ReadAll(); err != nil {
		return "", err
	}
	debriefsRoles, err := os.ReadFile(filepath.FromSlash(debriefsRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(debriefsRoles)).ReadAll(); err != nil {
		return "", err
	}
	extraworkRoles, err := os.ReadFile(filepath.FromSlash(extraworkRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(extraworkRoles)).ReadAll(); err != nil {
		return "", err
	}
	projectEnrolRoles, err := os.ReadFile(filepath.FromSlash(projectEnrolRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(projectEnrolRoles)).ReadAll(); err != nil {
		return "", err
	}
	ssaEntryRoles, err := os.ReadFile(filepath.FromSlash(ssaEntryRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(ssaEntryRoles)).ReadAll(); err != nil {
		return "", err
	}
	clusterFacilitationRoles, err := os.ReadFile(filepath.FromSlash(clusterFacilitationRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(clusterFacilitationRoles)).ReadAll(); err != nil {
		return "", err
	}
	activityFacilitatorRoles, err := os.ReadFile(filepath.FromSlash(activityFacilitatorRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(activityFacilitatorRoles)).ReadAll(); err != nil {
		return "", err
	}
	clusterMembershipRoles, err := os.ReadFile(filepath.FromSlash(clusterMembershipRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(clusterMembershipRoles)).ReadAll(); err != nil {
		return "", err
	}
	clusterCreateRoles, err := os.ReadFile(filepath.FromSlash(clusterCreateRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(clusterCreateRoles)).ReadAll(); err != nil {
		return "", err
	}
	mscsRoles, err := os.ReadFile(filepath.FromSlash(mscsRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(mscsRoles)).ReadAll(); err != nil {
		return "", err
	}
	relayOpsRoles, err := os.ReadFile(filepath.FromSlash(relayOpsRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(relayOpsRoles)).ReadAll(); err != nil {
		return "", err
	}
	clusterOnboardRoles, err := os.ReadFile(filepath.FromSlash(clusterOnboardRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(clusterOnboardRoles)).ReadAll(); err != nil {
		return "", err
	}
	loansLedgerRoles, err := os.ReadFile(filepath.FromSlash(loansLedgerRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(loansLedgerRoles)).ReadAll(); err != nil {
		return "", err
	}
	fieldOpsRoles, err := os.ReadFile(filepath.FromSlash(fieldOpsRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(fieldOpsRoles)).ReadAll(); err != nil {
		return "", err
	}
	financeRoles, err := os.ReadFile(filepath.FromSlash(financeRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(financeRoles)).ReadAll(); err != nil {
		return "", err
	}
	workforceOpsRoles, err := os.ReadFile(filepath.FromSlash(workforceOpsRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(workforceOpsRoles)).ReadAll(); err != nil {
		return "", err
	}
	supportRoles, err := os.ReadFile(filepath.FromSlash(supportRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(supportRoles)).ReadAll(); err != nil {
		return "", err
	}
	messagingRoles, err := os.ReadFile(filepath.FromSlash(messagingRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(messagingRoles)).ReadAll(); err != nil {
		return "", err
	}
	schedulerJobsRoles, err := os.ReadFile(filepath.FromSlash(schedulerJobsRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(schedulerJobsRoles)).ReadAll(); err != nil {
		return "", err
	}
	settingsRoles, err := os.ReadFile(filepath.FromSlash(settingsRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(settingsRoles)).ReadAll(); err != nil {
		return "", err
	}
	schoolActionsRoles, err := os.ReadFile(filepath.FromSlash(schoolActionsRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(schoolActionsRoles)).ReadAll(); err != nil {
		return "", err
	}
	todoRoles, err := os.ReadFile(filepath.FromSlash(todoRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(todoRoles)).ReadAll(); err != nil {
		return "", err
	}
	todoUnsnoozeRoles, err := os.ReadFile(filepath.FromSlash(todoUnsnoozeRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(todoUnsnoozeRoles)).ReadAll(); err != nil {
		return "", err
	}
	presenceRoles, err := os.ReadFile(filepath.FromSlash(presenceRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(presenceRoles)).ReadAll(); err != nil {
		return "", err
	}
	mypdRoles, err := os.ReadFile(filepath.FromSlash(mypdRolesFile))
	if err != nil {
		return "", err
	}
	if _, err := conn.Conn().PgConn().Exec(ctx, string(mypdRoles)).ReadAll(); err != nil {
		return "", err
	}
	buffer := make([]byte, 24)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	password := hex.EncodeToString(buffer)
	// Hex only, so it is safe to inline: ALTER ROLE takes no bind parameters.
	if _, err := conn.Exec(ctx, "ALTER ROLE "+gatewayRole+" PASSWORD '"+password+"'"); err != nil {
		return "", err
	}
	return password, nil
}

// ── helpers ─────────────────────────────────────────────────────────────────

// testClient is the address a test's requests come from: one per test, so a
// test's rate limits are its own.
func testClient(t *testing.T) string {
	sum := 0
	for _, r := range t.Name() {
		sum = (sum*31 + int(r)) % 65000
	}
	return fmt.Sprintf("10.%d.%d.%d", sum/256%256, sum%256, len(t.Name())%250+1)
}

func token(t *testing.T, userID, role string, expires time.Duration) string {
	t.Helper()
	signed, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": userID, "activeRole": role,
		"iat": time.Now().Unix(), "exp": time.Now().Add(expires).Unix(),
	}).SignedString([]byte(signingSecret))
	if err != nil {
		t.Fatal(err)
	}
	return signed
}

func authed[T any](message *T, bearer string) *connect.Request[T] {
	request := connect.NewRequest(message)
	if bearer != "" {
		request.Header().Set("Authorization", "Bearer "+bearer)
	}
	return request
}

func schoolsClient() schoolsv1connect.SchoolServiceClient {
	return schoolsv1connect.NewSchoolServiceClient(http.DefaultClient, baseURL)
}

type account struct {
	userID, staffID, role string
}

// accountWithSchools returns the active account in role holding the most
// operating schools (at least `least`), skipping the user id `not`.
func accountWithSchools(t *testing.T, role string, least int, not string) account {
	t.Helper()
	found := account{role: role}
	err := admin.QueryRow(context.Background(), `
SELECT u.id, sp.id
FROM "user" u
JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
LEFT JOIN staff_school_assignment a ON a.staff_id = sp.id
LEFT JOIN school s ON s.id = a.school_id
  AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
WHERE u.active_role = $1 AND u.is_active AND u.deleted_at IS NULL AND u.status = 'active'
  AND u.id <> $3
GROUP BY u.id, sp.id
HAVING count(DISTINCT s.id) >= $2
ORDER BY count(DISTINCT s.id) DESC, u.id
LIMIT 1`, role, least, not).Scan(&found.userID, &found.staffID)
	if err != nil {
		t.Fatalf("the test database has no %s with %d+ schools (seed it with `manage.py seed --demo`): %v", role, least, err)
	}
	return found
}

// expectedSchoolIDs is the direct portfolio written independently of the
// gateway's query: a join, not a sub-select.
func expectedSchoolIDs(t *testing.T, staffID string) []string {
	t.Helper()
	rows, err := admin.Query(context.Background(), `
SELECT DISTINCT s.id
FROM staff_school_assignment a
JOIN school s ON s.id = a.school_id
WHERE a.staff_id = $1
  AND s.deleted_at IS NULL
  AND s.operational_status IN ('active', 'reopened')`, staffID)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	ids := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			t.Fatal(err)
		}
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func listAll(t *testing.T, bearer string, pageSize int32) []*schoolsv1.School {
	t.Helper()
	var all []*schoolsv1.School
	for page := int32(1); ; page++ {
		response, err := schoolsClient().ListMySchools(context.Background(), authed(&schoolsv1.ListMySchoolsRequest{
			Page: &commonv1.PageRequest{Page: page, PageSize: pageSize},
		}, bearer))
		if err != nil {
			t.Fatalf("page %d: %v", page, err)
		}
		all = append(all, response.Msg.GetSchools()...)
		if page >= response.Msg.GetPage().GetTotalPages() {
			if int64(len(all)) != response.Msg.GetPage().GetTotal() {
				t.Fatalf("paging returned %d rows, total says %d", len(all), response.Msg.GetPage().GetTotal())
			}
			return all
		}
	}
}

func idsOf(schools []*schoolsv1.School) []string {
	ids := make([]string, 0, len(schools))
	for _, school := range schools {
		ids = append(ids, school.GetId())
	}
	sort.Strings(ids)
	return ids
}

// ── schema contract ─────────────────────────────────────────────────────────

// Every column the gateway's SQL names, with the type its Go code scans into.
// When an existing-application migration changes one of these, this test
// fails before any gateway query does.
func TestExistingSchemaContract(t *testing.T) {
	contract := map[string]string{
		"user.id": "character varying", "user.email": "character varying",
		"user.name": "character varying", "user.roles": "ARRAY",
		"user.active_role": "character varying", "user.status": "character varying",
		"user.is_active": "boolean", "user.deleted_at": "timestamp with time zone",
		"user.must_change_password": "boolean",
		"staff_profile.id":          "character varying", "staff_profile.user_id": "character varying",
		"staff_profile.deleted_at":         "timestamp with time zone",
		"acting_assignment.appointee_id":   "character varying",
		"acting_assignment.cancelled_at":   "timestamp with time zone",
		"acting_assignment.expired_at":     "timestamp with time zone",
		"acting_assignment.start_date":     "date",
		"acting_assignment.end_date":       "date",
		"staff_school_assignment.staff_id": "character varying", "staff_school_assignment.school_id": "character varying",
		"school.id": "character varying", "school.school_id": "character varying",
		"school.name": "character varying", "school.school_type": "character varying",
		"school.operational_status": "character varying", "school.cluster_status": "character varying",
		"school.current_fy_ssa_status": "character varying", "school.planning_readiness": "character varying",
		"school.region_id": "character varying", "school.district_id": "character varying",
		"school.sub_county_id": "character varying", "school.parish_id": "character varying",
		"school.cluster_id": "character varying", "school.enrollment": "integer",
		"school.salesforce_account_id": "character varying", "school.deleted_at": "timestamp with time zone",
		"region.id": "character varying", "region.name": "character varying",
		"district.id": "character varying", "district.name": "character varying",
		"sub_county.id": "character varying", "sub_county.name": "character varying",
		"parish.id": "character varying", "parish.name": "character varying",
	}
	rows, err := admin.Query(context.Background(), `
SELECT table_name || '.' || column_name, data_type
FROM information_schema.columns WHERE table_schema = 'public'`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	actual := map[string]string{}
	for rows.Next() {
		var column, dataType string
		if err := rows.Scan(&column, &dataType); err != nil {
			t.Fatal(err)
		}
		actual[column] = dataType
	}
	for column, want := range contract {
		if got, ok := actual[column]; !ok {
			t.Errorf("%s is missing from the existing schema", column)
		} else if got != want {
			t.Errorf("%s is %q, the gateway expects %q", column, got, want)
		}
	}
}

// ── database protection ─────────────────────────────────────────────────────

// Signing in and account administration moved to Go (owner brief,
// 2026-11-11), so the gateway reads the sign-in columns and writes the
// lockout, password, status, name, email and role columns
// (identity_roles.sql). What it still may never do is below: make anyone a
// superuser or staff, enrol a second factor, rewrite or remove an audit row,
// delete a session or an account, or touch records it was not granted.
func TestGatewayRoleCanNeitherWriteNorReadSecrets(t *testing.T) {
	const rw = `BEGIN READ WRITE; `
	statements := map[string]string{
		"update a school":                         `UPDATE school SET name = name`,
		"delete an assignment":                    `DELETE FROM staff_school_assignment`,
		"insert a region":                         `INSERT INTO region (id, name) VALUES ('x', 'x')`,
		"create a table":                          `CREATE TABLE gateway_should_not_exist (id int)`,
		"alter a table":                           `ALTER TABLE school ADD COLUMN gateway_should_not_exist int`,
		"read an evidence file's storage address": `SELECT uri FROM evidence_record LIMIT 1`,
		"read an evidence review note":            `SELECT review_note FROM evidence_record LIMIT 1`,
		"leave read-only then update":             `SET default_transaction_read_only = off; UPDATE school SET name = name`,
		"make an account a superuser":             rw + `UPDATE "user" SET is_superuser = is_superuser`,
		"make an account staff":                   rw + `UPDATE "user" SET is_staff = is_staff`,
		"enrol a second factor":                   rw + `UPDATE "user" SET mfa_secret = mfa_secret`,
		"change an account's id":                  rw + `UPDATE "user" SET id = id`,
		"rewrite an audit row":                    rw + `UPDATE audit_log SET reason = reason`,
		"delete audit rows":                       rw + `DELETE FROM audit_log`,
		"delete sessions":                         rw + `DELETE FROM refresh_token`,
		"delete an account":                       rw + `DELETE FROM "user"`,
		"delete a partner":                        rw + `DELETE FROM partner`,
		"delete a school handover":                rw + `DELETE FROM partner_assignment`,
		"delete an activity":                      rw + `DELETE FROM activity`,
		"delete an acting appointment":            rw + `DELETE FROM acting_assignment`,
		"re-seat an acting appointment":           rw + `UPDATE acting_assignment SET seat_id = seat_id`,
		"read the payload of the log":             `SELECT payload FROM audit_log LIMIT 1`,
		// Scheduling a school visit (activities_roles.sql): the save inserts
		// its rows and changes nothing after them. Moving one (29) changes
		// only its day, batch and status.
		"price an activity":                     rw + `UPDATE activity SET est_cost_cents = est_cost_cents`,
		"hand an activity to someone else":      rw + `UPDATE activity SET responsible_staff_id = responsible_staff_id`,
		"move an activity to another school":    rw + `UPDATE activity SET school_id = school_id`,
		"give an activity to a partner":         rw + `UPDATE activity SET assigned_partner_id = assigned_partner_id`,
		"change what an activity is":            rw + `UPDATE activity SET activity_type = activity_type`,
		"start an activity":                     rw + `UPDATE activity SET execution_started_at = execution_started_at`,
		"record an activity's delivery":         rw + `UPDATE activity SET actual_delivery_date = actual_delivery_date`,
		"give an activity its Salesforce ID":    rw + `UPDATE activity SET salesforce_activity_id = salesforce_activity_id`,
		"remove an activity softly":             rw + `UPDATE activity SET deleted_at = deleted_at`,
		"change an activity's expected numbers": rw + `UPDATE activity SET expected_participants = expected_participants`,
		"move a day to another date":            rw + `UPDATE daily_visit_batch SET visit_date = visit_date`,
		"give a day to someone else":            rw + `UPDATE daily_visit_batch SET responsible_user = responsible_user`,
		"rewrite the schedule trail":            rw + `UPDATE activity_schedule_change SET reason = reason`,
		"remove the schedule trail":             rw + `DELETE FROM activity_schedule_change`,
		// A notice's words (notification.body) are read by the notification
		// centre since 2026-11-13 (deploy/db/roles.sql), so they are no longer
		// refused to this login.
		"write a notice":             rw + `UPDATE notification SET resolved_at = resolved_at`,
		"change a day's figures":     rw + `UPDATE daily_visit_batch SET daily_pool_amount = daily_pool_amount`,
		"delete a day":               rw + `DELETE FROM daily_visit_batch`,
		"write a cost line":          rw + `INSERT INTO activity_schedule_cost_line (id) VALUES ('x')`,
		"delete the costs to follow": rw + `DELETE FROM daily_visit_costs_to_follow`,
		"read the costs' provenance": `SELECT provenance FROM daily_visit_costs_to_follow LIMIT 1`,
		// The Group Training (docs/migration/38): invitations are added,
		// never changed or removed, and no cluster is written.
		"change an invitation":             rw + `UPDATE cluster_activity_attendance SET invited = invited`,
		"record an attendance":             rw + `UPDATE cluster_activity_attendance SET attended = attended`,
		"remove an invitation":             rw + `DELETE FROM cluster_activity_attendance`,
		"re-cluster a session":             rw + `UPDATE activity SET cluster_id = cluster_id`,
		"change a session's invited count": rw + `UPDATE activity SET schools_invited = schools_invited`,
		"write a cluster":                  rw + `UPDATE cluster SET responsible_staff_id = responsible_staff_id`,
		"delete a ledger mark":             rw + `DELETE FROM target_ledger_dirty`,
		"delete domain events":             rw + `DELETE FROM domain_event_log`,
		"rescore an SSA recommendation":    rw + `UPDATE ssa_recommendation SET score = score`,
		"lock a school":                    rw + `SELECT id FROM school LIMIT 1 FOR UPDATE`,
		// Cancelling a visit (30): advances are withdrawn only through
		// gateway_money.withdraw_unmoved_advances.
		"delete an advance":        rw + `DELETE FROM advance_request`,
		"change an advance":        rw + `UPDATE advance_request SET status = status`,
		"become the withdraw role": rw + `SET ROLE edify_advance_withdraw_owner`,
		"write a milestone credit": rw + `UPDATE hr_milestone_progress_credit SET reversed_at = reversed_at`,
		// Editing a visit (31) writes its goal and expected outcome only.
		"re-aim a visit at another intervention": rw + `UPDATE activity SET focus_intervention = focus_intervention`,
		"change what a visit is for":             rw + `UPDATE activity SET purpose_type = purpose_type`,
		"rewrite a visit's SSA verdict":          rw + `UPDATE activity SET ssa_alignment = ssa_alignment`,
		// An online Group Training (48) inserts its cost revision and changes
		// nothing of it, nor how the session is delivered.
		"reprice a cost revision":       rw + `UPDATE activity_cost_snapshot SET operational_cost = operational_cost`,
		"supersede a cost revision":     rw + `UPDATE activity_cost_snapshot SET is_current = is_current`,
		"remove a cost revision":        rw + `DELETE FROM activity_cost_snapshot`,
		"change how a session is given": rw + `UPDATE activity SET programme_delivery_mode = programme_delivery_mode`,
		"undo a snooze for someone":     rw + `DELETE FROM command_center_todo_snooze`,
		"hand a snooze to someone else": rw + `UPDATE command_center_todo_snooze SET user_id = user_id`,
		// The presence stamp (65) goes through gateway_presence.beat only.
		"stamp someone's presence directly": rw + `UPDATE "user" SET last_seen_at = last_seen_at`,
		"rename someone's page":             rw + `UPDATE "user" SET last_seen_path = last_seen_path`,
		"credit someone's time directly":    rw + `UPDATE presence_time SET seconds = seconds`,
		"invent time on a page":             rw + `INSERT INTO presence_time (id, user_id, day, section, working_on, seconds) VALUES ('x', 'x', current_date, 'x', 'x', 1)`,
		"remove time on a page":             rw + "DELETE FROM presence_time",
		"lengthen a sign-in":                rw + `UPDATE login_event SET active_seconds = active_seconds`,
		"become the presence owner":         rw + `SET ROLE edify_presence_owner`,
		"read a snooze's words":             `SELECT title FROM command_center_todo_snooze LIMIT 1`,
		"write a Today decision":            rw + `INSERT INTO command_center_today_action (id) VALUES ('x')`,
		// My Professional Development's read (deploy/db/mypd_roles.sql): a
		// course's status alone, a new allocation alone, reminders only
		// through gateway_pd.close_course_reminders.
		"change a PD course's words":   rw + `UPDATE pd_request SET course_name = course_name`,
		"change an allocation's money": rw + `UPDATE pd_allocation SET annual_allocation = annual_allocation`,
		"remove an allocation":         rw + `DELETE FROM pd_allocation`,
		"remove a PD course":           rw + `DELETE FROM pd_request`,
		"become the reminders owner":   rw + `SET ROLE edify_pd_reminders_owner`,
	}
	for name, statement := range statements {
		t.Run(name, func(t *testing.T) {
			conn, err := gateway.Acquire(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Release()
			_, err = conn.Conn().PgConn().Exec(context.Background(), statement).ReadAll()
			var pgErr *pgconn.PgError
			if !errors.As(err, &pgErr) {
				t.Fatalf("the statement was not refused (err=%v)", err)
			}
			// 42501 insufficient_privilege, 25006 read_only_sql_transaction
			if pgErr.Code != "42501" && pgErr.Code != "25006" {
				t.Fatalf("refused for an unexpected reason: %s %s", pgErr.Code, pgErr.Message)
			}
			// Put the pooled session back the way the pool configured it.
			_, _ = conn.Conn().PgConn().Exec(context.Background(), "ROLLBACK").ReadAll()
			_, _ = conn.Exec(context.Background(), "SET default_transaction_read_only = on")
		})
	}
}

func TestStagingIdentityCheckAcceptsOnlyTheReadOnlyRole(t *testing.T) {
	staging := dbguard.Policy{Env: config.Staging}

	identity, err := dbguard.VerifyIdentity(context.Background(), staging, gateway)
	if err != nil {
		t.Fatalf("the read-only role must pass: %v", err)
	}
	if identity.Role != gatewayRole || identity.Superuser || len(identity.WritableTables) != 0 {
		t.Fatalf("identity: %+v", identity)
	}

	if _, err := dbguard.VerifyIdentity(context.Background(), staging, admin); !errors.Is(err, dbguard.ErrRefused) {
		t.Fatalf("an owner or superuser connection must be refused in staging, got %v", err)
	}
}

// ── the slice ───────────────────────────────────────────────────────────────

func TestListMySchoolsIsExactlyTheDirectPortfolio(t *testing.T) {
	tests := []struct {
		role  string
		least int
	}{
		{role: "CCEO", least: 1},
		// A Programme Lead's direct portfolio is whatever is assigned to
		// them personally, which may be nothing; never their team's schools.
		{role: "Program Lead", least: 0},
	}
	for _, test := range tests {
		t.Run(test.role, func(t *testing.T) {
			person := accountWithSchools(t, test.role, test.least, "")
			want := expectedSchoolIDs(t, person.staffID)

			schools := listAll(t, token(t, person.userID, test.role, time.Minute), 7)
			if got := idsOf(schools); strings.Join(got, ",") != strings.Join(want, ",") {
				t.Fatalf("got %d schools, want %d", len(got), len(want))
			}
			for _, school := range schools {
				if school.GetSchoolId() == "" || school.GetName() == "" || school.GetSchoolType() == "" {
					t.Fatalf("a school is missing its identity: %v", school)
				}
			}
		})
	}
}

func TestSearchNarrowsWithinThePortfolio(t *testing.T) {
	person := accountWithSchools(t, "CCEO", 2, "")
	bearer := token(t, person.userID, "CCEO", time.Minute)
	first := listAll(t, bearer, 200)[0]

	response, err := schoolsClient().ListMySchools(context.Background(), authed(&schoolsv1.ListMySchoolsRequest{
		Search: strings.ToLower(first.GetSchoolId()),
	}, bearer))
	if err != nil {
		t.Fatal(err)
	}
	if len(response.Msg.GetSchools()) == 0 {
		t.Fatal("searching for a School ID in the portfolio found nothing")
	}
	for _, school := range response.Msg.GetSchools() {
		if !strings.Contains(strings.ToLower(school.GetSchoolId()+" "+school.GetName()), strings.ToLower(first.GetSchoolId())) {
			t.Fatalf("%q does not match the search", school.GetSchoolId())
		}
	}

	everything, err := schoolsClient().ListMySchools(context.Background(), authed(&schoolsv1.ListMySchoolsRequest{Search: "%"}, bearer))
	if err != nil {
		t.Fatal(err)
	}
	if everything.Msg.GetPage().GetTotal() != 0 {
		t.Fatal(`searching for "%" must look for the character, not match every school`)
	}
}

func TestGetMySchool(t *testing.T) {
	owner := accountWithSchools(t, "CCEO", 1, "")
	other := accountWithSchools(t, "CCEO", 0, owner.userID)
	bearer := token(t, owner.userID, "CCEO", time.Minute)
	mine := listAll(t, bearer, 200)[0]

	for _, ref := range []string{mine.GetSchoolId(), mine.GetId()} {
		response, err := schoolsClient().GetMySchool(context.Background(), authed(&schoolsv1.GetMySchoolRequest{SchoolRef: ref}, bearer))
		if err != nil || response.Msg.GetSchool().GetId() != mine.GetId() {
			t.Fatalf("by %q: %v / %v", ref, response, err)
		}
	}

	// The other officer asks for a school that is the owner's and not theirs.
	otherIDs := map[string]bool{}
	for _, id := range expectedSchoolIDs(t, other.staffID) {
		otherIDs[id] = true
	}
	otherBearer := token(t, other.userID, "CCEO", time.Minute)
	for _, school := range listAll(t, bearer, 200) {
		if otherIDs[school.GetId()] {
			continue
		}
		for _, ref := range []string{school.GetSchoolId(), school.GetId()} {
			_, err := schoolsClient().GetMySchool(context.Background(), authed(&schoolsv1.GetMySchoolRequest{SchoolRef: ref}, otherBearer))
			if connect.CodeOf(err) != connect.CodeNotFound || apierr.Reason(err) != apierr.ReasonSchoolNotFound {
				t.Fatalf("another officer's school must be not found, got %v", err)
			}
		}
		return
	}
	t.Fatal("the seed has no school held by one officer and not the other")
}

func TestClosedAndDeletedSchoolsLeaveThePortfolio(t *testing.T) {
	person := accountWithSchools(t, "CCEO", 2, "")
	bearer := token(t, person.userID, "CCEO", time.Minute)
	target := listAll(t, bearer, 200)[0].GetId()
	ctx := context.Background()

	var original string
	if err := admin.QueryRow(ctx, `SELECT operational_status FROM school WHERE id = $1`, target).Scan(&original); err != nil {
		t.Fatal(err)
	}
	changes := map[string]string{
		"soft-deleted": `UPDATE school SET deleted_at = now() WHERE id = $1`,
		"closed":       `UPDATE school SET operational_status = 'closed' WHERE id = $1`,
	}
	for name, change := range changes {
		t.Run(name, func(t *testing.T) {
			t.Cleanup(func() {
				_, err := admin.Exec(ctx, `UPDATE school SET deleted_at = NULL, operational_status = $2 WHERE id = $1`, target, original)
				if err != nil {
					t.Errorf("restoring the fixture school: %v", err)
				}
			})
			if _, err := admin.Exec(ctx, change, target); err != nil {
				t.Fatal(err)
			}
			for _, id := range idsOf(listAll(t, bearer, 200)) {
				if id == target {
					t.Fatalf("a %s school is still listed", name)
				}
			}
		})
	}
}

func TestAuthenticationAgainstTheExistingAccounts(t *testing.T) {
	person := accountWithSchools(t, "CCEO", 1, "")
	ctx := context.Background()
	list := func(bearer string) error {
		_, err := schoolsClient().ListMySchools(ctx, authed(&schoolsv1.ListMySchoolsRequest{}, bearer))
		return err
	}

	t.Run("no token", func(t *testing.T) {
		err := list("")
		if connect.CodeOf(err) != connect.CodeUnauthenticated || apierr.Reason(err) != apierr.ReasonAuthMissing {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("expired token", func(t *testing.T) {
		err := list(token(t, person.userID, "CCEO", -time.Minute))
		if apierr.Reason(err) != apierr.ReasonAuthExpired {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("unknown user", func(t *testing.T) {
		err := list(token(t, "no-such-user", "CCEO", time.Minute))
		if connect.CodeOf(err) != connect.CodeUnauthenticated {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("a token cannot claim a role the account does not hold", func(t *testing.T) {
		var adminUser string
		err := admin.QueryRow(ctx, `
SELECT id FROM "user"
WHERE active_role = 'Admin' AND is_active AND deleted_at IS NULL AND status = 'active'
  AND NOT ('CCEO' = ANY(roles))
LIMIT 1`).Scan(&adminUser)
		if err != nil {
			t.Fatalf("the seed has no Admin account: %v", err)
		}
		err = list(token(t, adminUser, "CCEO", time.Minute))
		if connect.CodeOf(err) != connect.CodePermissionDenied || apierr.Reason(err) != apierr.ReasonRoleNotMigrated {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("deactivating the account stops a live token at once", func(t *testing.T) {
		bearer := token(t, person.userID, "CCEO", time.Minute)
		if err := list(bearer); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() {
			if _, err := admin.Exec(ctx, `UPDATE "user" SET is_active = true WHERE id = $1`, person.userID); err != nil {
				t.Errorf("restoring the account: %v", err)
			}
		})
		if _, err := admin.Exec(ctx, `UPDATE "user" SET is_active = false WHERE id = $1`, person.userID); err != nil {
			t.Fatal(err)
		}
		if err := list(bearer); connect.CodeOf(err) != connect.CodeUnauthenticated {
			t.Fatalf("got %v", err)
		}
	})
}

func TestSessionAndErrorDetailCarryTheRequestIdentity(t *testing.T) {
	person := accountWithSchools(t, "CCEO", 1, "")
	identityClient := identityv1connect.NewIdentityServiceClient(http.DefaultClient, baseURL)

	response, err := identityClient.GetSession(context.Background(),
		authed(&identityv1.GetSessionRequest{}, token(t, person.userID, "CCEO", time.Minute)))
	if err != nil {
		t.Fatal(err)
	}
	session := response.Msg.GetSession()
	if session.GetUserId() != person.userID || session.GetStaffProfileId() != person.staffID || session.GetActiveRole() != "CCEO" {
		t.Fatalf("session: %v", session)
	}
	if response.Header().Get("X-Request-Id") == "" || response.Header().Get("traceparent") == "" {
		t.Fatalf("trace headers missing: %v", response.Header())
	}

	request := authed(&identityv1.GetSessionRequest{}, "")
	request.Header().Set("X-Request-Id", "integration-req-01")
	_, err = identityClient.GetSession(context.Background(), request)
	var connectErr *connect.Error
	if !errors.As(err, &connectErr) || len(connectErr.Details()) != 1 {
		t.Fatalf("want one error detail, got %v", err)
	}
	value, err := connectErr.Details()[0].Value()
	if err != nil {
		t.Fatal(err)
	}
	detail, ok := value.(*commonv1.ErrorDetail)
	if !ok || detail.GetRequestId() != "integration-req-01" || len(detail.GetTraceId()) != 32 {
		t.Fatalf("detail: %v", value)
	}
}

func TestReadinessAgainstTheRealDatabase(t *testing.T) {
	response, err := http.Get(baseURL + "/readyz")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("readiness: %d", response.StatusCode)
	}
}

// seedCountries is countryctl seed-legacy on the test database: the
// countries, Uganda's settings, and every school and account the seed holds
// mapped to Uganda. Run again, it adds only what is missing.
func seedCountries(ctx context.Context, conn *pgx.Conn) error {
	tx, err := conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if _, err := country.SeedLegacy(ctx, tx, "integration"); err != nil {
		return err
	}
	if _, err := country.SeedGeography(ctx, tx, "integration"); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
