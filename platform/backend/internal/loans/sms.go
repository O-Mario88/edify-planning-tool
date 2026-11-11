package loans

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// SMSProvider hands a text message to an SMS gateway. A nil error means the
// gateway accepted it for sending — not that the phone received it; only a
// delivery report says that.
type SMSProvider interface {
	Send(ctx context.Context, to, body string) (providerID string, err error)
	Name() string
}

// NewSMSProvider returns the configured provider, or nil when there is none.
func NewSMSProvider(cfg config.Loans) SMSProvider {
	switch cfg.SMSProvider {
	case "dev_file":
		return &fileSMS{dir: cfg.SMSDevDir}
	case "africastalking":
		return &africasTalking{username: cfg.SMSUsername, apiKey: cfg.SMSAPIKey, sender: cfg.SMSSender,
			http: &http.Client{Timeout: 20 * time.Second}}
	}
	return nil
}

// fileSMS writes each message to a file: a developer's machine only.
type fileSMS struct{ dir string }

func (f *fileSMS) Name() string { return "development SMS file" }

func (f *fileSMS) Send(_ context.Context, to, body string) (string, error) {
	id, err := NewID()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(f.dir, 0o700); err != nil {
		return "", err
	}
	name := filepath.Join(f.dir, time.Now().UTC().Format("20060102T150405.000")+"-"+id+".sms")
	return id, os.WriteFile(name, []byte("To: "+to+"\n\n"+body+"\n"), 0o600)
}

// africasTalking sends through Africa's Talking's messaging API.
type africasTalking struct {
	username, apiKey, sender string
	http                     *http.Client
}

func (a *africasTalking) Name() string { return "Africa's Talking" }

func (a *africasTalking) Send(ctx context.Context, to, body string) (string, error) {
	form := url.Values{"username": {a.username}, "to": {to}, "message": {body}}
	if a.sender != "" {
		form.Set("from", a.sender)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.africastalking.com/version1/messaging",
		strings.NewReader(form.Encode()))
	if err != nil {
		return "", err
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.Header.Set("Accept", "application/json")
	request.Header.Set("apiKey", a.apiKey)
	response, err := a.http.Do(request)
	if err != nil {
		return "", fmt.Errorf("loans: reaching the SMS gateway: %w", err)
	}
	defer func() { _ = response.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(response.Body, 64<<10))
	var answer struct {
		SMSMessageData struct {
			Recipients []struct {
				Status    string `json:"status"`
				MessageID string `json:"messageId"`
			} `json:"Recipients"`
		} `json:"SMSMessageData"`
	}
	if response.StatusCode >= 300 || json.Unmarshal(raw, &answer) != nil || len(answer.SMSMessageData.Recipients) == 0 {
		return "", fmt.Errorf("loans: the SMS gateway refused the message (status %d)", response.StatusCode)
	}
	recipient := answer.SMSMessageData.Recipients[0]
	if recipient.Status != "Success" {
		return "", fmt.Errorf("loans: the SMS gateway refused the message: %s", recipient.Status)
	}
	return recipient.MessageID, nil
}

// SMS kinds.
const (
	SMSUpcoming      = "installment_upcoming"
	SMSOverdue       = "installment_overdue"
	SMSAccessCode    = "access_code"
	SMSStatementLink = "statement_link"
	SMSAgreementLink = "agreement_link"
)

// QueueSMS adds a message once: a second message with the same dedupe key
// is the first one. An opted-out number is recorded as suppressed.
func (s *Store) QueueSMS(ctx context.Context, applicationID, kind, dedupeKey, recipient, body string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var optedOut bool
		if err := tx.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM school_loans.sms_preference WHERE phone = $1 AND opted_out_at IS NOT NULL)`, recipient).
			Scan(&optedOut); err != nil {
			return err
		}
		status := "queued"
		if optedOut && kind != SMSAccessCode {
			status = "suppressed"
		}
		id, err := NewID()
		if err != nil {
			return err
		}
		var application *string
		if applicationID != "" {
			application = &applicationID
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.sms_message (id, application_id, kind, dedupe_key, recipient, body, status, next_attempt_at,
  created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, $8) ON CONFLICT (dedupe_key) DO NOTHING`, id, application, kind, dedupeKey,
			recipient, body, status, now)
		return err
	})
}

// SMSWorker sends queued messages and queues the weekly reminders.
type SMSWorker struct {
	store    *Store
	provider SMSProvider
	keys     Keys
	baseURL  string
	logger   *slog.Logger
	now      func() time.Time
}

// NewSMSWorker returns the SMS worker; provider may be nil.
func NewSMSWorker(store *Store, provider SMSProvider, keys Keys, baseURL string, logger *slog.Logger, now func() time.Time) *SMSWorker {
	if now == nil {
		now = time.Now
	}
	return &SMSWorker{store: store, provider: provider, keys: keys, baseURL: strings.TrimRight(baseURL, "/"), logger: logger, now: now}
}

// Reminder policy: weekly, on Mondays, in Kampala's daytime only.
const (
	reminderWeekday   = time.Monday
	reminderFromHour  = 8
	reminderUntilHour = 18
	upcomingWindow    = 7
	smsRetries        = 5
)

// SendDue sends the queued messages whose time has come.
func (w *SMSWorker) SendDue(ctx context.Context) (int, error) {
	if w.provider == nil {
		return 0, nil
	}
	type due struct {
		id, recipient, body string
		attempts            int
	}
	var batch []due
	err := w.store.inWrite(ctx, func(tx pgx.Tx) error {
		rows, err := tx.Query(ctx, `
UPDATE school_loans.sms_message SET lease_until = $2, attempts = attempts + 1, updated_at = $1
WHERE id IN (SELECT id FROM school_loans.sms_message
  WHERE status = 'queued' AND next_attempt_at <= $1 AND (lease_until IS NULL OR lease_until < $1)
  ORDER BY next_attempt_at LIMIT 20 FOR UPDATE SKIP LOCKED)
RETURNING id, recipient, body, attempts`, w.now(), w.now().Add(2*time.Minute))
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var d due
			if err := rows.Scan(&d.id, &d.recipient, &d.body, &d.attempts); err != nil {
				return err
			}
			batch = append(batch, d)
		}
		return rows.Err()
	})
	if err != nil {
		return 0, err
	}
	for _, d := range batch {
		providerID, sendErr := w.provider.Send(ctx, d.recipient, d.body)
		err := w.store.inWrite(ctx, func(tx pgx.Tx) error {
			switch {
			case sendErr == nil:
				_, err := tx.Exec(ctx, `
UPDATE school_loans.sms_message SET status = 'submitted', provider = $2, provider_message_id = $3, submitted_at = $4,
  lease_until = NULL, last_error = '', updated_at = $4 WHERE id = $1`, d.id, w.provider.Name(), providerID, w.now())
				return err
			case d.attempts >= smsRetries:
				_, err := tx.Exec(ctx, `
UPDATE school_loans.sms_message SET status = 'failed', lease_until = NULL, last_error = $2, updated_at = $3 WHERE id = $1`,
					d.id, truncate(sendErr.Error(), 300), w.now())
				return err
			default:
				_, err := tx.Exec(ctx, `
UPDATE school_loans.sms_message SET lease_until = NULL, last_error = $2, next_attempt_at = $3, updated_at = $4 WHERE id = $1`,
					d.id, truncate(sendErr.Error(), 300), w.now().Add(time.Duration(d.attempts*d.attempts)*5*time.Minute), w.now())
				return err
			}
		})
		if err != nil {
			return 0, err
		}
	}
	return len(batch), nil
}

func truncate(text string, limit int) string {
	if len(text) > limit {
		return text[:limit]
	}
	return text
}

// ReminderCandidate is an active loan that may need a reminder.
type ReminderCandidate struct {
	ApplicationID, LoanID, LenderName, Phone string
}

// reminderCandidates are applications with a ledger loan, not closed.
func (s *Store) reminderCandidates(ctx context.Context) ([]ReminderCandidate, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, linked_mfi_loan_id, lender_name, director_phone FROM school_loans.application
WHERE linked_mfi_loan_id <> '' AND closure_status NOT IN ('closed', 'written_off')
  AND status NOT IN ('withdrawn', 'closed')`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ReminderCandidate
	for rows.Next() {
		var c ReminderCandidate
		if err := rows.Scan(&c.ApplicationID, &c.LoanID, &c.LenderName, &c.Phone); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// ReminderFor decides the one reminder, if any, a loan's position calls for
// this week. It follows the brief's checks in order: the loan is active and
// not settled; the next unpaid installment is overdue, or due within a week;
// a reminder for this week has not already been queued (the dedupe key).
func ReminderFor(position ledger.Position, week string, applicationID string) (kind, dedupe string, due *ledger.InstallmentView) {
	if position.Status == ledger.StatusSettled || position.Status == ledger.StatusAwaitingDisbursement ||
		position.Status == ledger.StatusNoSchedule || position.NextDue == nil {
		return "", "", nil
	}
	next := position.NextDue
	if position.AmountOverdue > 0 {
		return SMSOverdue, "overdue:" + applicationID + ":" + week, next
	}
	if !next.DueDate.After(position.AsOf.AddDate(0, 0, upcomingWindow)) {
		return SMSUpcoming, "upcoming:" + applicationID + ":" + next.ID + ":" + week, next
	}
	return "", "", nil
}

// QueueWeeklyReminders queues this week's reminders, once, on the reminder
// day in Kampala's daytime. Each reads the loan's latest verified position.
func (w *SMSWorker) QueueWeeklyReminders(ctx context.Context) (int, error) {
	local := w.now().In(kampala)
	if local.Weekday() != reminderWeekday || local.Hour() < reminderFromHour || local.Hour() >= reminderUntilHour {
		return 0, nil
	}
	year, number := local.ISOWeek()
	week := fmt.Sprintf("%d-W%02d", year, number)
	candidates, err := w.store.reminderCandidates(ctx)
	if err != nil {
		return 0, err
	}
	queued := 0
	for _, c := range candidates {
		verified, err := w.store.PhoneVerified(ctx, c.ApplicationID)
		if err != nil || !verified {
			continue
		}
		_, book, _, err := w.store.LedgerBook(ctx, c.LoanID)
		if err != nil {
			continue
		}
		position := book.Position(ledger.DayOf(local), 14)
		kind, dedupe, due := ReminderFor(position, week, c.ApplicationID)
		if kind == "" {
			continue
		}
		link, err := w.statementLink(ctx, c.ApplicationID, c.Phone, local)
		if err != nil {
			return queued, err
		}
		body := fmt.Sprintf("Edify Loan Reminder: your school loan installment with %s is due on %s. "+
			"Contact %s if you need assistance. Your secure statement: %s",
			c.LenderName, due.DueDate.Format("2 Jan 2006"), c.LenderName, link)
		if kind == SMSOverdue {
			body = fmt.Sprintf("Edify Loan Reminder: a school loan installment with %s is overdue. "+
				"Please contact %s about it. Your secure statement: %s", c.LenderName, c.LenderName, link)
		}
		if err := w.store.QueueSMS(ctx, c.ApplicationID, kind, dedupe, c.Phone, body, w.now()); err != nil {
			return queued, err
		}
		queued++
	}
	return queued, nil
}

// statementLink issues a fresh statement access link (a code is still
// needed to open it) for the director's phone.
func (w *SMSWorker) statementLink(ctx context.Context, applicationID, phone string, now time.Time) (string, error) {
	token, err := w.store.IssueSchoolAccess(ctx, applicationID, "statement", "sms", phone, "system", now)
	if err != nil {
		return "", err
	}
	return w.baseURL + "/loan/statement?t=" + url.QueryEscape(token), nil
}

// Run sends queued messages every minute and queues reminders hourly.
func (w *SMSWorker) Run(ctx context.Context, ready func(context.Context) error) {
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()
	lastReminders := time.Time{}
	for {
		if ready(ctx) == nil {
			if _, err := w.SendDue(ctx); err != nil && ctx.Err() == nil {
				w.logger.Error("loans: sending SMS failed", slog.String("error", err.Error()))
			}
			if w.now().Sub(lastReminders) >= time.Hour && w.baseURL != "" {
				if _, err := w.QueueWeeklyReminders(ctx); err != nil && ctx.Err() == nil {
					w.logger.Error("loans: queueing reminders failed", slog.String("error", err.Error()))
				}
				lastReminders = w.now()
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// DeliveryReports takes the SMS gateway's delivery reports at
// /sms/delivery-report/{secret}. Only a report marks a message delivered.
func (s *Store) DeliveryReports(secret string, logger *slog.Logger) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		if secret == "" || subtle.ConstantTimeCompare([]byte(request.PathValue("secret")), []byte(secret)) != 1 {
			http.NotFound(writer, request)
			return
		}
		request.Body = http.MaxBytesReader(writer, request.Body, 16<<10)
		if err := request.ParseForm(); err != nil {
			writer.WriteHeader(http.StatusBadRequest)
			return
		}
		id, status := request.PostForm.Get("id"), request.PostForm.Get("status")
		next := map[string]string{"Success": "delivered", "Failed": "failed", "Rejected": "failed"}[status]
		if id == "" || next == "" {
			writer.WriteHeader(http.StatusNoContent)
			return
		}
		err := s.inWrite(request.Context(), func(tx pgx.Tx) error {
			_, err := tx.Exec(request.Context(), `
UPDATE school_loans.sms_message SET status = $2, delivered_at = CASE WHEN $2 = 'delivered' THEN now() ELSE delivered_at END,
  last_error = CASE WHEN $2 = 'failed' THEN $3 ELSE last_error END, updated_at = now()
WHERE provider_message_id = $1 AND status IN ('submitted', 'delivered', 'failed')`, id, next, "Delivery report: "+status)
			return err
		})
		if err != nil {
			logger.Error("loans: recording an SMS delivery report", slog.String("error", err.Error()))
			writer.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		writer.WriteHeader(http.StatusNoContent)
	}
}

// ErrNoSMS: no SMS provider is configured on this server.
var ErrNoSMS = errors.New("loans: no SMS provider is configured")
