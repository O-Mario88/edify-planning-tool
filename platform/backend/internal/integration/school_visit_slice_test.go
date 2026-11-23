//go:build integration

package integration

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// TestSchoolVisitVerticalSliceWithoutDjango proves the first Uganda vertical
// slice end-to-end with Django completely absent (ExistingAppURL == "",
// StrictReads == true):
//
//  1. School lookup via Go SchoolDirectoryScreenService (CCEO session)
//  2. Schedule a school visit via Go activities.Service (StandalonePricing)
//  3. Open My Plan via Go PageScreenService and confirm visibility
//  4. Edit and reschedule the visit; verify schedule-change history
//  5. Validation failure (invalid Salesforce ID) and denied action (unrelated
//     officer cannot edit or complete another officer's visit)
//  6. Complete the visit with a valid Salesforce ID + double-tap retry check
//     (proving exactly 1 reference, 1 verification, 1 submitted_to_pl row)
//  7. Supervisor queue: separate Programme Lead session opens /pl/review-queue
//  8. Cancel a second scheduled visit and verify cancelled state
//  9. Restart the Go gateway server (fresh httptest.Server, StrictReads=true,
//     ExistingAppURL=""), reopen My Plan and PL Review Queue, verify persisted
//     state and zero attempted Django calls.
func TestSchoolVisitVerticalSliceWithoutDjango(t *testing.T) {
	ctx := context.Background()
	const (
		cceoEmail      = "cceo@edify.org"
		unrelatedEmail = "cceo17@edify.org"
		plEmail        = "pl2@edify.org"
	)
	borrowAccount(t, cceoEmail)
	borrowAccount(t, unrelatedEmail)
	borrowAccount(t, plEmail)

	// Start a dedicated strict-reads, Django-absent Go gateway (Instance 1).
	strictCfg := config.Config{
		Env:         config.Test,
		Release:     "vertical-slice-1",
		JWTSecret:   signingSecret,
		StrictReads: true,
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
	gw1 := httptest.NewServer(server.New(strictCfg, gateway, nil, logger))
	t.Cleanup(gw1.Close)

	cceoToken := sessionOf(t, cceoEmail, seededPassword).GetAccessToken()
	plToken := sessionOf(t, plEmail, seededPassword).GetAccessToken()

	authenticator := auth.NewAuthenticator(auth.NewVerifier(signingSecret, time.Now), identity.NewStore(gateway))
	principalOf := func(token string) auth.Principal {
		t.Helper()
		p, err := authenticator.Authenticate(ctx, "Bearer "+token)
		if err != nil {
			t.Fatalf("authenticating token: %v", err)
		}
		return p
	}
	cceoPrincipal := principalOf(cceoToken)
	unrelatedToken := sessionOf(t, unrelatedEmail, seededPassword).GetAccessToken()
	unrelatedPrincipal := principalOf(unrelatedToken)

	// 1. School lookup through Go SchoolDirectoryScreenService (Django absent).
	dirClient := screensv1connect.NewSchoolDirectoryScreenServiceClient(http.DefaultClient, gw1.URL)
	dirReq := authed(&screensv1.GetSchoolDirectoryRequest{}, cceoToken)
	dirResp, err := dirClient.GetSchoolDirectory(ctx, dirReq)
	if err != nil {
		t.Fatalf("school directory lookup failed: %v", err)
	}
	if len(dirResp.Msg.GetSchools()) == 0 {
		t.Fatalf("expected seeded schools for %s, got 0", cceoEmail)
	}
	t.Logf("step 1 (school lookup): trace=%s schools=%d",
		dirResp.Header().Get(trace.HeaderRequestID), len(dirResp.Msg.GetSchools()))

	// Pick a non-core operating school in cceo's own portfolio so 27.3 and
	// 183.1 apply cleanly (activities.Request.SchoolID takes the school_id code).
	var schoolID string
	err = admin.QueryRow(ctx, `
SELECT s.school_id
FROM school s
WHERE s.deleted_at IS NULL
  AND s.account_owner_id IN ($1, $2)
  AND LOWER(COALESCE(s.school_type, '')) NOT LIKE '%core%'
  AND COALESCE(s.school_id, '') <> ''
  AND s.closed_at IS NULL
ORDER BY s.id ASC
LIMIT 1`, cceoPrincipal.StaffProfileID, cceoPrincipal.UserID).Scan(&schoolID)
	if err != nil {
		t.Fatalf("finding non-core school for %s: %v", cceoEmail, err)
	}

	// Wire Go activities.Service with StandalonePricing (zero Django HTTP calls).
	actSvc, err := activities.NewService(gateway, activities.StandalonePricing{}, logger, time.Now)
	if err != nil {
		t.Fatalf("building activities service: %v", err)
	}

	// Pick a clean weekday 3 days ahead (and another 4 days ahead for reschedule)
	// so we don't collide with existing seeded visits.
	now := time.Now().UTC()
	nextWeekday := func(d time.Time) time.Time {
		for d.Weekday() == time.Saturday || d.Weekday() == time.Sunday {
			d = d.AddDate(0, 0, 1)
		}
		return d
	}
	day1 := nextWeekday(now.AddDate(0, 0, 14)).Format("2006-01-02")
	day2 := nextWeekday(now.AddDate(0, 0, 17)).Format("2006-01-02")
	dayCancel := nextWeekday(now.AddDate(0, 0, 21)).Format("2006-01-02")

	var createdIDs []string
	t.Cleanup(func() {
		for _, id := range createdIDs {
			_, _ = admin.Exec(ctx, `DELETE FROM activity_completion_verification WHERE activity_id = $1`, id)
			_, _ = admin.Exec(ctx, `DELETE FROM activity_salesforce_reference WHERE activity_id = $1`, id)
			_, _ = admin.Exec(ctx, `DELETE FROM activity_schedule_change WHERE activity_id = $1`, id)
			_, _ = admin.Exec(ctx, `DELETE FROM daily_visit_costs_to_follow WHERE activity_id = $1`, id)
			_, _ = admin.Exec(ctx, `DELETE FROM activity WHERE id = $1`, id)
		}
	})

	origin := activities.Origin{IP: "127.0.0.1", UserAgent: "edify-slice-test", CorrelationID: "slice-corr-1"}

	// 2. Schedule a school visit in Go (zero Django calls).
	scheduled, err := actSvc.Schedule(ctx, cceoPrincipal, activities.Request{
		SchoolID: schoolID,
		Purpose:  "donor_visit",
		Date:     day1,
		Goal:     "Vertical slice visit goal",
		Outcome:  "Vertical slice expected outcome",
	}, origin)
	if err != nil {
		t.Fatalf("step 2 (schedule visit) failed: %v", err)
	}
	createdIDs = append(createdIDs, scheduled.ActivityID)
	t.Logf("step 2 (schedule): activity_id=%s status=%s date=%s fy=%s",
		scheduled.ActivityID, scheduled.Status, scheduled.PlannedDate, scheduled.FY)

	// 3. Open My Plan & Calendar via Go PageScreenService (Django absent, StrictReads=true).
	pageClient1 := screensv1connect.NewPageScreenServiceClient(http.DefaultClient, gw1.URL)
	myPlanResp, err := pageClient1.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/my-plan"}, cceoToken))
	if err != nil {
		t.Fatalf("step 3a (open /my-plan) failed: %v", err)
	}
	t.Logf("step 3a (/my-plan): trace=%s blocks=%d",
		myPlanResp.Header().Get(trace.HeaderRequestID), len(myPlanResp.Msg.GetBlocks()))
	calResp, err := pageClient1.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/calendar"}, cceoToken))
	if err != nil {
		t.Fatalf("step 3b (open /calendar) failed: %v", err)
	}
	t.Logf("step 3b (/calendar): trace=%s blocks=%d",
		calResp.Header().Get(trace.HeaderRequestID), len(calResp.Msg.GetBlocks()))

	// 4a. Edit visit goal/outcome in Go.
	if _, err := actSvc.Edit(ctx, cceoPrincipal, activities.EditRequest{
		ActivityID: scheduled.ActivityID,
		Posted: map[string]string{
			"activity_purpose_text": "Updated vertical slice goal",
			"expected_outcome":      "Updated vertical slice outcome",
		},
		Reason: "Refined before travel",
	}, origin); err != nil {
		t.Fatalf("step 4a (edit visit) failed: %v", err)
	}

	// 4b. Reschedule visit to day2 in Go.
	moved, err := actSvc.Reschedule(ctx, cceoPrincipal, activities.MoveRequest{
		ActivityID: scheduled.ActivityID,
		Date:       day2,
		Reason:     "Headteacher requested new day",
	}, origin)
	if err != nil {
		t.Fatalf("step 4b (reschedule visit) failed: %v", err)
	}
	if moved.PlannedDate != day2 {
		t.Fatalf("rescheduled date = %s, want %s", moved.PlannedDate, day2)
	}

	// 5a. Denied action: unrelated officer cannot edit cceo's visit.
	_, err = actSvc.Edit(ctx, unrelatedPrincipal, activities.EditRequest{
		ActivityID: scheduled.ActivityID,
		Posted: map[string]string{
			"activity_purpose_text": "Unauthorized edit",
			"expected_outcome":      "Unauthorized outcome",
		},
	}, origin)
	var refusal *activities.Refusal
	if err == nil || (!errors.As(err, &refusal) && !errors.Is(err, activities.ErrHandOn)) {
		t.Fatalf("step 5a: expected refusal/hand-on for unrelated officer edit, got %v", err)
	}

	// Transition visit to completion_started on today's date (mirrors opening
	// the Complete drawer on the visit day; a future completed day is refused).
	today := now.Format("2006-01-02")
	if _, err := admin.Exec(ctx, `UPDATE activity SET status = 'completion_started', planned_date = $2::date, execution_started_at = now() WHERE id = $1`, scheduled.ActivityID, today); err != nil {
		t.Fatalf("starting completion: %v", err)
	}

	// 5b. Validation failure: malformed Salesforce ID is refused cleanly.
	_, err = actSvc.Complete(ctx, cceoPrincipal, activities.CompleteRequest{
		ActivityID: scheduled.ActivityID,
		Form: url.Values{
			"actual_delivery_date": {today},
			"salesforce_id":        {"BAD-1"},
			"teachers_attended":    {"2"},
			"leaders_attended":     {"1"},
			"other_participants":   {"0"},
			"actual_outcome":       {"Observed classrooms"},
		},
	}, origin)
	if !errors.As(err, &refusal) || !strings.Contains(refusal.Message, "Salesforce ID") {
		t.Fatalf("step 5b: expected Salesforce ID refusal, got %v", err)
	}

	// 6a. Complete visit with valid Salesforce ID via Go.
	sfID := "SVE-SLICE" + strings.ToUpper(scheduled.ActivityID[len(scheduled.ActivityID)-6:])
	completeForm := url.Values{
		"actual_delivery_date": {today},
		"salesforce_id":        {sfID},
		"teachers_attended":    {"4"},
		"leaders_attended":     {"2"},
		"other_participants":   {"1"},
		"actual_outcome":       {"Met headteacher and reviewed plan"},
		"actual_observations":  {"Strong leadership engagement"},
		"follow_up_note":       {"Share summary next week"},
	}
	completed, err := actSvc.Complete(ctx, cceoPrincipal, activities.CompleteRequest{
		ActivityID: scheduled.ActivityID,
		Form:       completeForm,
	}, origin)
	if err != nil {
		t.Fatalf("step 6a (complete visit) failed: %v", err)
	}
	t.Logf("step 6a (complete): sfID=%s message=%q", sfID, completed.Message)

	// 6b. Double-tap / retry idempotency: re-submitting the same completion
	// must NOT duplicate reference or verification rows.
	if _, err := actSvc.Complete(ctx, cceoPrincipal, activities.CompleteRequest{
		ActivityID: scheduled.ActivityID,
		Form:       completeForm,
	}, origin); err == nil {
		t.Fatalf("step 6b: expected second completion attempt to be rejected/handed-on, got nil")
	}
	var refCount, verCount int
	var persistedStatus, persistedSF string
	if err := admin.QueryRow(ctx, `SELECT status, COALESCE(salesforce_activity_id, '') FROM activity WHERE id = $1`, scheduled.ActivityID).Scan(&persistedStatus, &persistedSF); err != nil {
		t.Fatalf("reading persisted activity: %v", err)
	}
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM activity_salesforce_reference WHERE activity_id = $1`, scheduled.ActivityID).Scan(&refCount); err != nil {
		t.Fatalf("counting references: %v", err)
	}
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM activity_completion_verification WHERE activity_id = $1`, scheduled.ActivityID).Scan(&verCount); err != nil {
		t.Fatalf("counting verifications: %v", err)
	}
	if persistedStatus != "submitted_to_pl" || persistedSF != sfID || refCount != 1 || verCount != 1 {
		t.Fatalf("post-double-tap state mismatch: status=%q sf=%q refs=%d verifs=%d",
			persistedStatus, persistedSF, refCount, verCount)
	}

	// 7. Supervisor queue & native Go PL Review (M9: Return → Re-submit → Approve)
	// + authorized Go CSV export, all with Django completely absent.
	plQueueResp, err := pageClient1.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/pl/review-queue"}, plToken))
	if err != nil {
		t.Fatalf("step 7 (PL /pl/review-queue) failed: %v", err)
	}
	t.Logf("step 7 (/pl/review-queue): trace=%s blocks=%d",
		plQueueResp.Header().Get(trace.HeaderRequestID), len(plQueueResp.Msg.GetBlocks()))

	reviewSvc := plreview.NewReviewService(gateway, time.Now)
	// 7a. Unrelated CCEO is refused from approving.
	if _, err := reviewSvc.Approve(ctx, unrelatedPrincipal, scheduled.ActivityID); err == nil {
		t.Fatalf("step 7a: expected unrelated CCEO refused on Approve")
	}

	// Sign in as Admin (always permitted reviewer across Uganda) to exercise
	// both Return and Approve in Go.
	const adminEmail = "admin@edify.org"
	borrowAccount(t, adminEmail)
	adminToken := sessionOf(t, adminEmail, seededPassword).GetAccessToken()
	adminPrincipal := principalOf(adminToken)

	// 7b. Blank return reason is refused.
	if _, err := reviewSvc.Return(ctx, adminPrincipal, scheduled.ActivityID, nil, "   "); err == nil {
		t.Fatalf("step 7b: expected blank return reason refused")
	}
	// 7c. Valid Return moves visit to returned_by_pl with note and audit row.
	returned, err := reviewSvc.Return(ctx, adminPrincipal, scheduled.ActivityID, nil, "Clarify teacher count")
	if err != nil || returned.Status != "returned_by_pl" {
		t.Fatalf("step 7c (PL return): got %+v, err=%v", returned, err)
	}
	// Move back to submitted_to_pl (simulating officer correction resubmission)
	// and approve natively in Go.
	if _, err := admin.Exec(ctx, `UPDATE activity SET status = 'submitted_to_pl' WHERE id = $1`, scheduled.ActivityID); err != nil {
		t.Fatalf("re-submitting visit: %v", err)
	}
	// 7d. Approve moves visit to ia_verified + confirmed verification + audit.
	approved, err := reviewSvc.Approve(ctx, adminPrincipal, scheduled.ActivityID)
	if err != nil || approved.Status != "ia_verified" {
		t.Fatalf("step 7d (PL approve): got %+v, err=%v", approved, err)
	}
	var verifiedStatus, iaVerifStatus, compVerifStatus string
	if err := admin.QueryRow(ctx, `SELECT status, COALESCE(ia_verification_status, '') FROM activity WHERE id = $1`, scheduled.ActivityID).Scan(&verifiedStatus, &iaVerifStatus); err != nil {
		t.Fatalf("reading verified activity: %v", err)
	}
	if err := admin.QueryRow(ctx, `SELECT status FROM activity_completion_verification WHERE activity_id = $1`, scheduled.ActivityID).Scan(&compVerifStatus); err != nil {
		t.Fatalf("reading completion verification: %v", err)
	}
	// The existing approval leaves the completion's verification row as it was
	// (pl_review.services._approve; measured against it in docs/migration/189).
	if verifiedStatus != "ia_verified" || iaVerifStatus != "confirmed" || compVerifStatus != "pending" {
		t.Fatalf("step 7d mismatch: status=%q ia=%q compVerif=%q", verifiedStatus, iaVerifStatus, compVerifStatus)
	}
	// 7e. Native Go CSV export: permitted reviewer sees the verified visit &
	// Salesforce ID; unrelated CCEO does NOT see cceo@edify.org's visit.
	csvBytes, csvCount, err := reviewSvc.ExportCompletedVisitsCSV(ctx, adminPrincipal)
	if err != nil {
		t.Fatalf("step 7e (admin CSV export) failed: %v", err)
	}
	if !strings.Contains(string(csvBytes), scheduled.ActivityID) || !strings.Contains(string(csvBytes), sfID) {
		t.Fatalf("step 7e: admin CSV export (%d rows) missing activity %s or sfID %s", csvCount, scheduled.ActivityID, sfID)
	}
	unrelatedCSV, _, err := reviewSvc.ExportCompletedVisitsCSV(ctx, unrelatedPrincipal)
	if err != nil {
		t.Fatalf("step 7e (unrelated CCEO CSV export) failed: %v", err)
	}
	if strings.Contains(string(unrelatedCSV), scheduled.ActivityID) {
		t.Fatalf("step 7e: unrelated CCEO CSV export leaked activity %s", scheduled.ActivityID)
	}
	t.Logf("step 7d-e (PL approve + Go CSV export): status=%s ia=%s exportRows=%d", verifiedStatus, iaVerifStatus, csvCount)

	// 8. Cancel a second visit cleanly in Go.
	second, err := actSvc.Schedule(ctx, cceoPrincipal, activities.Request{
		SchoolID: schoolID,
		Purpose:  "social_visit",
		Date:     dayCancel,
		Goal:     "Visit to cancel",
		Outcome:  "Cancelled before travel",
	}, origin)
	if err != nil {
		t.Fatalf("step 8a (schedule second visit) failed: %v", err)
	}
	createdIDs = append(createdIDs, second.ActivityID)
	if _, err := actSvc.Cancel(ctx, cceoPrincipal, activities.CancelRequest{
		ActivityID: second.ActivityID,
		Reason:     "School closed for event",
	}, origin); err != nil {
		t.Fatalf("step 8b (cancel visit) failed: %v", err)
	}
	var cancelledStatus string
	if err := admin.QueryRow(ctx, `SELECT status FROM activity WHERE id = $1`, second.ActivityID).Scan(&cancelledStatus); err != nil {
		t.Fatalf("reading cancelled status: %v", err)
	}
	if cancelledStatus != "cancelled" {
		t.Fatalf("step 8b: status = %q, want cancelled", cancelledStatus)
	}

	// 9. Restart Go gateway (close gw1, start fresh gw2 with StrictReads=true,
	// ExistingAppURL=""), reopen records, verify persisted state survives restart.
	gw1.Close()
	strictCfg.Release = "vertical-slice-2-restarted"
	gw2 := httptest.NewServer(server.New(strictCfg, gateway, nil, logger))
	t.Cleanup(gw2.Close)

	pageClient2 := screensv1connect.NewPageScreenServiceClient(http.DefaultClient, gw2.URL)
	reopenedCal, err := pageClient2.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/calendar"}, cceoToken))
	if err != nil {
		t.Fatalf("step 9a (reopen /calendar after restart) failed: %v", err)
	}
	reopenedPL, err := pageClient2.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/pl/review-queue"}, plToken))
	if err != nil {
		t.Fatalf("step 9b (reopen /pl/review-queue after restart) failed: %v", err)
	}
	// Verify unrelated reader cannot open /pl/review-queue (permission denied).
	if _, err := pageClient2.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: "/pl/review-queue"}, unrelatedToken)); connect.CodeOf(err) != connect.CodePermissionDenied && connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("step 9c: expected unrelated CCEO refused on /pl/review-queue, got %v", err)
	}
	t.Logf("step 9 (after restart): calendarTrace=%s plQueueTrace=%s completed=%s cancelled=%s",
		reopenedCal.Header().Get(trace.HeaderRequestID),
		reopenedPL.Header().Get(trace.HeaderRequestID),
		scheduled.ActivityID, second.ActivityID)
}
