package accounts

import (
	"context"
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestAdminCannotSetTemporaryPasswordOnOwnAccount(t *testing.T) {
	svc := NewService(Deps{})
	admin := auth.Principal{Account: auth.Account{UserID: "admin-1", ActiveRole: "Admin"}}
	err := svc.SetTemporaryPassword(context.Background(), admin, "admin-1", "NewStrongPassword123!")
	var refusal *Refused
	if !errors.As(err, &refusal) {
		t.Fatalf("expected Refused when admin resets own password, got %v", err)
	}
}
