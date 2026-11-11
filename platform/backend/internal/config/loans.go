package config

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
)

const (
	envPublicBaseURL  = "EDIFY_PUBLIC_BASE_URL"
	envSMTPAddr       = "EDIFY_SMTP_ADDR"
	envSMTPUsername   = "EDIFY_SMTP_USERNAME"
	envSMTPPassword   = "EDIFY_SMTP_PASSWORD"
	envMailFrom       = "EDIFY_MAIL_FROM"
	envDevMailboxDir  = "EDIFY_DEV_MAILBOX_DIR"
	envTrustProxy     = "EDIFY_TRUST_PROXY_HEADERS"
	envPrivacyContact = "EDIFY_LOANS_PRIVACY_CONTACT"
	envSMSProvider    = "EDIFY_SMS_PROVIDER"
	envSMSDevDir      = "EDIFY_SMS_DEV_DIR"
	envSMSUsername    = "EDIFY_SMS_USERNAME"
	envSMSAPIKey      = "EDIFY_SMS_API_KEY"
	envSMSSender      = "EDIFY_SMS_SENDER"
	envSMSCallback    = "EDIFY_SMS_CALLBACK_SECRET"
	envCooldownDays   = "EDIFY_LOAN_REMINDER_COOLDOWN_DAYS"
)

// Loans configures the School Loan Application Portal's public pages and
// the mail that carries referrals to lenders.
type Loans struct {
	// PublicBaseURL is where the public form and emailed links point, such
	// as https://apply.staging.example. Empty: links are built from the
	// request, and lender notifications wait (they need an absolute link).
	PublicBaseURL string
	// SMTP delivery. Empty SMTPAddr: no mail provider; notifications stay
	// queued and staff see them waiting. Nothing is ever marked sent unless
	// a provider accepted it.
	SMTPAddr     string
	SMTPUsername string
	SMTPPassword string
	MailFrom     string
	// DevMailboxDir writes each message to a file instead of sending it, on
	// a developer's machine only (development and test).
	DevMailboxDir string
	// TrustProxyHeaders reads the client address from X-Forwarded-For, for
	// rate limiting behind the platform's load balancer.
	TrustProxyHeaders bool
	// PrivacyContact is who the privacy notice tells applicants to contact.
	PrivacyContact string

	// SMSProvider is "" (none: reminders and codes by SMS wait, and nothing is
	// claimed sent), "dev_file" (development and test: each message is
	// written to SMSDevDir) or "africastalking".
	SMSProvider string
	SMSDevDir   string
	SMSUsername string
	SMSAPIKey   string
	SMSSender   string
	// SMSCallbackSecret authenticates the provider's delivery reports.
	SMSCallbackSecret string
	// ReminderCooldownDays is how long after a notification of one kind to a
	// school another of the same kind waits (staff, lenders and the weekly
	// reminders alike). Default 7.
	ReminderCooldownDays int
}

// defaultCooldownDays: one reminder of a kind to a school a week.
const defaultCooldownDays = 7

func loadLoans(env Environment, getenv func(string) string) (Loans, error) {
	loans := Loans{
		PublicBaseURL:        strings.TrimRight(strings.TrimSpace(getenv(envPublicBaseURL)), "/"),
		SMTPAddr:             strings.TrimSpace(getenv(envSMTPAddr)),
		SMTPUsername:         strings.TrimSpace(getenv(envSMTPUsername)),
		SMTPPassword:         getenv(envSMTPPassword),
		MailFrom:             strings.TrimSpace(getenv(envMailFrom)),
		DevMailboxDir:        strings.TrimSpace(getenv(envDevMailboxDir)),
		TrustProxyHeaders:    strings.EqualFold(strings.TrimSpace(getenv(envTrustProxy)), "true"),
		PrivacyContact:       strings.TrimSpace(getenv(envPrivacyContact)),
		SMSProvider:          strings.TrimSpace(getenv(envSMSProvider)),
		SMSDevDir:            strings.TrimSpace(getenv(envSMSDevDir)),
		SMSUsername:          strings.TrimSpace(getenv(envSMSUsername)),
		SMSAPIKey:            getenv(envSMSAPIKey),
		SMSSender:            strings.TrimSpace(getenv(envSMSSender)),
		SMSCallbackSecret:    getenv(envSMSCallback),
		ReminderCooldownDays: defaultCooldownDays,
	}
	if raw := strings.TrimSpace(getenv(envCooldownDays)); raw != "" {
		days, err := strconv.Atoi(raw)
		if err != nil || days < 1 || days > 60 {
			return Loans{}, fmt.Errorf("config: %s must be a whole number of days from 1 to 60", envCooldownDays)
		}
		loans.ReminderCooldownDays = days
	}
	switch loans.SMSProvider {
	case "":
	case "dev_file":
		if env != Development && env != Test {
			return Loans{}, fmt.Errorf("config: %s=dev_file is for development and test only", envSMSProvider)
		}
		if loans.SMSDevDir == "" {
			return Loans{}, fmt.Errorf("config: %s is required for dev_file", envSMSDevDir)
		}
	case "africastalking":
		if loans.SMSUsername == "" || loans.SMSAPIKey == "" {
			return Loans{}, fmt.Errorf("config: %s and %s are required for africastalking", envSMSUsername, envSMSAPIKey)
		}
		if len(loans.SMSCallbackSecret) < 24 {
			return Loans{}, fmt.Errorf("config: %s must be a long random secret", envSMSCallback)
		}
	default:
		return Loans{}, fmt.Errorf("config: %s must be dev_file or africastalking", envSMSProvider)
	}
	if loans.PublicBaseURL != "" {
		parsed, err := url.Parse(loans.PublicBaseURL)
		if err != nil || parsed.Host == "" || parsed.Path != "" {
			return Loans{}, fmt.Errorf("config: %s must be a base URL such as https://host", envPublicBaseURL)
		}
		host := strings.ToLower(parsed.Hostname())
		if host == productionSite || strings.HasSuffix(host, "."+productionSite) {
			return Loans{}, fmt.Errorf("config: %s points at the production site; this build may not use it", envPublicBaseURL)
		}
		if env == Staging && parsed.Scheme != "https" {
			return Loans{}, fmt.Errorf("config: %s must be https in staging", envPublicBaseURL)
		}
	}
	if loans.DevMailboxDir != "" && env != Development && env != Test {
		return Loans{}, fmt.Errorf("config: %s is for development and test only", envDevMailboxDir)
	}
	if loans.DevMailboxDir != "" && loans.SMTPAddr != "" {
		return Loans{}, fmt.Errorf("config: set %s or %s, not both", envDevMailboxDir, envSMTPAddr)
	}
	if (loans.SMTPAddr != "" || loans.DevMailboxDir != "") && loans.MailFrom == "" {
		return Loans{}, fmt.Errorf("config: %s is required when mail is configured", envMailFrom)
	}
	return loans, nil
}
