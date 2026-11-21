package exports

import (
	"context"
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

func TestExportAuthorizationAtCreationAndDownload(t *testing.T) {
	mgr := NewManager(nil, nil)
	cceo := auth.Principal{Account: auth.Account{
		UserID: "u-cceo", ActiveRole: "CCEO", Country: &country.Work{ID: "ug", Code: "UG"},
	}}
	other := auth.Principal{Account: auth.Account{
		UserID: "u-other", ActiveRole: "CCEO", Country: &country.Work{ID: "ug", Code: "UG"},
	}}
	keReader := auth.Principal{Account: auth.Account{
		UserID: "u-cceo", ActiveRole: "CCEO", Country: &country.Work{ID: "ke", Code: "KE"},
	}}
	admin := auth.Principal{Account: auth.Account{UserID: "u-admin", ActiveRole: "Admin"}}

	// CCEO refused finance export at creation.
	if _, err := mgr.CreateAndRun(context.Background(), cceo, "finance_weekly"); !errors.Is(err, ErrForbidden) {
		t.Fatalf("expected ErrForbidden for CCEO finance export, got %v", err)
	}
	// CCEO permitted completed_visits export.
	job, err := mgr.CreateAndRun(context.Background(), cceo, "completed_visits")
	if err != nil || job.Status != StatusCompleted || job.SHA256 == "" {
		t.Fatalf("CreateAndRun failed: job=%+v err=%v", job, err)
	}
	// Owner can download.
	if _, err := mgr.AuthorizeDownload(cceo, job.ID); err != nil {
		t.Fatalf("owner download refused: %v", err)
	}
	// Unrelated user refused at download.
	if _, err := mgr.AuthorizeDownload(other, job.ID); !errors.Is(err, ErrForbidden) {
		t.Fatalf("unrelated user download should be ErrForbidden, got %v", err)
	}
	// Cross-country reader refused at download.
	if _, err := mgr.AuthorizeDownload(keReader, job.ID); !errors.Is(err, ErrForbidden) {
		t.Fatalf("cross-country download should be ErrForbidden, got %v", err)
	}
	// Admin positive control allowed.
	if _, err := mgr.AuthorizeDownload(admin, job.ID); err != nil {
		t.Fatalf("admin download refused: %v", err)
	}
}
