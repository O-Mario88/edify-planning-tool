package settingspage

import (
	"context"
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestMasksAreThePagesOwn(t *testing.T) {
	for _, tc := range []struct{ in, want string }{
		{"ann@edify.org", "a•••@edify.org"},
		{"alexandra@edify.org", "a••••••••@edify.org"},
		{"@edify.org", "•••@edify.org"},
		{"no-at-sign", "•••"},
		{"x@", "•••"},
		{"élise@edify.org", "é••••@edify.org"},
	} {
		if got := maskEmail(tc.in); got != tc.want {
			t.Errorf("maskEmail(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
	for _, tc := range []struct{ in, want string }{
		{"+256 700 000 001", "•••• 0001"},
		{"123", "••••"},
	} {
		if got := maskPhone(tc.in); got != tc.want {
			t.Errorf("maskPhone(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestTheChannelFallsBackToEmail(t *testing.T) {
	for _, tc := range []struct {
		preferred   string
		sms, app    bool
		want        string
		description string
	}{
		{"", false, false, "email", "none chosen"},
		{"sms", true, false, "sms", "text messages reach them"},
		{"sms", false, false, "email", "a number removed or the provider off"},
		{"app", false, true, "app", "the app is set up"},
		{"app", false, false, "email", "the app is not set up"},
		{"carrier-pigeon", true, true, "email", "an unknown channel"},
	} {
		if got := resolveChannel(tc.preferred, tc.sms, tc.app); got != tc.want {
			t.Errorf("%s: resolveChannel = %q, want %q", tc.description, got, tc.want)
		}
	}
}

func TestPolicyCoversTheActiveRoleAndEveryHeldRole(t *testing.T) {
	s := NewService(nil, Policy{RequiredRoles: []string{"Admin"}}, func(string) string { return "" })
	if !s.requiredByPolicy(account{roles: []string{"CCEO", "Admin"}, activeRole: "CCEO"}) {
		t.Error("a held required role is not covered")
	}
	if !s.requiredByPolicy(account{activeRole: "Admin"}) {
		t.Error("the active required role is not covered")
	}
	if s.requiredByPolicy(account{roles: []string{"CCEO"}, activeRole: "CCEO"}) {
		t.Error("a role outside the policy is covered")
	}
	all := NewService(nil, Policy{RequiredForAll: true}, func(string) string { return "" })
	if !all.requiredByPolicy(account{}) {
		t.Error("the estate-wide switch does not cover everyone")
	}
}

func TestSMSNeedsTheProviderAndBothSettings(t *testing.T) {
	env := map[string]string{"SMS_PROVIDER": "africastalking", "SMS_API_KEY": "k", "SMS_USERNAME": "u"}
	getenv := func(name string) string { return env[name] }
	s := NewService(nil, Policy{}, getenv)
	if !s.smsConfigured() {
		t.Fatal("configured SMS is not offered")
	}
	two := s.twoStep(account{email: "a@b.c", phone: "+256700000001"})
	if !two.SmsAvailable || two.SmsBlockedReason != "" || two.PhoneHint != "•••• 0001" {
		t.Errorf("with a phone: %+v", two)
	}
	if two := s.twoStep(account{email: "a@b.c"}); two.SmsAvailable || two.SmsBlockedReason != rules.SMSNeedsPhone {
		t.Errorf("without a phone: %+v", two)
	}
	delete(env, "SMS_USERNAME")
	if two := s.twoStep(account{email: "a@b.c", phone: "+256700000001"}); two.SmsAvailable || two.SmsBlockedReason != rules.SMSNotConfigured {
		t.Errorf("without a username: %+v", two)
	}
}

func TestTheSessionLengthIsReadAsTheSettingsAre(t *testing.T) {
	for _, tc := range []struct {
		value string
		want  int
	}{
		{"", 1800},
		{"3600", 3600},
		{" 900 ", 900},
		{"1_200", 1200},
		{"thirty", 1800},
		{"1__200", 1800},
		{"_1200", 1800},
		{"-90", -90},
	} {
		s := NewService(nil, Policy{}, func(string) string { return tc.value })
		if got := s.sessionIdleSeconds(); got != tc.want {
			t.Errorf("%q: %d, want %d", tc.value, got, tc.want)
		}
	}
	if floorDiv(-90, 60) != -2 || floorDiv(90, 60) != 1 || floorDiv(1800, 60) != 30 {
		t.Error("floorDiv is not Python's //")
	}
}

func TestWhoMayOpenSettings(t *testing.T) {
	s := NewService(nil, Policy{}, func(string) string { return "" })
	ctx := context.Background()
	if _, err := s.Build(ctx, auth.Principal{Account: auth.Account{ActiveRole: "ClusterLeader"}}); !errors.Is(err, ErrNotAvailable) {
		t.Errorf("the Cluster Leader: %v", err)
	}
	if _, err := s.Build(ctx, auth.Principal{Account: auth.Account{ActiveRole: "Nobody"}}); !errors.Is(err, ErrNotAvailable) {
		t.Errorf("an unknown role: %v", err)
	}
	acting := auth.Principal{Account: auth.Account{ActiveRole: "CCEO", InActingAppointment: true}}
	if _, err := s.Build(ctx, acting); !errors.Is(err, ErrActing) {
		t.Errorf("an acting appointment: %v", err)
	}
}
