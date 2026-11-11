package loans

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Worker sends the outbox: each lender's referral notification, staff alerts
// when a delivery fails, and daily follow-up reminders. It runs inside the
// gateway process; any number of instances may run, since tasks are leased
// (FOR UPDATE SKIP LOCKED) one instance at a time.
type Worker struct {
	store   *Store
	mailer  Mailer
	baseURL string
	logger  *slog.Logger
	now     func() time.Time
}

// NewWorker returns the delivery worker. mailer may be nil (none configured).
func NewWorker(store *Store, mailer Mailer, baseURL string, logger *slog.Logger, now func() time.Time) *Worker {
	if now == nil {
		now = time.Now
	}
	return &Worker{store: store, mailer: mailer, baseURL: strings.TrimRight(baseURL, "/"), logger: logger, now: now}
}

// Delivery timing.
const (
	pollInterval      = 15 * time.Second
	leaseLength       = 2 * time.Minute
	batchSize         = 10
	accessLifetime    = 14 * 24 * time.Hour
	noProviderRetry   = 15 * time.Minute
	reminderInterval  = time.Hour
	maxDeliveryErrLen = 300
)

// retryAfter is the wait before attempt n+1; past its end a task fails.
var retryAfter = []time.Duration{
	time.Minute, 5 * time.Minute, 15 * time.Minute, time.Hour, 3 * time.Hour, 6 * time.Hour,
}

// Run sends due tasks until ctx ends. ready says whether school_loans is
// migrated; until it is, the worker waits without sending.
func (w *Worker) Run(ctx context.Context, ready func(context.Context) error) {
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	lastReminders, warned := time.Time{}, false
	for {
		if err := ready(ctx); err != nil {
			if !warned && ctx.Err() == nil {
				w.logger.Warn("loans: delivery worker waiting for school_loans", slog.String("error", err.Error()))
				warned = true
			}
		} else if _, err := w.RunOnce(ctx); err != nil && ctx.Err() == nil {
			w.logger.Error("loans: delivery run failed", slog.String("error", err.Error()))
		}
		if !warned && w.now().Sub(lastReminders) >= reminderInterval {
			if err := w.store.QueueFollowUpReminders(ctx, w.now()); err != nil && ctx.Err() == nil {
				w.logger.Error("loans: queueing reminders failed", slog.String("error", err.Error()))
			}
			lastReminders = w.now()
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// RunOnce sends the tasks due now and says how many it handled.
func (w *Worker) RunOnce(ctx context.Context) (int, error) {
	tasks, err := w.store.leaseTasks(ctx, w.now())
	if err != nil {
		return 0, err
	}
	for _, t := range tasks {
		if err := w.deliver(ctx, t); err != nil {
			w.logger.Error("loans: delivering a task", slog.String("task", t.ID), slog.String("kind", t.Kind),
				slog.String("error", err.Error()))
		}
	}
	return len(tasks), nil
}

func (w *Worker) deliver(ctx context.Context, t leasedTask) error {
	if w.mailer == nil {
		// Not a failure of the lender's address: the task waits, staff see
		// it waiting, and it goes as soon as a provider is configured.
		return w.store.retryTask(ctx, t, w.now().Add(noProviderRetry), ErrNoMailer.Error(), false)
	}
	switch t.Kind {
	case TaskLenderReferral:
		return w.deliverReferral(ctx, t)
	case TaskStaffAlert, TaskFollowUpRemind:
		message, err := w.store.staffMessage(ctx, t, w.baseURL)
		if err != nil {
			return w.store.failTask(ctx, t, err.Error())
		}
		if _, err := w.mailer.Send(ctx, message); err != nil {
			return w.retryOrFail(ctx, t, err)
		}
		return w.store.markTaskSent(ctx, t, "", w.now())
	}
	return w.store.failTask(ctx, t, "unknown task kind "+t.Kind)
}

func (w *Worker) deliverReferral(ctx context.Context, t leasedTask) error {
	if w.baseURL == "" {
		return w.store.retryTask(ctx, t, w.now().Add(noProviderRetry),
			"EDIFY_PUBLIC_BASE_URL is not set, so no link can be sent", false)
	}
	referral, err := w.store.referralForDelivery(ctx, t.ApplicationID)
	if err != nil {
		return w.store.failReferral(ctx, t, "The application could not be read: "+err.Error(), w.now())
	}
	if !IsOpen(referral.Status) {
		return w.store.cancelTask(ctx, t, "The application is "+StatusLabel(referral.Status)+".")
	}
	// The lender's address now, not when the application arrived: a
	// corrected address is used on the next attempt.
	lender, err := eligibleLender(ctx, w.store.db, referral.PartnerID)
	if errors.Is(err, ErrLenderUnavailable) {
		return w.store.failReferral(ctx, t,
			"The lender is not receiving referrals now or has no confirmed receiving address.", w.now())
	}
	if err != nil {
		return w.retryOrFail(ctx, t, err)
	}
	token, err := w.store.issueAccess(ctx, lender, t.ApplicationID, w.now())
	if err != nil {
		return w.retryOrFail(ctx, t, err)
	}
	link := w.baseURL + "/lender/referrals?t=" + url.QueryEscape(token)
	expires := w.now().Add(accessLifetime)
	message := Message{
		To:      lender.DeliveryEmail,
		Subject: "New school loan application " + referral.Reference + " from Edify",
		Text: fmt.Sprintf(`Hello %s,

Edify has a new school loan application for you.

Reference: %s
Received by Edify: %s

Open it here (a one-time code will be sent to this address before it opens):
%s

This link works until %s. Please do not forward this email: the
application is addressed to %s only.

Edify School Loans
`, lender.Name, referral.Reference, longMoment(referral.SubmittedAt), link, longDay(expires), lender.Name),
	}
	providerID, err := w.mailer.Send(ctx, message)
	if err != nil {
		return w.retryOrFail(ctx, t, err)
	}
	return w.store.markReferralSent(ctx, t, lender, providerID, w.mailer.Channel(), w.now())
}

func (w *Worker) retryOrFail(ctx context.Context, t leasedTask, cause error) error {
	reason := cause.Error()
	if len(reason) > maxDeliveryErrLen {
		reason = reason[:maxDeliveryErrLen]
	}
	if t.Attempts > len(retryAfter) {
		if t.Kind == TaskLenderReferral {
			return w.store.failReferral(ctx, t, "Sending failed after repeated attempts: "+reason, w.now())
		}
		return w.store.failTask(ctx, t, reason)
	}
	return w.store.retryTask(ctx, t, w.now().Add(retryAfter[t.Attempts-1]), reason, true)
}

type leasedTask struct {
	ID              string
	Kind            string
	ApplicationID   string
	PartnerID       string
	RecipientUserID string
	Recipient       string
	Attempts        int
	DedupeKey       string
}

func (s *Store) leaseTasks(ctx context.Context, now time.Time) ([]leasedTask, error) {
	var tasks []leasedTask
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		rows, err := tx.Query(ctx, `
UPDATE school_loans.delivery_task SET lease_until = $2, attempts = attempts + 1, updated_at = $1
WHERE id IN (
  SELECT id FROM school_loans.delivery_task
  WHERE status = 'pending' AND next_attempt_at <= $1 AND (lease_until IS NULL OR lease_until < $1)
  ORDER BY next_attempt_at LIMIT $3 FOR UPDATE SKIP LOCKED)
RETURNING id, kind, COALESCE(application_id::text, ''), partner_id, recipient_user_id, recipient_email,
  attempts, dedupe_key`,
			now, now.Add(leaseLength), batchSize)
		if err != nil {
			return fmt.Errorf("loans: leasing tasks: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var t leasedTask
			if err := rows.Scan(&t.ID, &t.Kind, &t.ApplicationID, &t.PartnerID, &t.RecipientUserID, &t.Recipient,
				&t.Attempts, &t.DedupeKey); err != nil {
				return err
			}
			tasks = append(tasks, t)
		}
		return rows.Err()
	})
	return tasks, err
}

// retryTask puts a task back for later. countsAgainst false gives the
// attempt back (a missing provider is not the lender's failure).
func (s *Store) retryTask(ctx context.Context, t leasedTask, at time.Time, reason string, countsAgainst bool) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
UPDATE school_loans.delivery_task
SET next_attempt_at = $2, lease_until = NULL, last_error = $3,
  attempts = CASE WHEN $4 THEN attempts ELSE attempts - 1 END, updated_at = now()
WHERE id = $1`, t.ID, at, reason, countsAgainst)
		return err
	})
}

func (s *Store) failTask(ctx context.Context, t leasedTask, reason string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
UPDATE school_loans.delivery_task SET status = 'failed', lease_until = NULL, last_error = $2, updated_at = now()
WHERE id = $1`, t.ID, reason)
		return err
	})
}

func (s *Store) cancelTask(ctx context.Context, t leasedTask, reason string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
UPDATE school_loans.delivery_task SET status = 'cancelled', lease_until = NULL, last_error = $2, updated_at = now()
WHERE id = $1`, t.ID, reason)
		return err
	})
}

func (s *Store) markTaskSent(ctx context.Context, t leasedTask, providerID string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
UPDATE school_loans.delivery_task
SET status = 'sent', sent_at = $2, provider_message_id = $3, lease_until = NULL, last_error = '', updated_at = $2
WHERE id = $1`, t.ID, now, providerID)
		return err
	})
}

type referralForDelivery struct {
	Reference   string
	PartnerID   string
	Status      string
	SubmittedAt time.Time
}

func (s *Store) referralForDelivery(ctx context.Context, applicationID string) (referralForDelivery, error) {
	var r referralForDelivery
	err := s.db.QueryRow(ctx, `
SELECT reference, partner_id, status, submitted_at FROM school_loans.application WHERE id = $1`, applicationID).
		Scan(&r.Reference, &r.PartnerID, &r.Status, &r.SubmittedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return r, ErrNotFound
	}
	return r, err
}

// issueAccess records a lender link token for one referral and returns it.
func (s *Store) issueAccess(ctx context.Context, lender Lender, applicationID string, now time.Time) (string, error) {
	token, err := NewToken()
	if err != nil {
		return "", err
	}
	id, err := NewID()
	if err != nil {
		return "", err
	}
	var application *string
	if applicationID != "" {
		application = &applicationID
	}
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
INSERT INTO school_loans.lender_access (id, partner_id, application_id, token_hash, email, expires_at, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7)`,
			id, lender.PartnerID, application, HashToken(token), lender.DeliveryEmail, now.Add(accessLifetime), now)
		return err
	})
	return token, err
}

// markReferralSent records that the provider accepted the notification:
// delivery becomes Notification sent and the application Awaiting Lender
// Receipt. It never says the lender received or opened it.
func (s *Store) markReferralSent(ctx context.Context, t leasedTask, lender Lender, providerID, channel string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.delivery_task
SET status = 'sent', sent_at = $2, provider_message_id = $3, recipient_email = $4, lease_until = NULL,
  last_error = '', updated_at = $2
WHERE id = $1`, t.ID, now, providerID, lender.DeliveryEmail); err != nil {
			return err
		}
		var from string
		err := tx.QueryRow(ctx, `
UPDATE school_loans.application a
SET delivery_status = CASE WHEN a.delivery_status = 'opened_by_lender' THEN a.delivery_status ELSE 'sent' END,
  status = CASE WHEN a.status = 'submitted' THEN 'awaiting_lender_receipt' ELSE a.status END,
  updated_at = $2
FROM school_loans.application prior
WHERE a.id = $1 AND prior.id = a.id
RETURNING prior.status`, t.ApplicationID, now).Scan(&from)
		if err != nil {
			return err
		}
		to := from
		if from == StatusSubmitted {
			to = StatusAwaitingReceipt
		}
		return appendEvent(ctx, tx, Event{
			ApplicationID: t.ApplicationID, Kind: "delivery_sent", ActorKind: "system",
			FromStatus: from, ToStatus: to,
			Note: "Notification sent to " + lender.Name + " at " + maskEmail(lender.DeliveryEmail) + " (" + channel + ").",
		})
	})
}

// failReferral marks the notification failed, keeps the application, and
// alerts the staff who can correct the address or resend.
func (s *Store) failReferral(ctx context.Context, t leasedTask, reason string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.delivery_task SET status = 'failed', lease_until = NULL, last_error = $2, updated_at = $3
WHERE id = $1`, t.ID, reason, now); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.application SET delivery_status = 'failed', updated_at = $2
WHERE id = $1 AND delivery_status IN ('queued', 'failed')`, t.ApplicationID, now); err != nil {
			return err
		}
		if err := appendEvent(ctx, tx, Event{
			ApplicationID: t.ApplicationID, Kind: "delivery_failed", ActorKind: "system", Note: reason,
		}); err != nil {
			return err
		}
		return queueStaffAlerts(ctx, tx, t.ApplicationID, now)
	})
}

// alertRoles are told when a delivery fails: the BTOs who follow
// applications up and the Country Director who manages lender addresses.
var alertRoles = []string{roleBTO, roleCountryDirector}

func queueStaffAlerts(ctx context.Context, tx pgx.Tx, applicationID string, now time.Time) error {
	rows, err := tx.Query(ctx, `
SELECT id, email FROM "user"
WHERE deleted_at IS NULL AND is_active AND status = 'active' AND email <> '' AND roles && $1::varchar[]`, alertRoles)
	if err != nil {
		return fmt.Errorf("loans: finding staff to alert: %w", err)
	}
	type recipient struct{ id, email string }
	var recipients []recipient
	for rows.Next() {
		var r recipient
		if err := rows.Scan(&r.id, &r.email); err != nil {
			rows.Close()
			return err
		}
		recipients = append(recipients, r)
	}
	rows.Close()
	for _, r := range recipients {
		if err := enqueue(ctx, tx, task{
			Kind: TaskStaffAlert, DedupeKey: "alert:" + applicationID + ":" + r.id + ":" + now.Format("2006-01-02"),
			ApplicationID: applicationID, RecipientUserID: r.id, Recipient: r.email, At: now,
		}); err != nil {
			return err
		}
	}
	return nil
}

// staffMessage composes a staff alert or reminder. Neither carries a
// director's details or a school's finances: staff open the app for those.
func (s *Store) staffMessage(ctx context.Context, t leasedTask, baseURL string) (Message, error) {
	switch t.Kind {
	case TaskStaffAlert:
		var reference, lender string
		if err := s.db.QueryRow(ctx, `SELECT reference, lender_name FROM school_loans.application WHERE id = $1`,
			t.ApplicationID).Scan(&reference, &lender); err != nil {
			return Message{}, err
		}
		return Message{
			To:      t.Recipient,
			Subject: "Loan application " + reference + " could not be sent to " + lender,
			Text: "Edify could not send school loan application " + reference + " to " + lender + ".\n\n" +
				"The application is safe. Open Loan Referrals in the Edify app to correct the lender's\n" +
				"receiving address (Country Director) or send it again (BTO).\n\nEdify School Loans\n",
		}, nil
	case TaskFollowUpRemind:
		var count int
		if err := s.db.QueryRow(ctx, `
SELECT count(*) FROM school_loans.application
WHERE responsible_bto_id = $1 AND next_follow_up_on < $2
  AND status NOT IN ('declined', 'disbursed', 'closed', 'withdrawn')`, t.RecipientUserID, time.Now().In(kampala)).
			Scan(&count); err != nil {
			return Message{}, err
		}
		return Message{
			To:      t.Recipient,
			Subject: fmt.Sprintf("%d school loan follow-up(s) are overdue", count),
			Text: fmt.Sprintf("You have %d school loan application(s) whose follow-up date has passed.\n\n"+
				"Open Loan Referrals in the Edify app to follow them up.\n\nEdify School Loans\n", count),
		}, nil
	}
	return Message{}, fmt.Errorf("no message for %s", t.Kind)
}

// QueueFollowUpReminders queues one reminder a day for each BTO responsible
// for an application whose follow-up date has passed.
func (s *Store) QueueFollowUpReminders(ctx context.Context, now time.Time) error {
	today := now.In(kampala).Format("2006-01-02")
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		rows, err := tx.Query(ctx, `
SELECT DISTINCT a.responsible_bto_id, u.email
FROM school_loans.application a JOIN "user" u ON u.id = a.responsible_bto_id
WHERE a.responsible_bto_id <> '' AND a.next_follow_up_on < $1::date
  AND a.status NOT IN ('declined', 'disbursed', 'closed', 'withdrawn')
  AND u.deleted_at IS NULL AND u.is_active AND u.email <> ''`, today)
		if err != nil {
			return err
		}
		type recipient struct{ id, email string }
		var recipients []recipient
		for rows.Next() {
			var r recipient
			if err := rows.Scan(&r.id, &r.email); err != nil {
				rows.Close()
				return err
			}
			recipients = append(recipients, r)
		}
		rows.Close()
		for _, r := range recipients {
			if err := enqueue(ctx, tx, task{
				Kind: TaskFollowUpRemind, DedupeKey: "remind:" + r.id + ":" + today,
				RecipientUserID: r.id, Recipient: r.email, At: now,
			}); err != nil {
				return err
			}
		}
		return nil
	})
}
