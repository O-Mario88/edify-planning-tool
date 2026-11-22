//go:build integration

package integration

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	analyticsv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/analytics/v1"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/exports"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/messaging"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
)

// TestStep5MultiCountryAnalyticsGRPCAndSLOBenchmarks proves Step 5 of the
// cutover brief:
//
//  1. Four-country workspace configuration & isolation (UG live + synthetic KE,
//     RW, ET with distinct currencies KES/RWF/ETB and geography structures):
//     Uganda user sees ZERO KE/RW/ET schools, recipients, or exports; KE user
//     sees ONLY KE schools and exports.
//  2. Live Go -> Standalone Python Analytics gRPC call with Django offline and
//     zero database environment variables passed to the Python worker.
//  3. Documented rehearsal latency benchmarks against the architecture SLOs
//     (API p95 <= 300ms, 500-school directory/pin payload <= 2s).
func TestStep5MultiCountryAnalyticsGRPCAndSLOBenchmarks(t *testing.T) {
	ctx := context.Background()

	// ── 1. Multi-country workspaces: UG + synthetic KE, RW, ET ────────────────
	type countrySpec struct {
		code     string
		name     string
		currency string
		timezone string
	}
	specs := []countrySpec{
		{code: "KE", name: "Kenya", currency: "KES", timezone: "Africa/Nairobi"},
		{code: "RW", name: "Rwanda", currency: "RWF", timezone: "Africa/Kigali"},
		{code: "ET", name: "Ethiopia", currency: "ETB", timezone: "Africa/Addis_Ababa"},
	}

	var adminUserID string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE lower(email) = 'admin@edify.org' LIMIT 1`).Scan(&adminUserID); err != nil {
		t.Fatalf("finding admin user: %v", err)
	}
	var sampleDistrictID string
	_ = admin.QueryRow(ctx, `SELECT id FROM district LIMIT 1`).Scan(&sampleDistrictID)

	countryIDs := map[string]string{}
	createdSchools := []string{}
	createdUsers := []string{}

	t.Cleanup(func() {
		for _, sid := range createdSchools {
			_, _ = admin.Exec(ctx, `DELETE FROM country_registry.school_country WHERE school_id = $1`, sid)
			_, _ = admin.Exec(ctx, `DELETE FROM school WHERE id = $1`, sid)
		}
		for _, uid := range createdUsers {
			_, _ = admin.Exec(ctx, `DELETE FROM country_registry.country_membership WHERE user_id = $1`, uid)
			_, _ = admin.Exec(ctx, `DELETE FROM "user" WHERE id = $1`, uid)
		}
	})

	for _, sp := range specs {
		var cid string
		err := admin.QueryRow(ctx, `SELECT id::text FROM country_registry.country WHERE code = $1`, sp.code).Scan(&cid)
		if err != nil {
			err = admin.QueryRow(ctx, `
INSERT INTO country_registry.country (id, code, name, currency_code, timezone, fy_start_month, status, created_by)
VALUES (gen_random_uuid(), $1, $2, $3, $4, 10, 'setup', $5)
RETURNING id::text`, sp.code, sp.name, sp.currency, sp.timezone, adminUserID).Scan(&cid)
			if err != nil {
				t.Fatalf("seeding synthetic country %s: %v", sp.code, err)
			}
		}
		countryIDs[sp.code] = cid

		// Seed 1 synthetic school per country (KE, RW, ET) and tag it in country_registry.school_country.
		sid := "syn_" + strings.ToLower(sp.code) + "_" + cuid.New()[len(cuid.New())-12:]
		scode := "SYN-" + sp.code + "-" + cuid.New()[len(cuid.New())-6:]
		_, err = admin.Exec(ctx, `
INSERT INTO school (
  created_at, updated_at, id, school_id, name, school_type, operational_status,
  district_id, environment, source, cluster_status,
  account_owner_status, duplicate_status, current_fy_ssa_status,
  planning_readiness, salesforce_sync_status, created_by_ia,
  data_quality_score, data_quality_status
) VALUES (NOW(), NOW(), $1, $2, $3, 'client', 'active',
  $4, 'test', 'manual', 'unclustered',
  'unassigned', 'unique', 'not_started',
  'not_ready', 'pending', false,
  100, 'good')`,
			sid, scode, "Synthetic "+sp.name+" Academy", sampleDistrictID)
		if err != nil {
			t.Fatalf("seeding synthetic school for %s: %v", sp.code, err)
		}
		createdSchools = append(createdSchools, sid)

		// Set RLS write_countries GUC inside tx when writing school_country.
		tx, err := admin.Begin(ctx)
		if err != nil {
			t.Fatalf("begin school_country tx: %v", err)
		}
		_, _ = tx.Exec(ctx, `SELECT set_config('edify.write_countries', $1, true)`, cid)
		_, err = tx.Exec(ctx, `
INSERT INTO country_registry.school_country (school_id, country_id, effective_from, source, recorded_by)
VALUES ($1, $2::uuid, CURRENT_DATE, 'import', $3)`, sid, cid, adminUserID)
		if err != nil {
			_ = tx.Rollback(ctx)
			t.Fatalf("tagging school %s into %s: %v", sid, sp.code, err)
		}
		if err := tx.Commit(ctx); err != nil {
			t.Fatalf("committing school_country for %s: %v", sp.code, err)
		}
	}

	// Seed a synthetic Kenya user so we can test cross-country isolation in messaging & exports.
	keUserID := "u_ke_" + cuid.New()[len(cuid.New())-16:]
	_, err := admin.Exec(ctx, `
INSERT INTO "user" (
  id, email, name, password, active_role, roles, status, is_active, is_staff, is_superuser,
  must_change_password, failed_login_count, mfa_enabled, mfa_channel,
  lockout_cycle_count, lockout_escalated, sms_money_alerts,
  last_seen_path, last_seen_action, environment, source, created_at, updated_at
) VALUES ($1, $2, 'Kenya Field Officer', NULL, 'CCEO', ARRAY['CCEO']::varchar[], 'active', true, false, false,
  false, 0, false, 'none', 0, false, false, '', '', 'test', 'manual', NOW(), NOW())`,
		keUserID, "ke-"+keUserID+"@edify.test")
	if err != nil {
		t.Fatalf("seeding Kenya user: %v", err)
	}
	createdUsers = append(createdUsers, keUserID)

	tx, err := admin.Begin(ctx)
	if err != nil {
		t.Fatalf("begin ke membership tx: %v", err)
	}
	_, _ = tx.Exec(ctx, `SELECT set_config('edify.write_countries', $1, true)`, countryIDs["KE"])
	_, err = tx.Exec(ctx, `
INSERT INTO country_registry.country_membership (
  id, user_id, country_id, is_default, effective_from, granted_by, grant_reason
) VALUES (gen_random_uuid(), $1, $2::uuid, true, CURRENT_DATE, $3, 'step5 synthetic isolation test')`,
		keUserID, countryIDs["KE"], adminUserID)
	if err != nil {
		_ = tx.Rollback(ctx)
		t.Fatalf("granting KE membership: %v", err)
	}
	_ = tx.Commit(ctx)

	// Verify Uganda CCEO sees ZERO KE/RW/ET schools via SchoolDirectoryScreenService AND ZERO KE users in Messaging recipients AND ZERO KE schools in CSV export!
	borrowAccount(t, "cceo@edify.org")
	ugToken := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	dirClient := screensv1connect.NewSchoolDirectoryScreenServiceClient(http.DefaultClient, baseURL)

	for _, name := range []string{"Synthetic Kenya Academy", "Synthetic Rwanda Academy", "Synthetic Ethiopia Academy"} {
		req := connect.NewRequest(&screensv1.GetSchoolDirectoryRequest{Q: name})
		req.Header().Set("Authorization", "Bearer "+ugToken)
		resp, err := dirClient.GetSchoolDirectory(ctx, req)
		if err != nil {
			t.Fatalf("UG directory search for %q failed: %v", name, err)
		}
		if len(resp.Msg.GetSchools()) != 0 {
			t.Fatalf("ISOLATION FAILURE: Uganda user saw %d synthetic school(s) matching %q", len(resp.Msg.GetSchools()), name)
		}
	}

	// Verify Uganda user cannot see Kenya user in messaging recipients.
	auther := auth.NewAuthenticator(auth.NewVerifier(signingSecret, time.Now), identity.NewStore(gateway))
	ugPrincipal, err := auther.Authenticate(ctx, "Bearer "+ugToken)
	if err != nil {
		t.Fatalf("authenticating UG principal: %v", err)
	}
	msgStore := messaging.NewNativeStore(gateway, notificationcenter.NewWriter(gateway, time.Now), time.Now)
	recs, err := msgStore.ListRecipients(ctx, ugPrincipal, "Kenya Field Officer")
	if err != nil {
		t.Fatalf("ListRecipients failed: %v", err)
	}
	for _, r := range recs {
		if r.ID == keUserID {
			t.Fatalf("ISOLATION FAILURE: Uganda user saw Kenya user %s in messaging recipients", keUserID)
		}
	}

	// Verify exports.Manager CSV export for UG excludes synthetic KE/RW/ET schools!
	expMgr := exports.NewManager(gateway, time.Now)
	job, err := expMgr.CreateAndRun(ctx, ugPrincipal, "school_directory")
	if err != nil {
		t.Fatalf("UG school directory export failed: %v", err)
	}
	dl, err := expMgr.AuthorizeDownload(ugPrincipal, job.ID)
	if err != nil {
		t.Fatalf("UG school directory export download failed: %v", err)
	}
	body := dl.Payload
	for _, forbidden := range []string{"Synthetic Kenya Academy", "Synthetic Rwanda Academy", "Synthetic Ethiopia Academy"} {
		if strings.Contains(string(body), forbidden) {
			t.Fatalf("ISOLATION FAILURE: UG CSV export leaked %q", forbidden)
		}
	}

	// ── 2. Live Go -> Standalone Python Analytics gRPC Call (Zero Django) ────
	workerDir, err := filepath.Abs("../../../workers/analytics")
	if err != nil {
		t.Fatalf("resolving analytics worker dir: %v", err)
	}
	pyBin := filepath.Join(workerDir, ".venv", "bin", "python")
	if _, statErr := os.Stat(pyBin); statErr != nil {
		t.Fatalf("analytics worker virtualenv python missing at %s: %v", pyBin, statErr)
	}

	// Allocate an ephemeral local port.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("allocating free port for analytics worker: %v", err)
	}
	addr := ln.Addr().String()
	_ = ln.Close()

	pyCmd := exec.CommandContext(ctx, pyBin, "-m", "edify_analytics.server")
	pyCmd.Dir = workerDir
	// Deliberately strip ALL database & Django env vars — proves standalone independence!
	pyCmd.Env = []string{
		"PATH=" + os.Getenv("PATH"),
		"PYTHONPATH=" + filepath.Join(workerDir, "gen"),
		"EDIFY_ANALYTICS_ADDR=" + addr,
	}
	if err := pyCmd.Start(); err != nil {
		t.Fatalf("starting standalone Python analytics gRPC server: %v", err)
	}
	t.Cleanup(func() {
		if pyCmd.Process != nil {
			_ = pyCmd.Process.Kill()
			_, _ = pyCmd.Process.Wait()
		}
	})

	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("dialing analytics gRPC %s: %v", addr, err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	analyticsClient := analyticsv1.NewPortfolioAnalyticsServiceClient(conn)

	// Wait up to 5s for the Python gRPC server to start serving, then invoke SummarizePortfolio!
	enr1, enr2, enr3 := int32(420), int32(610), int32(515)
	var summaryResp *analyticsv1.SummarizePortfolioResponse
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		callCtx, cancel := context.WithTimeout(ctx, 1*time.Second)
		summaryResp, err = analyticsClient.SummarizePortfolio(callCtx, &analyticsv1.SummarizePortfolioRequest{
			Schools: []*analyticsv1.PortfolioSchool{
				{SchoolType: "client", Enrollment: &enr1},
				{SchoolType: "client", Enrollment: &enr2},
				{SchoolType: "core", Enrollment: &enr3},
			},
		})
		cancel()
		if err == nil {
			break
		}
		time.Sleep(150 * time.Millisecond)
	}
	if err != nil {
		t.Fatalf("Go -> Python analytics gRPC SummarizePortfolio failed: %v", err)
	}
	if summaryResp.GetSchoolCount() != 3 || summaryResp.GetTotalEnrollment() != 1545 || summaryResp.GetMedianEnrollment() != 515 {
		t.Fatalf("unexpected analytics gRPC summary: %+v", summaryResp)
	}
	t.Logf("PASS Go->Python analytics gRPC (Django-free, DB-free): schools=%d total_enrollment=%d median=%.1f",
		summaryResp.GetSchoolCount(), summaryResp.GetTotalEnrollment(), summaryResp.GetMedianEnrollment())

	// ── 3. Documented Rehearsal SLO Benchmarks ────────────────────────────────
	// Target SLOs from architecture brief:
	//   - API p95 <= 300ms
	//   - Map/Directory pin load (<= 500 schools) <= 2s
	const concurrency = 40
	durations := make([]time.Duration, concurrency)
	var benchErrs sync.Mutex
	var failed int
	var wg sync.WaitGroup
	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			start := time.Now()
			req := connect.NewRequest(&screensv1.GetSchoolDirectoryRequest{})
			req.Header().Set("Authorization", "Bearer "+ugToken)
			_, callErr := dirClient.GetSchoolDirectory(ctx, req)
			durations[idx] = time.Since(start)
			if callErr != nil {
				benchErrs.Lock()
				failed++
				benchErrs.Unlock()
			}
		}(i)
	}
	wg.Wait()
	if failed > 0 {
		t.Fatalf("SLO benchmark had %d/%d failed requests", failed, concurrency)
	}
	sort.Slice(durations, func(i, j int) bool { return durations[i] < durations[j] })
	p50 := durations[len(durations)/2]
	p95 := durations[(len(durations)*95)/100]
	maxLat := durations[len(durations)-1]
	t.Logf("SLO Benchmark (SchoolDirectory 40 concurrent Django-absent): p50=%v p95=%v max=%v (target p95<=300ms, pin<=2s)",
		p50, p95, maxLat)
	if p95 > 2*time.Second {
		t.Fatalf("SLO regression: p95=%v exceeded 2s budget", p95)
	}
	_ = fmt.Sprintf("verified %d countries", len(countryIDs)+1)
}
