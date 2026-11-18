package settingspage

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"unicode"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrNotAvailable is the page refused to the reader's role (the existing
// page answers it with Access Denied).
var ErrNotAvailable = pagegate.ErrNotAvailable

// ErrActing is a reader in an acting appointment, whose pages the acting
// policy decides; they are handed on, as every Go page hands them.
var ErrActing = errors.New("settingspage: acting appointments are read by the existing page")

// Policy is who must use two-step verification whether or not they enrolled
// (settings.MFA_REQUIRED_FOR_ALL and MFA_REQUIRED_ROLES, which Go's sign-in
// reads as EDIFY_MFA_REQUIRED_*).
type Policy struct {
	RequiredForAll bool
	RequiredRoles  []string
}

// Service reads the Settings page.
type Service struct {
	db     schooldirectory.Querier
	policy Policy
	getenv func(string) string
}

// NewService wires the service to the database it reads, the two-step
// policy, and the environment the existing settings are read from (nil is
// the process's own).
func NewService(db schooldirectory.Querier, policy Policy, getenv func(string) string) *Service {
	if getenv == nil {
		getenv = os.Getenv
	}
	return &Service{db: db, policy: policy, getenv: getenv}
}

type account struct {
	email, phone, channel, activeRole string
	enrolled, appEnrolled, mustChange bool
	roles                             []string
}

// Build answers the page for p.
func (s *Service) Build(ctx context.Context, p auth.Principal) (*screensv1.GetSettingsResponse, error) {
	if p.InActingAppointment {
		return nil, ErrActing
	}
	if role, ok := rules.Roles[p.ActiveRole]; !ok || !role.Page {
		return nil, ErrNotAvailable
	}
	var a account
	err := s.db.QueryRow(ctx, `
SELECT u.email, COALESCE(u.phone, ''), u.mfa_enabled, COALESCE(u.mfa_channel, ''),
       COALESCE(u.mfa_secret, '') <> '', u.must_change_password, u.roles, COALESCE(u.active_role, '')
FROM "user" u WHERE u.id = $1`, p.UserID).Scan(
		&a.email, &a.phone, &a.enrolled, &a.channel, &a.appEnrolled, &a.mustChange, &a.roles, &a.activeRole)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotAvailable
	}
	if err != nil {
		return nil, fmt.Errorf("settingspage: reading the account: %w", err)
	}
	return &screensv1.GetSettingsResponse{
		Email:              a.email,
		MustChangePassword: a.mustChange,
		TwoStep:            s.twoStep(a),
		SessionIdleMinutes: int32(floorDiv(s.sessionIdleSeconds(), 60)),
	}, nil
}

// twoStep is enrolment_state.
func (s *Service) twoStep(a account) *screensv1.TwoStepVerification {
	smsAvailable := a.phone != "" && s.smsConfigured()
	required := s.requiredByPolicy(a)
	out := &screensv1.TwoStepVerification{
		InForce:          required || a.enrolled,
		RequiredByPolicy: required,
		Channel:          resolveChannel(a.channel, smsAvailable, a.appEnrolled),
		AppAvailable:     a.appEnrolled,
		SmsAvailable:     smsAvailable,
		EmailHint:        maskEmail(a.email),
	}
	switch {
	case smsAvailable:
	case a.phone == "":
		out.SmsBlockedReason = rules.SMSNeedsPhone
	default:
		out.SmsBlockedReason = rules.SMSNotConfigured
	}
	if a.phone != "" {
		out.PhoneHint = maskPhone(a.phone)
	}
	return out
}

// requiredByPolicy: the estate-wide switch, or a role held (or the active
// role) among the required ones.
func (s *Service) requiredByPolicy(a account) bool {
	if s.policy.RequiredForAll {
		return true
	}
	for _, required := range s.policy.RequiredRoles {
		if a.activeRole != "" && required == a.activeRole {
			return true
		}
		for _, held := range a.roles {
			if held == required {
				return true
			}
		}
	}
	return false
}

// smsConfigured is SmsService.is_configured, read from the same settings.
func (s *Service) smsConfigured() bool {
	if s.getenv(rules.SMSProviderEnv) != rules.SMSProvider {
		return false
	}
	for _, name := range rules.SMSRequiredEnvs {
		if s.getenv(name) == "" {
			return false
		}
	}
	return true
}

// sessionIdleSeconds is SESSION_COOKIE_AGE: the setting as an integer, its
// default when it is unset or not one (config/settings/base.py _as_int).
func (s *Service) sessionIdleSeconds() int {
	value := s.getenv(rules.SessionIdleEnv)
	if value == "" {
		return rules.SessionIdleDefaultSeconds
	}
	if n, ok := pythonInt(value); ok {
		return n
	}
	return rules.SessionIdleDefaultSeconds
}

// pythonInt reads a number as Python's int() does for the forms a setting
// takes: surrounding spaces, a sign, and underscores between digits.
func pythonInt(value string) (int, bool) {
	text := strings.TrimSpace(value)
	digits := strings.TrimLeft(text, "+-")
	if len(text)-len(digits) > 1 || digits == "" || strings.HasPrefix(digits, "_") ||
		strings.HasSuffix(digits, "_") || strings.Contains(digits, "__") {
		return 0, false
	}
	n, err := strconv.Atoi(strings.ReplaceAll(text, "_", ""))
	return n, err == nil
}

// floorDiv is Python's //, which floors rather than truncates.
func floorDiv(a, b int) int {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

// resolveChannel is resolve_channel: the preferred channel when it can be
// used, email otherwise.
func resolveChannel(preferred string, smsAvailable, appEnrolled bool) string {
	if preferred == "" {
		preferred = rules.Channels.Email
	}
	switch preferred {
	case rules.Channels.Email:
		return preferred
	case rules.Channels.SMS:
		if smsAvailable {
			return preferred
		}
	case rules.Channels.App:
		if appEnrolled {
			return preferred
		}
	}
	return rules.Channels.Email
}

// maskEmail is _mask_email.
func maskEmail(address string) string {
	name, domain, found := strings.Cut(address, "@")
	if !found || domain == "" {
		return "•••"
	}
	letters := []rune(name)
	head := ""
	if len(letters) > 0 {
		head = string(letters[0])
	}
	return head + strings.Repeat("•", max(3, len(letters)-1)) + "@" + domain
}

// maskPhone is _mask_phone.
func maskPhone(number string) string {
	var digits []rune
	for _, r := range number {
		if unicode.IsDigit(r) {
			digits = append(digits, r)
		}
	}
	if len(digits) < 4 {
		return "••••"
	}
	return "•••• " + string(digits[len(digits)-4:])
}
