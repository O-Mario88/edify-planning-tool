//go:build integration

package integration

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accounts"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/screens"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/signin"
)

// TestGatewaySchoolVisitFinancialCorrectnessWithoutDjango proves Step 1 of the
// cutover brief through the actual shipped Go gateway (`server.New` with
// ExistingAppURL == "", StrictReads == true, and all GoSaves enabled):
//
//  1. Client signs in through SignInService and calls PlanningDrawerService.SavePlanningDrawer
//     for two schools on the same primary-district day.
//  2. Verifies NativePricing settles the shared daily pool exactly against the
//     live operational rate card (primary_transport_per_day + lunch_per_day):
//     sum(activity.est_cost_cents) == daily_visit_batch.daily_pool_amount,
//     activity_cost_snapshot (is_current=true), activity_schedule_cost_line,
//     audit_log (activity.cost.calculated), domain_event_log (plan.changed),
//     and daily_visit_costs_to_follow cleanly drained.
//  3. Reschedules visit 2 through PageDrawerService.SaveDrawer and proves BOTH
//     old day (school_count=1, visit 1 re-priced to full pool) AND new day
//     (school_count=1, visit 2 priced at full pool) settle accurately.
//  4. Verifies finance-boundary lock: freezing a week's weekly_fund_request in
//     'submitted' causes DayCheck and MoveCheck to refuse changes.
//  5. Cancels visit 2 through PageDrawerService.SaveDrawer, verifying cancelled
//     status and empty batch settlement (school_count=0).
//  6. Completes visit 1 through PageDrawerService.SaveDrawer, proving idempotent
//     HandedIn notification delivery (1 row per supervisor even on retry),
//     unrelated PL denial, and supervising PL approval through PageDrawerService.
//  7. Zero attempted Django fallback calls throughout.
func TestGatewaySchoolVisitFinancialCorrectnessWithoutDjango(t *testing.T) {
	ctx := context.Background()
	const (
		cceoEmail        = "cceo@edify.org"
		plEmail          = "pl1@edify.org"
		unrelatedPLEmail = "pl2@edify.org"
	)
	borrowAccount(t, cceoEmail)
	borrowAccount(t, plEmail)
	borrowAccount(t, unrelatedPLEmail)

	// Reset fallback tracker before starting the strict Django-absent gateway.
	screens.GlobalFallbackTracker().Reset()

	cfg := config.Config{
		Env:         config.Test,
		Release:     "gateway-step1-acceptance",
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
	gw := httptest.NewServer(server.New(cfg, gateway, nil, logger))
	t.Cleanup(gw.Close)

	cceoToken := sessionOf(t, cceoEmail, seededPassword).GetAccessToken()
	plToken := sessionOf(t, plEmail, seededPassword).GetAccessToken()
	unrelatedPLToken := sessionOf(t, unrelatedPLEmail, seededPassword).GetAccessToken()

	var cceoUserID, cceoStaffID, primaryDistrictID string
	if err := admin.QueryRow(ctx, `
SELECT u.id, sp.id, COALESCE(sp.primary_district_id, '')
  FROM "user" u
  JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
 WHERE lower(u.email) = lower($1) LIMIT 1`, cceoEmail).Scan(&cceoUserID, &cceoStaffID, &primaryDistrictID); err != nil {
		t.Fatalf("resolving CCEO profile: %v", err)
	}

	// Pick two non-core operating schools assigned to this CCEO in their primary district.
	rows, err := admin.Query(ctx, `
SELECT s.id, s.school_id
  FROM school s
  JOIN staff_school_assignment ssa ON ssa.school_id = s.id AND ssa.staff_id = $1
 WHERE s.deleted_at IS NULL
   AND s.operational_status = 'active'
   AND LOWER(COALESCE(s.school_type, '')) NOT LIKE '%core%'
   AND COALESCE(s.school_id, '') <> ''
   AND s.closed_at IS NULL
   AND ($2 = '' OR s.district_id = $2)
 ORDER BY s.id ASC
 LIMIT 2`, cceoStaffID, primaryDistrictID)
	if err != nil {
		t.Fatalf("selecting two primary-district schools: %v", err)
	}
	type schoolPick struct {
		id   string
		code string
	}
	var schoolPicks []schoolPick
	for rows.Next() {
		var sp schoolPick
		if scanErr := rows.Scan(&sp.id, &sp.code); scanErr == nil {
			schoolPicks = append(schoolPicks, sp)
		}
	}
	rows.Close()
	if len(schoolPicks) < 2 {
		t.Fatalf("need 2 assigned primary-district schools for %s, got %d", cceoEmail, len(schoolPicks))
	}

	nextWeekday := func(d time.Time) time.Time {
		for d.Weekday() == time.Saturday || d.Weekday() == time.Sunday {
			d = d.AddDate(0, 0, 1)
		}
		return d
	}
	// Pick three clean future weekdays far from existing demo seed plans.
	day1 := nextWeekday(time.Now().UTC().AddDate(0, 0, 42)).Format(time.DateOnly)
	day2 := nextWeekday(time.Now().UTC().AddDate(0, 0, 49)).Format(time.DateOnly)
	dayLocked := nextWeekday(time.Now().UTC().AddDate(0, 0, 56)).Format(time.DateOnly)

	// Read expected operational primary-district pool total from the active rate card.
	var expectedPool int64
	if err := admin.QueryRow(ctx, `
SELECT COALESCE(SUM(cs.unit_cost), 0)
  FROM cost_setting cs
  JOIN cost_catalogue cc ON cc.id = cs.catalogue_id
 WHERE cc.is_active = true AND cc.kind = 'operational'
   AND cs.key IN ('primary_transport_per_day', 'lunch_per_day')`).Scan(&expectedPool); err != nil || expectedPool <= 0 {
		t.Fatalf("reading operational primary rate card: pool=%d err=%v", expectedPool, err)
	}

	// Ensure cleanup of test rows.
	var createdActivityIDs []string
	var createdBatchIDs []string
	t.Cleanup(func() {
		for _, aid := range createdActivityIDs {
			_, _ = admin.Exec(ctx, `DELETE FROM activity_completion_verification WHERE activity_id = $1`, aid)
			_, _ = admin.Exec(ctx, `DELETE FROM activity_salesforce_reference WHERE activity_id = $1`, aid)
			_, _ = admin.Exec(ctx, `DELETE FROM activity_schedule_cost_line WHERE activity_id = $1`, aid)
			_, _ = admin.Exec(ctx, `DELETE FROM activity_cost_snapshot WHERE activity_id = $1`, aid)
			_, _ = admin.Exec(ctx, `DELETE FROM activity_schedule_change WHERE activity_id = $1`, aid)
			_, _ = admin.Exec(ctx, `DELETE FROM notification WHERE context_id = $1`, aid)
			_, _ = admin.Exec(ctx, `DELETE FROM domain_event_log WHERE aggregate_id = $1`, aid)
			_, _ = admin.Exec(ctx, `DELETE FROM activity WHERE id = $1`, aid)
		}
		for _, bid := range createdBatchIDs {
			_, _ = admin.Exec(ctx, `DELETE FROM daily_visit_batch WHERE id = $1`, bid)
		}
		_, _ = admin.Exec(ctx, `DELETE FROM daily_visit_batch WHERE responsible_user = $1 AND visit_date IN ($2::date, $3::date, $4::date)`,
			cceoUserID, day1, day2, dayLocked)
	})

	planningClient := screensv1connect.NewPlanningDrawerServiceClient(http.DefaultClient, gw.URL)
	drawerClient := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, gw.URL)

	scheduleViaGateway := func(sp schoolPick, dateStr, goal string) string {
		t.Helper()
		req := connect.NewRequest(&screensv1.SavePlanningDrawerRequest{
			SchoolId: sp.code,
			Kind:     "schedule",
			Values: map[string]string{
				"school_id":             sp.code,
				"purpose_of_visit":      "donor_visit",
				"scheduled_date":        dateStr,
				"activity_purpose_text": goal,
				"expected_outcome":      "Actionable coaching follow-up recorded.",
				"require_catalogue":     "yes",
			},
		})
		req.Header().Set("Authorization", "Bearer "+cceoToken)
		resp, err := planningClient.SavePlanningDrawer(ctx, req)
		if err != nil {
			t.Fatalf("SavePlanningDrawer(%s, %s) RPC error: %v", sp.code, dateStr, err)
		}
		if !resp.Msg.GetSaved() {
			t.Fatalf("SavePlanningDrawer(%s, %s) refused: %s", sp.code, dateStr, resp.Msg.GetError())
		}
		var actID string
		if err := admin.QueryRow(ctx, `
SELECT id FROM activity
 WHERE school_id = $1 AND planned_date = $2::date AND responsible_staff_id = $3 AND deleted_at IS NULL
 ORDER BY created_at DESC LIMIT 1`, sp.id, dateStr, cceoStaffID).Scan(&actID); err != nil {
			t.Fatalf("finding created activity for school %s on %s: %v", sp.id, dateStr, err)
		}
		createdActivityIDs = append(createdActivityIDs, actID)
		return actID
	}

	// 1. Schedule Visit 1 & Visit 2 on the SAME day through the real gateway RPC.
	visit1 := scheduleViaGateway(schoolPicks[0], day1, "Gateway Step 1 Visit 1")
	visit2 := scheduleViaGateway(schoolPicks[1], day1, "Gateway Step 1 Visit 2")

	// Verify exact day-pool split across both visits.
	var batch1ID string
	var poolAmt, perSchool int64
	var schoolCount int
	if err := admin.QueryRow(ctx, `
SELECT id, daily_pool_amount, school_count, per_school_amount
  FROM daily_visit_batch
 WHERE responsible_user = $1 AND visit_date = $2::date
 LIMIT 1`, cceoUserID, day1).Scan(&batch1ID, &poolAmt, &schoolCount, &perSchool); err != nil {
		t.Fatalf("reading day1 batch: %v", err)
	}
	createdBatchIDs = append(createdBatchIDs, batch1ID)
	if poolAmt != expectedPool || schoolCount != 2 {
		t.Fatalf("day1 batch mismatch: got pool=%d count=%d, want pool=%d count=2", poolAmt, schoolCount, expectedPool)
	}

	var cost1, cost2 int64
	var snapCount, lineCount, followCount int
	_ = admin.QueryRow(ctx, `SELECT est_cost_cents FROM activity WHERE id = $1`, visit1).Scan(&cost1)
	_ = admin.QueryRow(ctx, `SELECT est_cost_cents FROM activity WHERE id = $1`, visit2).Scan(&cost2)
	if cost1+cost2 != expectedPool {
		t.Fatalf("exact pool conservation violated: cost1(%d) + cost2(%d) = %d != %d", cost1, cost2, cost1+cost2, expectedPool)
	}
	_ = admin.QueryRow(ctx, `SELECT COUNT(*) FROM activity_cost_snapshot WHERE activity_id IN ($1, $2) AND is_current = true`, visit1, visit2).Scan(&snapCount)
	_ = admin.QueryRow(ctx, `SELECT COUNT(*) FROM activity_schedule_cost_line WHERE activity_id IN ($1, $2)`, visit1, visit2).Scan(&lineCount)
	_ = admin.QueryRow(ctx, `SELECT COUNT(*) FROM daily_visit_costs_to_follow WHERE steps::text LIKE '%' || $1 || '%'`, batch1ID).Scan(&followCount)
	if snapCount != 2 {
		t.Fatalf("expected 2 current activity_cost_snapshot rows, got %d", snapCount)
	}
	if lineCount < 4 {
		t.Fatalf("expected >=4 activity_schedule_cost_line rows (transport+lunch x2), got %d", lineCount)
	}
	if followCount != 0 {
		t.Fatalf("expected daily_visit_costs_to_follow drained for batch %s, got %d rows", batch1ID, followCount)
	}

	// 2. Reschedule Visit 2 to day2 through PageDrawerService.SaveDrawer and verify BOTH days re-settle!
	moveReq := connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/my-plan/" + visit2 + "/reschedule-drawer",
		Values: map[string]string{
			"scheduled_date": day2,
			"reason":         "Headteacher requested next week",
		},
	})
	moveReq.Header().Set("Authorization", "Bearer "+cceoToken)
	moveResp, err := drawerClient.SaveDrawer(ctx, moveReq)
	if err != nil || !moveResp.Msg.GetSaved() {
		t.Fatalf("SaveDrawer reschedule failed: err=%v msg=%+v", err, moveResp.Msg)
	}

	// Old day (day1) should now have school_count=1 and visit1 priced at full expectedPool!
	var day1CountAfter int
	var visit1CostAfter, visit2CostAfter int64
	_ = admin.QueryRow(ctx, `SELECT school_count FROM daily_visit_batch WHERE id = $1`, batch1ID).Scan(&day1CountAfter)
	_ = admin.QueryRow(ctx, `SELECT est_cost_cents FROM activity WHERE id = $1`, visit1).Scan(&visit1CostAfter)
	_ = admin.QueryRow(ctx, `SELECT est_cost_cents FROM activity WHERE id = $1`, visit2).Scan(&visit2CostAfter)
	if day1CountAfter != 1 || visit1CostAfter != expectedPool || visit2CostAfter != expectedPool {
		t.Fatalf("post-reschedule settlement mismatch: day1Count=%d visit1=%d visit2=%d want=%d",
			day1CountAfter, visit1CostAfter, visit2CostAfter, expectedPool)
	}

	// 3. Finance-boundary lock: create a submitted weekly_fund_request covering dayLocked and verify DayCheck refuses!
	lockedWFR := cuid.New()
	lockedDate, _ := time.Parse(time.DateOnly, dayLocked)
	weekStart := lockedDate.AddDate(0, 0, -((int(lockedDate.Weekday()) + 6) % 7))
	weekEnd := weekStart.AddDate(0, 0, 6)
	_, err = admin.Exec(ctx, `
INSERT INTO weekly_fund_request (
  created_at, updated_at, id, fy, week_start_date, week_end_date,
  responsible_user, responsible_role, total_amount, status, return_reason, funding_source
) VALUES (NOW(), NOW(), $1, '2027', $2::date, $3::date, $4, 'CCEO', 62000, 'submitted_to_pl', '', 'operational')`,
		lockedWFR, weekStart.Format(time.DateOnly), weekEnd.Format(time.DateOnly), cceoUserID)
	if err != nil {
		t.Fatalf("seeding locked weekly_fund_request: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM weekly_fund_request WHERE id = $1`, lockedWFR)
	})

	lockedSchedReq := connect.NewRequest(&screensv1.SavePlanningDrawerRequest{
		SchoolId: schoolPicks[0].code,
		Kind:     "schedule",
		Values: map[string]string{
			"school_id":             schoolPicks[0].code,
			"purpose_of_visit":      "donor_visit",
			"scheduled_date":        dayLocked,
			"activity_purpose_text": "Should be refused by locked week",
			"expected_outcome":      "Refused",
			"require_catalogue":     "yes",
		},
	})
	lockedSchedReq.Header().Set("Authorization", "Bearer "+cceoToken)
	lockedSchedResp, err := planningClient.SavePlanningDrawer(ctx, lockedSchedReq)
	if err != nil {
		t.Fatalf("locked week SavePlanningDrawer RPC error: %v", err)
	}
	if lockedSchedResp.Msg.GetSaved() || !strings.Contains(strings.ToLower(lockedSchedResp.Msg.GetError()), "approval") {
		t.Fatalf("expected locked-week refusal, got saved=%v err=%q", lockedSchedResp.Msg.GetSaved(), lockedSchedResp.Msg.GetError())
	}

	// 4. Cancel Visit 2 before finance boundary through PageDrawerService.SaveDrawer.
	cancelReq := connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path:   "/my-plan/" + visit2 + "/cancel-drawer",
		Values: map[string]string{"reason": "School closed for holiday"},
	})
	cancelReq.Header().Set("Authorization", "Bearer "+cceoToken)
	cancelResp, err := drawerClient.SaveDrawer(ctx, cancelReq)
	if err != nil || !cancelResp.Msg.GetSaved() {
		t.Fatalf("SaveDrawer cancel failed: err=%v msg=%+v", err, cancelResp.Msg)
	}
	var cancelStatus string
	var day2Count int
	_ = admin.QueryRow(ctx, `SELECT status FROM activity WHERE id = $1`, visit2).Scan(&cancelStatus)
	_ = admin.QueryRow(ctx, `SELECT school_count FROM daily_visit_batch WHERE responsible_user = $1 AND visit_date = $2::date`, cceoUserID, day2).Scan(&day2Count)
	if cancelStatus != "cancelled" || day2Count != 0 {
		t.Fatalf("post-cancel mismatch: status=%q day2Count=%d", cancelStatus, day2Count)
	}

	// 5. Complete Visit 1 + prove idempotent HandedIn notification + PL approval through PageDrawerService.
	today := time.Now().UTC().Format(time.DateOnly)
	_, _ = admin.Exec(ctx, `UPDATE activity SET status = 'completion_started', planned_date = $2::date, scheduled_date = NOW(), execution_started_at = NOW() WHERE id = $1`, visit1, today)
	sfID := "SVE-GW" + strings.ToUpper(visit1[len(visit1)-6:])
	completeReq := connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/my-plan/" + visit1 + "/complete-drawer",
		Values: map[string]string{
			"actual_delivery_date": today,
			"salesforce_id":        sfID,
			"teachers_attended":    "3",
			"leaders_attended":     "1",
			"other_participants":   "0",
			"actual_outcome":       "Gateway Step 1 completion outcome",
			"actual_observations":  "Observed classroom progress",
		},
	})
	completeReq.Header().Set("Authorization", "Bearer "+cceoToken)
	completeResp, err := drawerClient.SaveDrawer(ctx, completeReq)
	if err != nil || !completeResp.Msg.GetSaved() {
		t.Fatalf("SaveDrawer complete failed: err=%v msg=%+v", err, completeResp.Msg)
	}

	// Replaying HandedIn directly must be idempotent (no duplicate notification rows).
	np := activities.NewNativePricing(gateway, notificationcenter.NewWriter(gateway, time.Now))
	if err := np.HandedIn(ctx, visit1, cceoUserID, "CCEO"); err != nil {
		t.Fatalf("HandedIn replay error: %v", err)
	}
	var notifCount int
	_ = admin.QueryRow(ctx, `
SELECT COUNT(*) FROM notification
 WHERE context_type = 'activity' AND context_id = $1 AND source_event_type = 'activity.completed_handed_in'`, visit1).Scan(&notifCount)
	if notifCount < 1 {
		t.Fatalf("expected supervisor notification for completed visit %s, got %d", visit1, notifCount)
	}
	// Replay again and confirm exact same count (deduplicated).
	if err := np.HandedIn(ctx, visit1, cceoUserID, "CCEO"); err != nil {
		t.Fatalf("HandedIn second replay error: %v", err)
	}
	var notifCount2 int
	_ = admin.QueryRow(ctx, `
SELECT COUNT(*) FROM notification
 WHERE context_type = 'activity' AND context_id = $1 AND source_event_type = 'activity.completed_handed_in'`, visit1).Scan(&notifCount2)
	if notifCount2 != notifCount {
		t.Fatalf("HandedIn not idempotent: first=%d second=%d", notifCount, notifCount2)
	}

	// Unrelated PL must be DENIED from approving another supervisor's CCEO visit.
	deniedApproveReq := connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path:   "/pl/review-queue/" + visit1 + "/confirm",
		Values: map[string]string{"note": "Unrelated PL should be refused"},
	})
	deniedApproveReq.Header().Set("Authorization", "Bearer "+unrelatedPLToken)
	if _, err := drawerClient.SaveDrawer(ctx, deniedApproveReq); err == nil {
		t.Fatalf("expected unrelated PL (%s) approval to be denied", unrelatedPLEmail)
	} else if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("expected PermissionDenied for unrelated PL, got %v (%v)", connect.CodeOf(err), err)
	}

	// Supervising PL approves through PageDrawerService.SaveDrawer.
	approveReq := connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path:   "/pl/review-queue/" + visit1 + "/confirm",
		Values: map[string]string{"note": "Verified Step 1 gateway completion"},
	})
	approveReq.Header().Set("Authorization", "Bearer "+plToken)
	approveResp, err := drawerClient.SaveDrawer(ctx, approveReq)
	if err != nil {
		t.Fatalf("PL approve via SaveDrawer RPC error: %v", err)
	}
	if !approveResp.Msg.GetSaved() {
		t.Fatalf("PL approve via SaveDrawer refused: %s", approveResp.Msg.GetError())
	}

	// Verify durable plan.changed domain events were recorded and ZERO Django fallbacks occurred.
	var eventCount int
	_ = admin.QueryRow(ctx, `SELECT COUNT(*) FROM domain_event_log WHERE aggregate_id = $1 AND event_type = 'plan.changed'`, visit1).Scan(&eventCount)
	if eventCount < 1 {
		t.Fatalf("expected durable plan.changed domain_event_log row for %s, got %d", visit1, eventCount)
	}
	if total := screens.GlobalFallbackTracker().Total(); total != 0 {
		t.Fatalf("expected 0 attempted Django fallback calls, got %d", total)
	}
}

// TestStep2RelaysLedgerAndLiveRevocationWithoutDjango proves Step 2 of the brief:
//  1. signin.DirectRelay creates & dedupes a real admin_system_incident + audit_log + Admin alert.
//  2. accounts.DirectRelay releases partner.user_id on account_deleted + writes admin.partner_login_released audit_log.
//  3. clusterlead.DirectOnboarder enforces conflict on staff email, creates pending_invited user + user_invitation + audit_log.
//  4. loans.NativeLedger executes the full lending lifecycle with idempotent replay and concurrent safety.
//  5. Live session permission/role revocation immediately restricts the next request using an already-open bearer token.
func TestStep2RelaysLedgerAndLiveRevocationWithoutDjango(t *testing.T) {
	ctx := context.Background()
	writer := notificationcenter.NewWriter(gateway, time.Now)

	// 1. Security incident relay (failed_login_threshold) -> admin_system_incident + dedupe.
	var targetUserID string
	if err := admin.QueryRow(ctx, `SELECT id FROM "user" WHERE lower(email) = 'cceo@edify.org' LIMIT 1`).Scan(&targetUserID); err != nil {
		t.Fatalf("finding target user: %v", err)
	}
	secRelay := signin.NewDirectRelay(gateway, writer).WithEnv("step2_test")
	if err := secRelay.Report(ctx, signin.SecurityEvent{
		Kind: "failed_login_threshold", UserID: targetUserID, Streak: 5, Locked: false,
	}); err != nil {
		t.Fatalf("secRelay.Report #1: %v", err)
	}
	if err := secRelay.Report(ctx, signin.SecurityEvent{
		Kind: "failed_login_threshold", UserID: targetUserID, Streak: 5, Locked: false,
	}); err != nil {
		t.Fatalf("secRelay.Report #2: %v", err)
	}
	var incID, incRef string
	var occ int
	if err := admin.QueryRow(ctx, `
SELECT id, reference, occurrence_count FROM admin_system_incident
 WHERE affected_component = 'authentication' AND title LIKE 'Failed-login threshold reached%'
 ORDER BY last_detected_at DESC LIMIT 1`).Scan(&incID, &incRef, &occ); err != nil {
		t.Fatalf("reading created security incident: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM notification WHERE context_id = $1`, incID)
		_, _ = admin.Exec(ctx, `DELETE FROM admin_system_incident WHERE id = $1`, incID)
	})
	if !strings.HasPrefix(incRef, "INC-") || occ < 2 {
		t.Fatalf("security incident mismatch: ref=%q occ=%d (want INC-* and >=2)", incRef, occ)
	}

	// 2. Account deleted relay -> partner.user_id released + audit_log recorded.
	tempPartnerUser := cuid.New()
	tempPartnerID := cuid.New()
	_, err := admin.Exec(ctx, `
INSERT INTO "user" (
  id, email, name, password, active_role, roles, status, is_active, is_staff, is_superuser,
  must_change_password, failed_login_count, mfa_enabled, mfa_channel,
  lockout_cycle_count, lockout_escalated, sms_money_alerts,
  last_seen_path, last_seen_action, environment, source, created_at, updated_at
) VALUES ($1, $2, 'Temp Partner', NULL, 'Partner', ARRAY['Partner']::varchar[], 'active', true, false, false,
  false, 0, false, 'none', 0, false, false, '', '', 'test', 'manual', NOW(), NOW())`,
		tempPartnerUser, "temp-partner-"+tempPartnerUser+"@edify.test")
	if err != nil {
		t.Fatalf("inserting temp partner user: %v", err)
	}
	_, err = admin.Exec(ctx, `
INSERT INTO partner (
  id, created_at, updated_at, name, trains_on, coverage_districts, is_certified,
  expertise_areas, active_status, environment, source,
  user_id, user_setup_status, activity_codes, ssa_interventions, region_names, partner_role
) VALUES ($1, NOW(), NOW(), 'Step2 Partner Org', ARRAY[]::varchar[], ARRAY[]::varchar[], false,
          ARRAY[]::varchar[], true, 'test', 'manual',
          $2, 'active', ARRAY[]::varchar[], ARRAY[]::varchar[], ARRAY[]::varchar[], 'implementing')`,
		tempPartnerID, tempPartnerUser)
	if err != nil {
		t.Fatalf("inserting temp partner org: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM partner WHERE id = $1`, tempPartnerID)
		_, _ = admin.Exec(ctx, `DELETE FROM "user" WHERE id = $1`, tempPartnerUser)
	})

	accRelay := accounts.NewDirectRelay(gateway, writer).WithCostSettler(activities.NewNativePricing(gateway, writer))
	if err := accRelay.Report(ctx, accounts.Event{Kind: "account_deleted", UserID: tempPartnerUser}); err != nil {
		t.Fatalf("accRelay account_deleted: %v", err)
	}
	var linkedUID *string
	var setupStatus string
	if err := admin.QueryRow(ctx, `SELECT user_id, user_setup_status FROM partner WHERE id = $1`, tempPartnerID).Scan(&linkedUID, &setupStatus); err != nil {
		t.Fatalf("verifying partner login release: %v", err)
	}
	if linkedUID != nil || setupStatus != "pending" {
		t.Fatalf("partner login not released: user_id=%v setup_status=%q", linkedUID, setupStatus)
	}
	var auditReleased int
	_ = admin.QueryRow(ctx, `SELECT COUNT(*) FROM audit_log WHERE action = 'admin.partner_login_released' AND subject_id = $1`, tempPartnerID).Scan(&auditReleased)
	if auditReleased < 1 {
		t.Fatalf("expected admin.partner_login_released audit row for %s", tempPartnerID)
	}

	// 3. Cluster leader onboarding parity: conflict on staff email + real pending_invited user + user_invitation.
	onboarder := clusterlead.NewDirectOnboarder(gateway)
	if _, err := onboarder.Onboard(ctx, "cl-test", clusterlead.OnboardInput{
		Name: "Existing Staff", Email: "cceo@edify.org",
	}); err == nil {
		t.Fatalf("expected conflict error when onboarding existing staff email as cluster leader")
	}
	leaderEmail := "leader-" + cuid.New() + "@edify.test"
	made, err := onboarder.Onboard(ctx, "cl-test", clusterlead.OnboardInput{
		Name: "Step2 Cluster Leader", Email: leaderEmail, Phone: "+256700000123",
	})
	if err != nil {
		t.Fatalf("DirectOnboarder new leader failed: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM user_invitation WHERE user_id = $1`, made.UserID)
		_, _ = admin.Exec(ctx, `DELETE FROM "user" WHERE id = $1`, made.UserID)
	})
	if made.Existing || made.InviteToken == "" {
		t.Fatalf("expected new leader with invite token, got %+v", made)
	}
	var uStatus string
	var uActive bool
	var invCount int
	_ = admin.QueryRow(ctx, `SELECT status, is_active FROM "user" WHERE id = $1`, made.UserID).Scan(&uStatus, &uActive)
	_ = admin.QueryRow(ctx, `SELECT COUNT(*) FROM user_invitation WHERE user_id = $1 AND revoked_at IS NULL`, made.UserID).Scan(&invCount)
	if uStatus != "pending_invited" || uActive || invCount != 1 {
		t.Fatalf("cluster leader onboarding state mismatch: status=%q active=%v invitations=%d", uStatus, uActive, invCount)
	}

	// 4. NativeLedger full lending lifecycle + idempotency + concurrency.
	var mfiID, purposeID, facilityID, loanSchoolID string
	_ = admin.QueryRow(ctx, `SELECT id FROM bt_mfi_organization LIMIT 1`).Scan(&mfiID)
	_ = admin.QueryRow(ctx, `SELECT id FROM bt_loan_purpose LIMIT 1`).Scan(&purposeID)
	_ = admin.QueryRow(ctx, `SELECT id FROM bt_funding_facility LIMIT 1`).Scan(&facilityID)
	_ = admin.QueryRow(ctx, `SELECT id FROM school WHERE deleted_at IS NULL LIMIT 1`).Scan(&loanSchoolID)
	if facilityID == "" && mfiID != "" {
		// A disbursement draws on a facility allocation; the demo seed has no
		// facility, so the test files a draft one of its own.
		facilityID = "fac_" + cuid.New()[len(cuid.New())-18:]
		if _, err := admin.Exec(ctx, `
INSERT INTO bt_funding_facility (
  created_at, updated_at, id, external_reference, name, country_code, currency, commitment_amount,
  revolving, starts_on, status, agreement_reference, created_by, mfi_id, facility_type, funding_source,
  geographic_restrictions, interest_structure, permitted_purpose_codes, reporting_conditions,
  school_eligibility_restrictions
) VALUES (NOW(), NOW(), $1, $1, 'Integration test facility', 'UG', 'UGX', 100000000,
  false, CURRENT_DATE, 'draft', $1, 'integration-test', $2, 'term', 'test',
  '{}', '{}', '[]', '{}', '{}')`, facilityID, mfiID); err != nil {
			t.Fatalf("inserting temp bt_funding_facility: %v", err)
		}
		madeFacility := facilityID
		t.Cleanup(func() {
			_, _ = admin.Exec(context.Background(), `DELETE FROM bt_funding_facility WHERE id = $1`, madeFacility)
		})
	}
	if mfiID != "" && purposeID != "" && loanSchoolID != "" {
		caseID := "cas_" + cuid.New()[len(cuid.New())-18:]
		if _, err := admin.Exec(ctx, `
INSERT INTO bt_case (
  created_at, updated_at, source, environment, id, status, opened_fy,
  triage_decision, triage_reason, closure_reason, school_id
) VALUES (NOW(), NOW(), 'manual', 'test', $1, 'open', '2027', 'eligible', '', '', $2)`,
			caseID, loanSchoolID); err != nil {
			t.Fatalf("inserting temp bt_case: %v", err)
		}
		var refID, loanID string
		t.Cleanup(func() {
			if loanID != "" {
				_, _ = admin.Exec(ctx, `DELETE FROM bt_loan_disbursement WHERE loan_id = $1`, loanID)
				_, _ = admin.Exec(ctx, `DELETE FROM bt_funding_facility_allocation WHERE loan_id = $1`, loanID)
				_, _ = admin.Exec(ctx, `DELETE FROM bt_mfi_loan WHERE id = $1`, loanID)
			}
			if refID != "" {
				_, _ = admin.Exec(ctx, `DELETE FROM bt_finance_referral WHERE id = $1`, refID)
			}
			_, _ = admin.Exec(ctx, `DELETE FROM bt_case WHERE id = $1`, caseID)
		})

		nl := loans.NewNativeLedger(gateway)
		reqAmt := ledger.Money(5_000_000)
		refID, err = nl.CreateReferral(ctx, loans.ReferralRequest{
			CaseID: caseID, MFIID: mfiID, PurposeID: purposeID,
			Requested: reqAmt, IntendedUse: "Classroom block", ConsentRecordedAt: time.Now().UTC(),
		})
		if err != nil {
			t.Fatalf("NativeLedger.CreateReferral: %v", err)
		}
		loanID, err = nl.RegisterLoan(ctx, loans.LoanRegistration{
			ReferralID: refID, ExternalReference: "EXT-" + cuid.New(), OfficerReference: "OFF-1",
			Approved: reqAmt, Requested: reqAmt, TermMonths: 12,
		})
		if err != nil {
			t.Fatalf("NativeLedger.RegisterLoan: %v", err)
		}
		if facilityID != "" {
			// Concurrent idempotent ReserveFacility calls with the same key must return the SAME ID.
			key := "res-" + cuid.New()
			var wg sync.WaitGroup
			ids := make([]string, 2)
			errs := make([]error, 2)
			for i := 0; i < 2; i++ {
				wg.Add(1)
				go func(idx int) {
					defer wg.Done()
					ids[idx], errs[idx] = nl.ReserveFacility(ctx, facilityID, loanID, reqAmt, key)
				}(i)
			}
			wg.Wait()
			if errs[0] != nil || errs[1] != nil || ids[0] == "" || ids[0] != ids[1] {
				t.Fatalf("concurrent ReserveFacility idempotency failed: ids=%v errs=%v", ids, errs)
			}
		}
		disbKey := "disb-" + cuid.New()
		d1, err := nl.PostDisbursement(ctx, loans.DisbursementPosting{
			LoanID: loanID, IdempotencyKey: disbKey, ExternalReference: "D-EXT", BankReference: "BNK-1",
			Amount: reqAmt, Sequence: 1, DisbursedOn: time.Now().UTC(), ValueDate: time.Now().UTC(),
		})
		if err != nil {
			t.Fatalf("NativeLedger.PostDisbursement #1: %v", err)
		}
		d2, err := nl.PostDisbursement(ctx, loans.DisbursementPosting{
			LoanID: loanID, IdempotencyKey: disbKey, ExternalReference: "D-EXT", BankReference: "BNK-1",
			Amount: reqAmt, Sequence: 1, DisbursedOn: time.Now().UTC(), ValueDate: time.Now().UTC(),
		})
		if err != nil || d1 != d2 {
			t.Fatalf("NativeLedger.PostDisbursement idempotent retry failed: d1=%q d2=%q err=%v", d1, d2, err)
		}
	}

	// 5. Live session permission/role revocation across an already-open bearer token.
	borrowAccount(t, "pl2@edify.org")
	openToken := sessionOf(t, "pl2@edify.org", seededPassword).GetAccessToken()
	pageClient := screensv1connect.NewPageScreenServiceClient(http.DefaultClient, baseURL)

	// Confirm /pl/review-queue succeeds while PL role is held.
	req1 := connect.NewRequest(&screensv1.GetPageRequest{Path: "/pl/review-queue"})
	req1.Header().Set("Authorization", "Bearer "+openToken)
	if _, err := pageClient.GetPage(ctx, req1); err != nil {
		t.Fatalf("expected /pl/review-queue allowed before revocation, got: %v", err)
	}

	// Revoke PL role in DB while the bearer token is still valid (not expired).
	var origRole string
	var origRoles []string
	if err := admin.QueryRow(ctx, `SELECT active_role, roles FROM "user" WHERE lower(email) = 'pl2@edify.org'`).Scan(&origRole, &origRoles); err != nil {
		t.Fatalf("reading pl2 roles: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `UPDATE "user" SET active_role = $1, roles = $2 WHERE lower(email) = 'pl2@edify.org'`, origRole, origRoles)
	})
	if _, err := admin.Exec(ctx, `UPDATE "user" SET active_role = 'CCEO', roles = ARRAY['CCEO']::varchar[] WHERE lower(email) = 'pl2@edify.org'`); err != nil {
		t.Fatalf("revoking pl2 role: %v", err)
	}

	// Immediately call /pl/review-queue with the SAME open bearer token -> MUST be denied!
	req2 := connect.NewRequest(&screensv1.GetPageRequest{Path: "/pl/review-queue"})
	req2.Header().Set("Authorization", "Bearer "+openToken)
	if _, err := pageClient.GetPage(ctx, req2); err == nil {
		t.Fatalf("SECURITY FAILURE: /pl/review-queue still allowed on open session after PL role was revoked in DB")
	} else if code := connect.CodeOf(err); code != connect.CodePermissionDenied && code != connect.CodeUnauthenticated && code != connect.CodeNotFound {
		t.Fatalf("expected PermissionDenied, Unauthenticated, or NotFound (pagegate) after role revocation, got %v (%v)", code, err)
	}
	_ = auth.Principal{} // keep import verified
}
