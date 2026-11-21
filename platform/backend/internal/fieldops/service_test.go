package fieldops

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestRecordUploadRejectsInterruptedUpload(t *testing.T) {
	svc := NewService(nil)
	p := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: "CCEO"}}
	if _, err := svc.RecordUpload(context.Background(), p, EvidenceUpload{
		ActivityID: "act1", URI: "s3://bucket/a.pdf", FileSize: 0,
	}); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for zero-byte upload, got %v", err)
	}
	if _, err := svc.RecordUpload(context.Background(), p, EvidenceUpload{
		ActivityID: "act1", URI: "", FileSize: 1024,
	}); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for missing URI, got %v", err)
	}
}

func TestIADecideActivityEnforcesRoleAndNote(t *testing.T) {
	svc := NewService(nil)
	cceo := auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: "CCEO"}}
	if _, err := svc.IADecideActivity(context.Background(), cceo, "act1", "verified", ""); !errors.Is(err, ErrForbidden) {
		t.Fatalf("expected ErrForbidden for CCEO, got %v", err)
	}
	ia := auth.Principal{Account: auth.Account{UserID: "u2", ActiveRole: "ImpactAssessment"}}
	if _, err := svc.IADecideActivity(context.Background(), ia, "act1", "returned", "  "); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput for empty return note, got %v", err)
	}
}

func TestPreviewSSACSVReconcilesValidDuplicatesAndRejected(t *testing.T) {
	csvData := strings.Join([]string{
		"school_id,score_ct,score_sl",
		"1001,3.5,4.0",
		"1001,3.0,3.0", // duplicate
		"1002,6.5,4.0", // invalid > 5
		",2.0,3.0",     // missing school_id
		"1003,4.2,3.8",
	}, "\n")
	preview, err := PreviewSSACSV(strings.NewReader(csvData), "2027")
	if err != nil {
		t.Fatalf("PreviewSSACSV failed: %v", err)
	}
	if len(preview.Valid) != 2 {
		t.Fatalf("valid=%d, want 2", len(preview.Valid))
	}
	if len(preview.Duplicate) != 1 || preview.Duplicate[0] != 3 {
		t.Fatalf("duplicates=%v, want [3]", preview.Duplicate)
	}
	if len(preview.Rejected) != 2 {
		t.Fatalf("rejected=%v, want 2 rows", preview.Rejected)
	}
}
