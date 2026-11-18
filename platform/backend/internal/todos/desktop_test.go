package todos

import (
	"context"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// The desktop To-Do has its own header and parts, which Go does not build
// yet: a desktop reading is handed on before anything is read.
func TestADesktopReadingIsHandedOn(t *testing.T) {
	s := NewService(nil, time.Now)
	ctx := pagegate.WithDesktop(context.Background(), true)
	response, served, err := s.Build(ctx, auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}, Path, nil)
	if served || response != nil || err != nil {
		t.Fatalf("a desktop reading was answered: %v %v %v", response, served, err)
	}
}
