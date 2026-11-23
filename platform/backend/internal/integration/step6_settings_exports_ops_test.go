//go:build integration

package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/scheduler"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/screens"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
)

// TestBatch19To21SettingsExportsSchedulerAndOpsWithoutDjango proves:
//   - Batch 19: Native /api/v1/settings/two-step (with policy guard + audit),
//     AccountService.SetNewPassword, POST /api/v1/exports + GET download +
//     ExportService.GetExport Connect RPC (with cross-user 403).
//   - Batch 20: Newly ported scheduler writers (hand_in_entered_work,
//     admin_maintenance_generation, weekly_fund_request, monthly_work_plan,
//     daily_plan_notifications, day_off_alerts, scheduler_watchdog).
//   - Batch 21: fieldops, financeops, and workforceops wired through both
//     SaveDrawer Connect RPC and /api/v1/ops/* HTTP endpoints.
//
// Zero Django calls (FallbackTracker.Total() == 0).
func TestBatch19To21SettingsExportsSchedulerAndOpsWithoutDjango(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	screens.GlobalFallbackTracker().Reset()
	cfg := config.Config{
		Env:         config.Test,
		JWTSecret:   signingSecret,
		StrictReads: true,
		GoSaves: config.GoSaves{
			ScheduleVisit:   true,
			RescheduleVisit: true,
			CancelVisit:     true,
			EditVisit:       true,
			GroupReschedule: true,
			GroupCancel:     true,
			CompleteVisit:   true,
			PLReview:        true,
			SchoolActions:   true,
		},
		Loans: config.Loans{
			PublicBaseURL:     publicBaseURL,
			DevMailboxDir:     mailbox,
			MailFrom:          "loans@edify.test",
			SMSProvider:       "dev_file",
			SMSDevDir:         smsbox,
			TrustProxyHeaders: true,
		},
		SignIn: config.SignIn{AppBaseURL: publicBaseURL},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := httptest.NewServer(server.New(cfg, gateway, nil, logger))
	t.Cleanup(srv.Close)

	cceoToken := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	pl1Token := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	iaToken := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()

	var cceoUserID, cceoStaffID, origName, origPhone, origChannel, origPassword string
	var origMFA, origMustChange bool
	if err := admin.QueryRow(ctx, `
SELECT u.id, COALESCE(sp.id, ''), u.name, COALESCE(u.phone, ''), u.mfa_enabled, u.mfa_channel, COALESCE(u.password, ''), u.must_change_password
  FROM "user" u
  LEFT JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
 WHERE lower(u.email) = 'cceo@edify.org' LIMIT 1`).Scan(
		&cceoUserID, &cceoStaffID, &origName, &origPhone, &origMFA, &origChannel, &origPassword, &origMustChange); err != nil {
		t.Fatalf("load cceo account: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(context.Background(), `
UPDATE "user"
   SET name = $2, phone = NULLIF($3, ''), mfa_enabled = $4, mfa_channel = $5, password = $6, must_change_password = $7
 WHERE id = $1`, cceoUserID, origName, origPhone, origMFA, origChannel, origPassword, origMustChange)
	})

	// ── 1. Batch 19: Settings Two-Step & Password Change ────────────────────
	t.Run("settings_two_step_and_password", func(t *testing.T) {
		res := doAuthJSON(t, srv.URL+"/api/v1/settings/two-step", cceoToken, map[string]any{
			"enabled": true,
			"channel": "email",
		})
		if res.StatusCode != http.StatusOK {
			t.Fatalf("two-step update expected 200, got %d: %s", res.StatusCode, res.Body)
		}
		var enabled bool
		var channel string
		if err := admin.QueryRow(ctx, `SELECT mfa_enabled, mfa_channel FROM "user" WHERE id = $1`, cceoUserID).Scan(&enabled, &channel); err != nil {
			t.Fatalf("read updated mfa: %v", err)
		}
		if !enabled || channel != "email" {
			t.Fatalf("expected mfa_enabled=true channel=email, got enabled=%v channel=%q", enabled, channel)
		}
		// Audit row recorded.
		var audCount int
		if err := admin.QueryRow(ctx, `
SELECT COUNT(*) FROM audit_log
 WHERE action = 'auth.mfa_settings_updated' AND subject_id = $1`, cceoUserID).Scan(&audCount); err != nil || audCount == 0 {
			t.Fatalf("expected auth.mfa_settings_updated audit row, got count=%d err=%v", audCount, err)
		}

		// Native password change via AccountService.SetNewPassword (requires must_change_password=true).
		if _, err := admin.Exec(ctx, `UPDATE "user" SET must_change_password = true WHERE id = $1`, cceoUserID); err != nil {
			t.Fatalf("set must_change_password: %v", err)
		}
		acctClient := identityv1connect.NewAccountServiceClient(http.DefaultClient, srv.URL)
		pwReq := connect.NewRequest(&identityv1.SetNewPasswordRequest{
			Password: "NewStrong!Password2026",
			Confirm:  "NewStrong!Password2026",
		})
		pwReq.Header().Set("Authorization", "Bearer "+cceoToken)
		if _, err := acctClient.SetNewPassword(ctx, pwReq); err != nil {
			t.Fatalf("AccountService.SetNewPassword failed: %v", err)
		}
		var stillMustChange bool
		if err := admin.QueryRow(ctx, `SELECT must_change_password FROM "user" WHERE id = $1`, cceoUserID).Scan(&stillMustChange); err != nil || stillMustChange {
			t.Fatalf("expected must_change_password cleared after SetNewPassword, got %v err=%v", stillMustChange, err)
		}
	})

	// ── 2. Batch 19: Native Exports HTTP + Connect GetExport ────────────────
	t.Run("native_exports_http_and_connect", func(t *testing.T) {
		createRes := doAuthJSON(t, srv.URL+"/api/v1/exports", cceoToken, map[string]any{
			"kind": "school_directory",
		})
		if createRes.StatusCode != http.StatusCreated {
			t.Fatalf("POST /api/v1/exports expected 201, got %d: %s", createRes.StatusCode, createRes.Body)
		}
		var created struct {
			ID          string `json:"id"`
			Status      string `json:"status"`
			DownloadURL string `json:"download_url"`
			RowCount    int    `json:"row_count"`
		}
		if err := json.Unmarshal([]byte(createRes.Body), &created); err != nil || created.ID == "" || created.RowCount == 0 {
			t.Fatalf("unexpected export response: %s", createRes.Body)
		}

		// Connect RPC ExportService.GetExport returns ready status natively.
		expClient := screensv1connect.NewExportServiceClient(http.DefaultClient, srv.URL)
		getReq := connect.NewRequest(&screensv1.GetExportRequest{JobId: created.ID})
		getReq.Header().Set("Authorization", "Bearer "+cceoToken)
		getResp, err := expClient.GetExport(ctx, getReq)
		if err != nil {
			t.Fatalf("ExportService.GetExport failed: %v", err)
		}
		if getResp.Msg.GetStatus() != "ready" || !strings.Contains(getResp.Msg.GetDownloadUrl(), created.ID) {
			t.Fatalf("unexpected GetExport response: %+v", getResp.Msg)
		}

		// Owner download succeeds with CSV content.
		dlReq, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+created.DownloadURL, nil)
		dlReq.Header.Set("Authorization", "Bearer "+cceoToken)
		dlRes, err := http.DefaultClient.Do(dlReq)
		if err != nil {
			t.Fatalf("GET export download failed: %v", err)
		}
		csvBytes, _ := io.ReadAll(dlRes.Body)
		dlRes.Body.Close()
		if dlRes.StatusCode != http.StatusOK || !strings.HasPrefix(string(csvBytes), "edify_school_id,record_id,school_name,district,sub_region,cluster,school_type,operational_status,enrollment") {
			t.Fatalf("unexpected download status=%d body=%q", dlRes.StatusCode, string(csvBytes[:min(len(csvBytes), 80)]))
		}

		// Another non-Admin user is refused (403).
		otherReq, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+created.DownloadURL, nil)
		otherReq.Header.Set("Authorization", "Bearer "+pl1Token)
		otherRes, err := http.DefaultClient.Do(otherReq)
		if err != nil {
			t.Fatalf("other user download check failed: %v", err)
		}
		otherRes.Body.Close()
		if otherRes.StatusCode != http.StatusForbidden {
			t.Fatalf("expected 403 for unrelated user export download, got %d", otherRes.StatusCode)
		}
	})

	// ── 3. Batch 21: FieldOps, FinanceOps & WorkforceOps via HTTP & SaveDrawer ─
	t.Run("ops_wired_http_and_savedrawer", func(t *testing.T) {
		// 3a. WorkforceOps profile update via SaveDrawer.
		drawerClient := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, srv.URL)
		profReq := connect.NewRequest(&screensv1.SaveDrawerRequest{
			Path:   "/profile/edit",
			Values: map[string]string{"name": origName, "phone": "+256700112233"},
		})
		profReq.Header().Set("Authorization", "Bearer "+cceoToken)
		profResp, err := drawerClient.SaveDrawer(ctx, profReq)
		if err != nil || !profResp.Msg.GetSaved() {
			t.Fatalf("SaveDrawer /profile/edit failed: resp=%+v err=%v", profResp, err)
		}

		// 3b. FinanceOps: create weekly fund request via HTTP, approve via PL SaveDrawer.
		weekStart := "2027-09-06"
		weekEnd := "2027-09-12"
		t.Cleanup(func() {
			_, _ = admin.Exec(context.Background(), `DELETE FROM weekly_fund_request WHERE responsible_user = $1 AND week_start_date = $2::date`, cceoUserID, weekStart)
		})
		finRes := doAuthJSON(t, srv.URL+"/api/v1/ops/weekly-requests", cceoToken, map[string]any{
			"fy":             "FY2027",
			"week_start":     weekStart,
			"week_end":       weekEnd,
			"total_amount":   125000,
			"funding_source": "core_budget",
		})
		if finRes.StatusCode != http.StatusCreated {
			t.Fatalf("POST /api/v1/ops/weekly-requests expected 201, got %d: %s", finRes.StatusCode, finRes.Body)
		}
		var finCreated struct {
			ID string `json:"id"`
		}
		_ = json.Unmarshal([]byte(finRes.Body), &finCreated)
		if finCreated.ID == "" {
			t.Fatalf("expected weekly request id, got %s", finRes.Body)
		}
		// Approve via PL SaveDrawer.
		plApprove := connect.NewRequest(&screensv1.SaveDrawerRequest{
			Path:   "/finance/weekly-requests/" + finCreated.ID + "/approve_pl",
			Values: map[string]string{},
		})
		plApprove.Header().Set("Authorization", "Bearer "+pl1Token)
		plResp, err := drawerClient.SaveDrawer(ctx, plApprove)
		if err != nil || !plResp.Msg.GetSaved() {
			t.Fatalf("SaveDrawer approve_pl failed: resp=%+v err=%v", plResp, err)
		}

		// 3c. FieldOps: upload evidence via HTTP, authorize read, IA verify via SaveDrawer.
		var actID, origRespStaff, origStatus, origIA string
		if err := admin.QueryRow(ctx, `
SELECT id, COALESCE(responsible_staff_id, ''), status, ia_verification_status
  FROM activity WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 1`).Scan(&actID, &origRespStaff, &origStatus, &origIA); err != nil {
			t.Fatalf("find seeded activity: %v", err)
		}
		if _, err := admin.Exec(ctx, `UPDATE activity SET responsible_staff_id = $2 WHERE id = $1`, actID, cceoStaffID); err != nil {
			t.Fatalf("assign activity to cceo: %v", err)
		}
		t.Cleanup(func() {
			_, _ = admin.Exec(context.Background(), `
UPDATE activity SET responsible_staff_id = NULLIF($2, ''), status = $3, ia_verification_status = $4 WHERE id = $1`,
				actID, origRespStaff, origStatus, origIA)
		})
		evRes := doAuthJSON(t, srv.URL+"/api/v1/ops/evidence", cceoToken, map[string]any{
			"activity_id":   actID,
			"kind":          "visit_form",
			"uri":           "https://storage.example.test/b21-evidence.pdf",
			"original_name": "visit.pdf",
			"mime_type":     "application/pdf",
			"extension":     "pdf",
			"file_size":     4096,
			"provider":      "s3",
			"notes":         "Batch 21 gateway test",
		})
		if evRes.StatusCode != http.StatusCreated {
			t.Fatalf("POST /api/v1/ops/evidence expected 201, got %d: %s", evRes.StatusCode, evRes.Body)
		}
		var evCreated struct {
			ID string `json:"id"`
		}
		_ = json.Unmarshal([]byte(evRes.Body), &evCreated)
		t.Cleanup(func() {
			_, _ = admin.Exec(context.Background(), `DELETE FROM evidence_record WHERE id = $1`, evCreated.ID)
		})
		authReq, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/api/v1/ops/evidence/"+evCreated.ID+"/authorize", nil)
		authReq.Header.Set("Authorization", "Bearer "+cceoToken)
		authRes, err := http.DefaultClient.Do(authReq)
		if err != nil || authRes.StatusCode != http.StatusOK {
			t.Fatalf("evidence authorize expected 200, got err=%v res=%+v", err, authRes)
		}
		authRes.Body.Close()

		// IA verify via SaveDrawer.
		iaReq := connect.NewRequest(&screensv1.SaveDrawerRequest{
			Path:   "/ia/verification/" + actID + "/decide",
			Values: map[string]string{"decision": "verified", "note": "Verified in Batch 21"},
		})
		iaReq.Header().Set("Authorization", "Bearer "+iaToken)
		iaResp, err := drawerClient.SaveDrawer(ctx, iaReq)
		if err != nil || !iaResp.Msg.GetSaved() {
			t.Fatalf("SaveDrawer IA verify failed: resp=%+v err=%v", iaResp, err)
		}
	})

	// ── 4. Batch 20: Newly Ported Scheduler Jobs Under Controlled Clock ─────
	t.Run("batch20_scheduler_jobs", func(t *testing.T) {
		simNow := time.Date(2027, 8, 3, 4, 0, 0, 0, time.UTC) // 07:00 EAT Tuesday
		tplID := "tpl_b20_test"
		mwiDate := "2027-08-03"
		_, err := admin.Exec(ctx, `
INSERT INTO admin_maintenance_template (
  created_at, updated_at, id, name, category, description,
  frequency_days, next_due_date, owner_id, estimated_minutes, steps, active
) VALUES (
  $1, $1, $2, 'Batch 20 Weekly DB Health Check', 'database', 'Verify vacuum and indexes',
  7, $3::date, $4, 15, '[]'::jsonb, true
) ON CONFLICT (id) DO UPDATE SET next_due_date = EXCLUDED.next_due_date, active = true`,
			simNow, tplID, mwiDate, cceoUserID)
		if err != nil {
			t.Fatalf("seed maintenance template: %v", err)
		}
		t.Cleanup(func() {
			_, _ = admin.Exec(context.Background(), `DELETE FROM admin_ops_work_item WHERE title = 'Batch 20 Weekly DB Health Check'`)
			_, _ = admin.Exec(context.Background(), `DELETE FROM admin_maintenance_template WHERE id = $1`, tplID)
			_, _ = admin.Exec(context.Background(), `DELETE FROM monthly_work_plan_budget WHERE month_key = '2027-09' AND country_id = 'UG'`)
			_, _ = admin.Exec(context.Background(), `DELETE FROM scheduled_job_execution WHERE runner = 'batch20-test'`)
		})

		jobs := scheduler.BuildUgandaJobsWithClock(gateway, func() time.Time { return simNow }, "batch20-test")
		byName := map[string]scheduler.Job{}
		for _, j := range jobs {
			byName[j.Name] = j
		}
		for _, name := range []string{
			"admin_maintenance_generation",
			"hand_in_entered_work",
			"weekly_fund_request",
			"monthly_work_plan",
			"document_lifecycle",
			"daily_plan_notifications",
			"daily_digest",
			"day_off_alerts",
			"pd_reminders",
			"daily_debrief_reminders",
			"ia_verification_digest",
			"scheduler_watchdog",
		} {
			if err := byName[name].Run(ctx); err != nil {
				t.Fatalf("scheduler job %s failed: %v", name, err)
			}
		}

		// Verify maintenance item created and template advanced +7 days.
		var itemCount int
		var nextDue string
		if err := admin.QueryRow(ctx, `SELECT COUNT(*) FROM admin_ops_work_item WHERE title = 'Batch 20 Weekly DB Health Check'`).Scan(&itemCount); err != nil || itemCount != 1 {
			t.Fatalf("expected 1 maintenance work item, got %d err=%v", itemCount, err)
		}
		if err := admin.QueryRow(ctx, `SELECT next_due_date::text FROM admin_maintenance_template WHERE id = $1`, tplID).Scan(&nextDue); err != nil || nextDue != "2027-08-10" {
			t.Fatalf("expected next_due_date=2027-08-10, got %q err=%v", nextDue, err)
		}
		// Re-running is idempotent (no second item created).
		if err := byName["admin_maintenance_generation"].Run(ctx); err != nil {
			t.Fatalf("re-run maintenance failed: %v", err)
		}
		if err := admin.QueryRow(ctx, `SELECT COUNT(*) FROM admin_ops_work_item WHERE title = 'Batch 20 Weekly DB Health Check'`).Scan(&itemCount); err != nil || itemCount != 1 {
			t.Fatalf("re-run should stay idempotent at 1 item, got %d", itemCount)
		}

		// Verify monthly_work_plan created draft for 2027-09.
		var mbStatus string
		if err := admin.QueryRow(ctx, `SELECT status FROM monthly_work_plan_budget WHERE country_id = 'UG' AND month_key = '2027-09'`).Scan(&mbStatus); err != nil || mbStatus != "draft" {
			t.Fatalf("expected draft monthly budget for 2027-09, got %q err=%v", mbStatus, err)
		}
	})

	if total := screens.GlobalFallbackTracker().Total(); total != 0 {
		t.Fatalf("expected 0 Django fallback attempts, got %d", total)
	}
}

type authHTTPResp struct {
	StatusCode int
	Body       string
}

func doAuthJSON(t *testing.T, url, token string, body any) authHTTPResp {
	t.Helper()
	raw, _ := json.Marshal(body)
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(raw))
	if err != nil {
		t.Fatalf("build request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("POST %s failed: %v", url, err)
	}
	defer res.Body.Close()
	b, _ := io.ReadAll(res.Body)
	return authHTTPResp{StatusCode: res.StatusCode, Body: string(b)}
}
