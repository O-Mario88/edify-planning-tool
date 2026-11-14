package platformhealth

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

func TestHowLongReadsInWholeUnits(t *testing.T) {
	for d, want := range map[time.Duration]string{
		30 * time.Second: "under a minute", time.Minute: "1 minute", 90 * time.Minute: "1 hour 30 minutes",
		50 * time.Hour: "2 days 2 hours", 24 * time.Hour: "1 day 0 hours",
	} {
		if got := since(d); got != want {
			t.Errorf("%v: %q, want %q", d, got, want)
		}
	}
}

func TestOnlyTheRolesThatMayOpenSystemHealthOpenIt(t *testing.T) {
	s := NewService(nil, Facts{}, Probe{}, nil, time.Now)
	_, served, err := s.Build(context.Background(), auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: "CCEO"}}, Path, url.Values{})
	if !served || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("a CCEO: %v %v", served, err)
	}
	if _, served, _ := s.Build(context.Background(), auth.Principal{}, "/system-health", nil); served {
		t.Error("the existing System Health is not Go's")
	}
}
