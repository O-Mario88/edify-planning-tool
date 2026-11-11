package config

import (
	"fmt"
	"net/url"
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
}

func loadLoans(env Environment, getenv func(string) string) (Loans, error) {
	loans := Loans{
		PublicBaseURL:     strings.TrimRight(strings.TrimSpace(getenv(envPublicBaseURL)), "/"),
		SMTPAddr:          strings.TrimSpace(getenv(envSMTPAddr)),
		SMTPUsername:      strings.TrimSpace(getenv(envSMTPUsername)),
		SMTPPassword:      getenv(envSMTPPassword),
		MailFrom:          strings.TrimSpace(getenv(envMailFrom)),
		DevMailboxDir:     strings.TrimSpace(getenv(envDevMailboxDir)),
		TrustProxyHeaders: strings.EqualFold(strings.TrimSpace(getenv(envTrustProxy)), "true"),
		PrivacyContact:    strings.TrimSpace(getenv(envPrivacyContact)),
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
