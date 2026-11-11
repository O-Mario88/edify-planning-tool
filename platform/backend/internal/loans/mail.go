package loans

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"net/mail"
	"net/smtp"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
)

// Message is one plain-text email. The portal's emails carry references and
// links only: never a director's details or a school's finances.
type Message struct {
	To      string
	Subject string
	Text    string
}

// Mailer hands a message to a mail provider. A nil error means the provider
// accepted it — not that anyone read it.
type Mailer interface {
	Send(ctx context.Context, message Message) (providerID string, err error)
	// Channel names the provider in the timeline ("email", "development mailbox").
	Channel() string
}

// ErrNoMailer: no provider is configured, so nothing can be sent.
var ErrNoMailer = errors.New("loans: no mail provider is configured")

// NewMailer returns the configured provider, or nil when there is none.
func NewMailer(cfg config.Loans) Mailer {
	switch {
	case cfg.DevMailboxDir != "":
		return &fileMailer{dir: cfg.DevMailboxDir, from: cfg.MailFrom}
	case cfg.SMTPAddr != "":
		return &smtpMailer{addr: cfg.SMTPAddr, username: cfg.SMTPUsername, password: cfg.SMTPPassword, from: cfg.MailFrom}
	}
	return nil
}

func compose(from string, message Message, id string, at time.Time) ([]byte, error) {
	for _, value := range []string{from, message.To, message.Subject} {
		if strings.ContainsAny(value, "\r\n") {
			return nil, errors.New("loans: a mail header holds a line break")
		}
	}
	if _, err := mail.ParseAddress(message.To); err != nil {
		return nil, fmt.Errorf("loans: %q is not an email address", message.To)
	}
	var out strings.Builder
	fmt.Fprintf(&out, "From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\nMessage-ID: <%s@edify-loans>\r\n",
		from, message.To, message.Subject, at.Format(time.RFC1123Z), id)
	out.WriteString("MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n")
	out.WriteString(strings.ReplaceAll(message.Text, "\n", "\r\n"))
	return []byte(out.String()), nil
}

// fileMailer writes each message to a file: a developer's machine only
// (config refuses it outside development and test).
type fileMailer struct {
	dir  string
	from string
}

func (m *fileMailer) Channel() string { return "development mailbox" }

func (m *fileMailer) Send(_ context.Context, message Message) (string, error) {
	id, err := NewID()
	if err != nil {
		return "", err
	}
	now := time.Now()
	raw, err := compose(m.from, message, id, now)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(m.dir, 0o700); err != nil {
		return "", fmt.Errorf("loans: preparing the mailbox: %w", err)
	}
	name := filepath.Join(m.dir, now.UTC().Format("20060102T150405.000")+"-"+id+".eml")
	if err := os.WriteFile(name, raw, 0o600); err != nil {
		return "", fmt.Errorf("loans: writing to the mailbox: %w", err)
	}
	return id, nil
}

// smtpMailer sends through an SMTP relay, only ever over TLS.
type smtpMailer struct {
	addr, username, password, from string
}

func (m *smtpMailer) Channel() string { return "email" }

const smtpTimeout = 30 * time.Second

func (m *smtpMailer) Send(ctx context.Context, message Message) (string, error) {
	id, err := NewID()
	if err != nil {
		return "", err
	}
	raw, err := compose(m.from, message, id, time.Now())
	if err != nil {
		return "", err
	}
	host, _, err := net.SplitHostPort(m.addr)
	if err != nil {
		return "", fmt.Errorf("loans: EDIFY_SMTP_ADDR must be host:port")
	}
	dialer := net.Dialer{Timeout: smtpTimeout}
	conn, err := dialer.DialContext(ctx, "tcp", m.addr)
	if err != nil {
		return "", fmt.Errorf("loans: reaching the mail relay: %w", err)
	}
	_ = conn.SetDeadline(time.Now().Add(smtpTimeout))
	client, err := smtp.NewClient(conn, host)
	if err != nil {
		_ = conn.Close()
		return "", fmt.Errorf("loans: greeting the mail relay: %w", err)
	}
	defer func() { _ = client.Close() }()
	if ok, _ := client.Extension("STARTTLS"); !ok {
		return "", errors.New("loans: the mail relay does not offer TLS; refusing to send in clear text")
	}
	if err := client.StartTLS(&tls.Config{ServerName: host, MinVersion: tls.VersionTLS12}); err != nil {
		return "", fmt.Errorf("loans: starting TLS with the mail relay: %w", err)
	}
	if m.username != "" {
		if err := client.Auth(smtp.PlainAuth("", m.username, m.password, host)); err != nil {
			return "", errors.New("loans: the mail relay refused the credentials")
		}
	}
	sender, err := mail.ParseAddress(m.from)
	if err != nil {
		return "", fmt.Errorf("loans: EDIFY_MAIL_FROM is not an address")
	}
	if err := client.Mail(sender.Address); err != nil {
		return "", fmt.Errorf("loans: the mail relay refused the sender: %w", err)
	}
	if err := client.Rcpt(message.To); err != nil {
		return "", fmt.Errorf("loans: the mail relay refused the recipient: %w", err)
	}
	body, err := client.Data()
	if err != nil {
		return "", fmt.Errorf("loans: opening the message body: %w", err)
	}
	if _, err := body.Write(raw); err != nil {
		return "", fmt.Errorf("loans: writing the message: %w", err)
	}
	if err := body.Close(); err != nil {
		return "", fmt.Errorf("loans: the mail relay did not accept the message: %w", err)
	}
	return id, client.Quit()
}

// maskEmail shows enough of an address to recognise it: g***@lender.org.
func maskEmail(address string) string {
	local, domain, found := strings.Cut(address, "@")
	if !found || local == "" {
		return "***"
	}
	return local[:1] + "***@" + domain
}
