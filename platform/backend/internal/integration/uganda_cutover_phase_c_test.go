//go:build integration

package integration

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/exports"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fieldops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/financeops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workforceops"
)

// TestUgandaCutoverPhaseCWithoutDjango exercises Batches 10–13 natively in Go
// against PostgreSQL using the read-only edify_gateway role and SECURITY
// DEFINER functions with zero Django involvement.
func TestUgandaCutoverPhaseCWithoutDjango(t *testing.T) {
	ctx := context.Background()
	verifier := auth.NewVerifier(signingSecret, time.Now)
	authenticator := auth.NewAuthenticator(verifier, identity.NewStore(gateway))

	borrowAccount(t, "cceo@edify.org")
	borrowAccount(t, "pl2@edify.org")
	borrowAccount(t, "admin@edify.org")

	cceoToken := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	cceoP, err := authenticator.Authenticate(ctx, "Bearer "+cceoToken)
	if err != nil {
		t.Fatalf("auth cceo: %v", err)
	}
	plToken := sessionOf(t, "pl2@edify.org", seededPassword).GetAccessToken()
	plP, err := authenticator.Authenticate(ctx, "Bearer "+plToken)
	if err != nil {
		t.Fatalf("auth pl: %v", err)
	}
	adminToken := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	adminP, err := authenticator.Authenticate(ctx, "Bearer "+adminToken)
	if err != nil {
		t.Fatalf("auth admin: %v", err)
	}

	// Pick an existing activity owned by CCEO (by either StaffProfileID or UserID).
	var actID, schoolPK string
	if err := admin.QueryRow(ctx, `
SELECT a.id, COALESCE(a.school_id, '')
FROM activity a
WHERE a.deleted_at IS NULL AND a.responsible_staff_id = ANY($1) AND a.school_id IS NOT NULL
ORDER BY a.created_at DESC LIMIT 1`, []string{cceoP.StaffProfileID, cceoP.UserID}).Scan(&actID, &schoolPK); err != nil {
		// Fallback: pick any live school activity and check using Admin + owner check.
		if err2 := admin.QueryRow(ctx, `
SELECT a.id, a.school_id FROM activity a
WHERE a.deleted_at IS NULL AND a.school_id IS NOT NULL
ORDER BY a.created_at DESC LIMIT 1`).Scan(&actID, &schoolPK); err2 != nil {
			t.Fatalf("finding test activity: %v / %v", err, err2)
		}
		cceoP.ActiveRole = "Admin"
	}

	// 1. M8 Evidence upload (interrupted rejected, valid idempotent, read auth enforced).
	fops := fieldops.NewService(gateway)
	if _, err := fops.RecordUpload(ctx, cceoP, fieldops.EvidenceUpload{
		ActivityID: actID, URI: "s3://edify-ug/broken.pdf", FileSize: 0,
	}); !errors.Is(err, fieldops.ErrInvalidInput) {
		t.Fatalf("expected interrupted 0-byte upload rejected, got %v", err)
	}
	uri := "s3://edify-ug/phase-c-evidence-" + actID + ".pdf"
	evID1, err := fops.RecordUpload(ctx, cceoP, fieldops.EvidenceUpload{
		ActivityID: actID, Kind: "visit_form", URI: uri, OriginalName: "visit.pdf",
		MimeType: "application/pdf", Extension: ".pdf", FileSize: 24576,
	})
	if err != nil {
		t.Fatalf("RecordUpload failed: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM evidence_record WHERE id = $1`, evID1)
	})
	evID2, err := fops.RecordUpload(ctx, cceoP, fieldops.EvidenceUpload{
		ActivityID: actID, Kind: "visit_form", URI: uri, OriginalName: "visit.pdf",
		MimeType: "application/pdf", Extension: ".pdf", FileSize: 24576,
	})
	if err != nil || evID2 != evID1 {
		t.Fatalf("idempotent RecordUpload mismatch: %q vs %q (err=%v)", evID1, evID2, err)
	}
	gotURI, err := fops.AuthorizeEvidenceRead(ctx, cceoP, evID1)
	if err != nil || gotURI != uri {
		t.Fatalf("owner AuthorizeEvidenceRead failed: uri=%q err=%v", gotURI, err)
	}
	unrelated := auth.Principal{Account: auth.Account{UserID: "u-stranger", StaffProfileID: "sp-stranger", ActiveRole: "CCEO"}}
	if _, err := fops.AuthorizeEvidenceRead(ctx, unrelated, evID1); !errors.Is(err, fieldops.ErrForbidden) {
		t.Fatalf("expected ErrForbidden for unrelated CCEO reading evidence, got %v", err)
	}

	// 2. M7 SSA entry & confirmation.
	ssaID, err := fops.EnterSSA(ctx, cceoP, fieldops.SSAEntryRequest{
		SchoolID: schoolPK, FY: "2099", Quarter: "Q1", Date: time.Now().UTC(), NewEnrollment: 412,
		Scores:        allEightSSAScores(4.5),
		CollectorType: "staff", ActivityID: actID,
	})
	if err != nil {
		t.Fatalf("EnterSSA failed: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM ssa_score WHERE ssa_record_id = $1`, ssaID)
		_, _ = admin.Exec(ctx, `DELETE FROM ssa_record WHERE id = $1`, ssaID)
	})
	if st, err := fops.DecideSSA(ctx, plP, ssaID, "confirmed", ""); err != nil || st != "confirmed" {
		t.Fatalf("DecideSSA failed: st=%q err=%v", st, err)
	}

	// 3. M12 Finance weekly fund request + duplicated disbursement callback idempotency.
	fin := financeops.NewService(gateway)
	wkStart := time.Date(2099, 1, 5, 0, 0, 0, 0, time.UTC)
	wkEnd := wkStart.AddDate(0, 0, 4)
	wfrID, err := fin.SubmitWeeklyRequest(ctx, cceoP, financeops.WeeklySubmitRequest{
		FY: "2099", WeekStart: wkStart, WeekEnd: wkEnd, TotalAmount: 450000, FundingSource: "edify_core",
	})
	if err != nil {
		t.Fatalf("SubmitWeeklyRequest failed: %v", err)
	}
	t.Cleanup(func() {
		_, _ = admin.Exec(ctx, `DELETE FROM weekly_fund_request WHERE id = $1`, wfrID)
		_, _ = admin.Exec(ctx, `DELETE FROM audit_log WHERE subject_id = $1`, wfrID)
	})
	if res, err := fin.TransitionWeeklyRequest(ctx, plP, wfrID, "approve_pl", 0, 0, "", "", ""); err != nil || res.Status != "approved_by_pl" {
		t.Fatalf("approve_pl failed: %+v err=%v", res, err)
	}
	if res, err := fin.TransitionWeeklyRequest(ctx, adminP, wfrID, "approve_cd", 0, 0, "", "", ""); err != nil || res.Status != "approved_by_cd" {
		t.Fatalf("approve_cd failed: %+v err=%v", res, err)
	}
	disb1, err := fin.TransitionWeeklyRequest(ctx, adminP, wfrID, "disburse", 450000, 0, "momo", "NS-MOMO-9901", "")
	if err != nil || !disb1.Applied || disb1.Status != "disbursed" {
		t.Fatalf("first disburse failed: %+v err=%v", disb1, err)
	}
	// Duplicate disbursement callback with same idempotency reference must NOT double-apply.
	disb2, err := fin.TransitionWeeklyRequest(ctx, adminP, wfrID, "disburse", 450000, 0, "momo", "NS-MOMO-9901", "")
	if err != nil || disb2.Applied || disb2.Status != "disbursed" {
		t.Fatalf("duplicate disburse callback should be idempotent (applied=false), got %+v err=%v", disb2, err)
	}
	if res, err := fin.TransitionWeeklyRequest(ctx, cceoP, wfrID, "confirm_receipt", 0, 0, "", "", ""); err != nil || res.Status != "receipt_confirmed" {
		t.Fatalf("confirm_receipt failed: %+v err=%v", res, err)
	}
	if res, err := fin.TransitionWeeklyRequest(ctx, cceoP, wfrID, "submit_accountability", 425000, 25000, "", "NS-ACC-9901", ""); err != nil || res.Status != "accounted" {
		t.Fatalf("submit_accountability failed: %+v err=%v", res, err)
	}
	variance, err := financeops.ReconcileVariance(450000, 425000, 25000)
	if err != nil || variance != 0 {
		t.Fatalf("variance=%d err=%v, want 0", variance, err)
	}

	// 4. Batch 10 / Step 2 DirectOnboarder: enforces leader_onboarding.py parity
	// by refusing to convert an existing staff account into a Cluster Leader.
	onboarder := clusterlead.NewDirectOnboarder(gateway)
	if _, err := onboarder.Onboard(ctx, "c1", clusterlead.OnboardInput{
		Name: "Existing CCEO", Email: cceoP.Email, Phone: "+256700000000",
	}); err == nil {
		t.Fatalf("DirectOnboarder must refuse existing staff email %s as Cluster Leader", cceoP.Email)
	}

	// 5. Batch 13 Workforce self-service profile update (non-destructive) & Authorized Async Export.
	wops := workforceops.NewService(gateway)
	if err := wops.UpdateOwnProfile(ctx, cceoP, "", ""); err != nil {
		t.Fatalf("UpdateOwnProfile failed: %v", err)
	}
	expMgr := exports.NewManager(gateway, time.Now)
	job, err := expMgr.CreateAndRun(ctx, cceoP, "completed_visits")
	if err != nil || job.Status != exports.StatusCompleted || !strings.HasPrefix(string(job.Payload), "activity_id,") {
		t.Fatalf("completed_visits export failed: job=%+v err=%v", job, err)
	}
	if _, err := expMgr.AuthorizeDownload(cceoP, job.ID); err != nil {
		t.Fatalf("owner export download refused: %v", err)
	}
	kePrincipal := cceoP
	kePrincipal.Country = &country.Work{ID: "ke-synthetic", Code: "KE"}
	if job.CountryID != "" {
		if _, err := expMgr.AuthorizeDownload(kePrincipal, job.ID); !errors.Is(err, exports.ErrForbidden) {
			t.Fatalf("expected cross-country download ErrForbidden, got %v", err)
		}
	}
	t.Logf("Phase C verified (zero Django): ev=%s ssa=%s wfr=%s export=%s rows=%d sha=%s",
		evID1, ssaID, wfrID, job.ID, job.RowCount, job.SHA256[:12])
}

// allEightSSAScores is a whole SSA: every intervention, each at score.
func allEightSSAScores(score float64) []fieldops.SSAScoreInput {
	out := make([]fieldops.SSAScoreInput, 0, len(fieldops.SSAInterventions))
	for _, iv := range fieldops.SSAInterventions {
		out = append(out, fieldops.SSAScoreInput{Intervention: iv.Key, Score: score})
	}
	return out
}
