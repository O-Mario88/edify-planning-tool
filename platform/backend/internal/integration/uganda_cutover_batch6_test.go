//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/scheduler"
	"net/http"
)

// TestNativeNotificationsAndLeaseSchedulerWithoutDjango proves M11 native Go
// notification delivery/deduplication/read transitions and PostgreSQL
// advisory-lock scheduler leasing with zero Django calls.
func TestNativeNotificationsAndLeaseSchedulerWithoutDjango(t *testing.T) {
	ctx := context.Background()
	const email = "cceo17@edify.org"
	const otherEmail = "pl2@edify.org"
	borrowAccount(t, email)
	borrowAccount(t, otherEmail)

	authenticator := auth.NewAuthenticator(auth.NewVerifier(signingSecret, time.Now), identity.NewStore(gateway))
	ownerToken := sessionOf(t, email, seededPassword).GetAccessToken()
	otherToken := sessionOf(t, otherEmail, seededPassword).GetAccessToken()
	owner, err := authenticator.Authenticate(ctx, "Bearer "+ownerToken)
	if err != nil {
		t.Fatal(err)
	}
	other, err := authenticator.Authenticate(ctx, "Bearer "+otherToken)
	if err != nil {
		t.Fatal(err)
	}

	const sourceID = "batch6notif001"
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM notification WHERE source_event_id = $1`, sourceID)
	})

	writer := notificationcenter.NewWriter(gateway, time.Now)
	d := notificationcenter.Delivery{
		RecipientID:     owner.UserID,
		SenderID:        other.UserID,
		Title:           "Cluster follow-up due",
		Body:            "Verify attendance sheet for your cluster meeting.",
		Category:        "cluster_support",
		ContextType:     "cluster_action",
		ContextID:       "ctx-batch6",
		TargetRoute:     "/clusters",
		ActionLabel:     "Open cluster",
		ActionRequired:  true,
		Priority:        "normal",
		SourceEventType: "action.reminder",
		SourceEventID:   sourceID,
	}

	// First delivery inserts 1 row; duplicate retry deduplicates to 0 new rows.
	created1, err := writer.Deliver(ctx, d)
	if err != nil || !created1 {
		t.Fatalf("first deliver: created=%v err=%v", created1, err)
	}
	created2, err := writer.Deliver(ctx, d)
	if err != nil || created2 {
		t.Fatalf("duplicate deliver must dedupe: created=%v err=%v", created2, err)
	}

	var notifID string
	var count int
	if err := admin.QueryRow(ctx, `SELECT count(*), min(id) FROM notification WHERE source_event_id = $1`, sourceID).Scan(&count, &notifID); err != nil {
		t.Fatal(err)
	}
	if count != 1 || notifID == "" {
		t.Fatalf("expected exactly 1 notification row, got %d (%q)", count, notifID)
	}

	// Unrelated user cannot mark owner's notification read.
	changedOther, err := writer.MarkRead(ctx, notifID, other.UserID)
	if err != nil || changedOther != 0 {
		t.Fatalf("other user marked owner notification read: changed=%d err=%v", changedOther, err)
	}
	// Owner marks own notification read.
	changedOwner, err := writer.MarkRead(ctx, notifID, owner.UserID)
	if err != nil || changedOwner != 1 {
		t.Fatalf("owner mark read: changed=%d err=%v", changedOwner, err)
	}

	// Verify PostgreSQL advisory-lock single-executor lease prevents overlap.
	locker := scheduler.NewPGLocker(gateway)
	const leaseKey int64 = 9918501
	unlock1, ok1, err := locker.TryLock(ctx, leaseKey)
	if err != nil || !ok1 {
		t.Fatalf("first PG lease acquire failed: ok=%v err=%v", ok1, err)
	}
	defer unlock1(ctx)
	_, ok2, err := locker.TryLock(ctx, leaseKey)
	if err != nil || ok2 {
		t.Fatalf("second PG lease must fail while first holds lock: ok=%v err=%v", ok2, err)
	}
}

// TestUgandaMultiCountryIsolation proves a Uganda-restricted reader cannot see
// synthetic second-country (Kenya) schools or completed visits via Go's
// SchoolDirectoryScreenService or CSV export, while an Admin (positive control)
// can read across registered countries.
func TestUgandaMultiCountryIsolation(t *testing.T) {
	ctx := context.Background()
	const (
		ugandaEmail = "cceo@edify.org"
		adminEmail  = "admin@edify.org"
		keRegionID  = "cmw9batch6keregion01"
		keDistID    = "cmw9batch6kedist0001"
		keSchoolID  = "cmw9batch6keschool01"
		keSchoolNum = "KE-ISO-9901"
		keActID     = "cmw9batch6keact00001"
	)
	borrowAccount(t, ugandaEmail)
	borrowAccount(t, adminEmail)

	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM activity WHERE id = $1`, keActID)
		_, _ = admin.Exec(ctx, `DELETE FROM school WHERE id = $1`, keSchoolID)
		_, _ = admin.Exec(ctx, `DELETE FROM district WHERE id = $1`, keDistID)
		_, _ = admin.Exec(ctx, `DELETE FROM region WHERE id = $1`, keRegionID)
	})

	// Seed synthetic second-country (Kenya) geography, school, and verified visit.
	if _, err := admin.Exec(ctx, `
INSERT INTO region (id, name, country, created_at, updated_at)
VALUES ($1, 'Nairobi Synthetic', 'Kenya', now(), now())
ON CONFLICT (id) DO NOTHING`, keRegionID); err != nil {
		t.Fatalf("seeding KE region: %v", err)
	}
	if _, err := admin.Exec(ctx, `
INSERT INTO district (id, name, region_id, district_type, created_at, updated_at)
VALUES ($1, 'Westlands Synthetic', $2, 'primary', now(), now())
ON CONFLICT (id) DO NOTHING`, keDistID, keRegionID); err != nil {
		t.Fatalf("seeding KE district: %v", err)
	}
	if _, err := admin.Exec(ctx, `
INSERT INTO school
SELECT (jsonb_populate_record(s, jsonb_build_object(
  'id', $1::text, 'school_id', $2::text, 'name', 'Nairobi Synthetic Academy',
  'region_id', $3::text, 'district_id', $4::text, 'sub_county_id', NULL,
  'account_owner_id', NULL, 'cluster_id', NULL, 'deleted_at', NULL, 'closed_at', NULL
))).*
FROM school s WHERE s.deleted_at IS NULL LIMIT 1
ON CONFLICT (id) DO NOTHING`, keSchoolID, keSchoolNum, keRegionID, keDistID); err != nil {
		t.Fatalf("seeding KE school: %v", err)
	}
	if _, err := admin.Exec(ctx, `
INSERT INTO activity
SELECT (jsonb_populate_record(a, jsonb_build_object(
  'id', $1::text, 'school_id', $2::text, 'cluster_id', NULL, 'responsible_staff_id', NULL,
  'status', 'ia_verified', 'salesforce_activity_id', 'SVE-KEISO9901',
  'deleted_at', NULL, 'daily_visit_batch_id', NULL, 'paired_school_visit_id', NULL
))).*
FROM activity a WHERE a.deleted_at IS NULL LIMIT 1
ON CONFLICT (id) DO NOTHING`, keActID, keSchoolID); err != nil {
		t.Fatalf("seeding KE activity: %v", err)
	}

	ugToken := sessionOf(t, ugandaEmail, seededPassword).GetAccessToken()
	adminToken := sessionOf(t, adminEmail, seededPassword).GetAccessToken()

	dirClient := screensv1connect.NewSchoolDirectoryScreenServiceClient(http.DefaultClient, baseURL)

	// Negative control: Uganda CCEO searching for the Kenya school sees 0 rows.
	ugResp, err := dirClient.GetSchoolDirectory(ctx, authed(&screensv1.GetSchoolDirectoryRequest{Q: "Nairobi Synthetic Academy"}, ugToken))
	if err != nil {
		t.Fatalf("Uganda directory search failed: %v", err)
	}
	if len(ugResp.Msg.GetSchools()) != 0 {
		t.Fatalf("country isolation breach: Uganda CCEO saw %d Kenyan schools", len(ugResp.Msg.GetSchools()))
	}

	// Negative control: Uganda CCEO CSV export must not contain the Kenyan visit.
	authenticator := auth.NewAuthenticator(auth.NewVerifier(signingSecret, time.Now), identity.NewStore(gateway))
	ugPrincipal, err := authenticator.Authenticate(ctx, "Bearer "+ugToken)
	if err != nil {
		t.Fatal(err)
	}
	adminPrincipal, err := authenticator.Authenticate(ctx, "Bearer "+adminToken)
	if err != nil {
		t.Fatal(err)
	}
	reviewSvc := plreview.NewReviewService(gateway, time.Now)
	ugCSV, _, err := reviewSvc.ExportCompletedVisitsCSV(ctx, ugPrincipal)
	if err != nil {
		t.Fatalf("Uganda CSV export failed: %v", err)
	}
	if strings.Contains(string(ugCSV), keActID) || strings.Contains(string(ugCSV), "SVE-KEISO9901") {
		t.Fatalf("country isolation breach: Uganda CCEO CSV export leaked Kenyan visit %s", keActID)
	}

	// Positive control: Admin sees the Kenyan visit in export.
	adminCSV, _, err := reviewSvc.ExportCompletedVisitsCSV(ctx, adminPrincipal)
	if err != nil {
		t.Fatalf("Admin CSV export failed: %v", err)
	}
	if !strings.Contains(string(adminCSV), keActID) {
		t.Fatalf("positive control failed: Admin CSV export did not include synthetic Kenyan visit %s", keActID)
	}
}
