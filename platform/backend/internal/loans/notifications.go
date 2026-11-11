package loans

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// School notifications: one history per application, shared by Edify staff,
// the lender's staff and the weekly reminders. Every message is chosen from
// an approved template, sent only to the phone on the application, held back
// inside a cooldown whoever sent the last one, and marked delivered only
// when the provider says so.

// templateVersion names the template texts below.
const templateVersion = "2026-11-11"

// Notification types.
const (
	NoteReceived     = "application_received"
	NoteUnderReview  = "application_under_review"
	NoteInfoRequired = "information_required"
	NoteAppointment  = "assessment_appointment"
	NoteAgreement    = "agreement_review"
	NoteDisbursed    = "disbursement_confirmation"
	NoteUpcoming     = "installment_upcoming"
	NoteDue          = "payment_due"
	NoteOverdue      = "payment_overdue"
	NoteReceipt      = "receipt_acknowledgment"
	NoteVerified     = "payment_verified"
	NoteSettled      = "loan_settled"
	NoteCollateral   = "collateral_release"
	NoteGeneral      = "general_follow_up"
	NoteStatement    = "statement_link"
)

// noteOrder is the order types are offered in.
var noteOrder = []string{NoteReceived, NoteUnderReview, NoteInfoRequired, NoteAppointment, NoteAgreement, NoteDisbursed,
	NoteUpcoming, NoteDue, NoteOverdue, NoteReceipt, NoteVerified, NoteSettled, NoteCollateral, NoteGeneral, NoteStatement}

// NoteLabels name the types.
var NoteLabels = map[string]string{
	NoteReceived: "Application Received", NoteUnderReview: "Application Under Review",
	NoteInfoRequired: "Additional Information Required", NoteAppointment: "Assessment Appointment Reminder",
	NoteAgreement: "Loan Agreement Review", NoteDisbursed: "Loan Disbursement Confirmation",
	NoteUpcoming: "Upcoming Installment Reminder", NoteDue: "Payment Due Reminder", NoteOverdue: "Overdue Payment Reminder",
	NoteReceipt: "Payment Receipt Acknowledgment", NoteVerified: "Payment Verification Confirmation",
	NoteSettled: "Loan Fully Settled", NoteCollateral: "Collateral Release Update", NoteGeneral: "General Loan Follow-up",
	NoteStatement: "Secure Statement Link",
}

// Placeholders in the templates.
const (
	slotLender    = "{lender}"
	slotReference = "{reference}"
	slotDate      = "{date}"
	slotAmount    = "{amount}"
	slotLink      = "{secure_link}"
)

// noteTemplates are the approved texts (owner's brief, staff loan tracking
// §7, where it gives one). Each names the lender; none says Edify lends.
// Balances are never put in a message.
var noteTemplates = map[string]string{
	NoteReceived:     "Edify: Your school loan application {reference} has been sent to {lender}. The lender will contact the school's director.",
	NoteUnderReview:  "Edify: Your school loan application {reference} is being processed by {lender}. For inquiries, contact the lender using the official contact details provided.",
	NoteInfoRequired: "{lender}: Please send the additional information requested for your school loan application {reference}. Contact your loan officer for details.",
	NoteAppointment:  "{lender}: Reminder of the school assessment visit for loan application {reference} on {date}. Contact your loan officer to change it.",
	NoteAgreement:    "{lender} has proposed terms for your school loan {reference}. Review them here (a code will be sent to you): {secure_link}",
	NoteDisbursed:    "{lender}: Your school loan {reference} has been disbursed. View your statement securely: {secure_link}",
	NoteUpcoming:     "Reminder from {lender}: Your school loan installment is due on {date}. Please check your secure statement or contact your loan officer for assistance. {secure_link}",
	NoteDue:          "Reminder from {lender}: Your school loan installment is due on {date}. Please check your secure statement or contact your loan officer for assistance. {secure_link}",
	NoteOverdue:      "{lender} repayment reminder: Our records indicate a payment may be overdue. Please check your secure loan statement or contact your loan officer. {secure_link}",
	NoteReceipt:      "{lender}: We have received your payment receipt for loan {reference} and are checking it. It counts towards your balance once verified.",
	NoteVerified:     "{lender}: Your loan payment of UGX {amount} on {date} has been verified. View your updated statement securely: {secure_link}",
	NoteSettled:      "{lender}: Your school loan is fully settled according to our verified records. Please follow up on any outstanding collateral release process.",
	NoteCollateral:   "{lender}: An update on the release of your loan security for {reference}. Please contact your loan officer to arrange it.",
	NoteGeneral:      "Edify: Your school loan application {reference} is being processed by {lender}. For inquiries, contact the lender using the official contact details provided.",
	NoteStatement:    "Edify: Your school loan statement with {lender} is ready. Open it here (a code will be sent to you): {secure_link}",
}

// linkedNotes carry a fresh statement or agreement link, issued on sending.
var linkedNotes = map[string]string{NoteAgreement: "agreement", NoteDisbursed: "statement", NoteUpcoming: "statement",
	NoteDue: "statement", NoteOverdue: "statement", NoteVerified: "statement", NoteStatement: "statement"}

// lenderOnlyNotes are the lender's own to send: they speak for its
// finance and credit decisions.
var lenderOnlyNotes = map[string]bool{NoteAgreement: true, NoteReceipt: true, NoteVerified: true, NoteCollateral: true,
	NoteStatement: true}

// transactionalNotes answer something the lender has just done (sent new
// terms, received or verified a payment): they skip the per-kind cooldown
// but still count towards the school's daily and weekly limits.
var transactionalNotes = map[string]bool{NoteAgreement: true, NoteReceipt: true, NoteVerified: true}

// Sending limits, the same for everyone.
const (
	maxPerSchoolPerDay  = 2
	maxPerSchoolPerWeek = 5
)

// Sender is who is sending: Edify staff, a lender's staff, or the system.
type Sender struct {
	ID, Name, Role, Organisation string
	IsLender, CanOverride        bool
}

// noteFacts are what a case's notifications may say.
type noteFacts struct {
	date, amount string
}

// eligibleNotes are the types the case's recorded state supports for this
// sender, with the facts each would carry. A disbursement or payment
// notification needs the ledger to show it: a note or a receipt is not enough.
func (c *caseData) eligibleNotes(sender Sender) map[string]noteFacts {
	out := map[string]noteFacts{}
	r := c.record
	stage := c.stage()
	if stage == StageClosed {
		return out
	}
	open := stage != StageDeclined
	// Still with the lender: not decided, not paid out (by the ledger or as
	// the lender reported it).
	inProcess := open && !c.disbursed() && r.LatestDecision() == nil &&
		r.Referral.Status != StatusApproved && r.Referral.Status != StatusDisbursed
	if inProcess && (r.Referral.DeliveryStatus == DeliverySent || r.Referral.DeliveryStatus == DeliveryOpened) {
		out[NoteReceived] = noteFacts{}
	}
	if inProcess && r.Assignment != nil {
		out[NoteUnderReview] = noteFacts{}
	}
	if open && (r.Referral.Status == StatusInformationRequested || (r.Assessment != nil && r.Assessment.Status == "information_required")) {
		out[NoteInfoRequired] = noteFacts{}
	}
	for _, contact := range r.Contacts {
		if contact.VisitOn != nil && !contact.VisitOn.Before(c.today) && open && !c.disbursed() {
			out[NoteAppointment] = noteFacts{date: day(*contact.VisitOn)}
		}
	}
	if a := r.LatestAgreement(); a != nil && a.Status == "issued" {
		out[NoteAgreement] = noteFacts{}
	}
	if c.disbursed() {
		out[NoteDisbursed] = noteFacts{}
		out[NoteStatement] = noteFacts{}
		p := c.position
		switch {
		case p.Status == ledger.StatusSettled:
			out[NoteSettled] = noteFacts{}
		case p.AmountOverdue > 0:
			out[NoteOverdue] = noteFacts{}
		case p.NextDue != nil && !p.NextDue.DueDate.After(c.today.AddDate(0, 0, dueWindowDays)):
			out[NoteDue] = noteFacts{date: day(p.NextDue.DueDate)}
			out[NoteUpcoming] = noteFacts{date: day(p.NextDue.DueDate)}
		}
		if len(c.pendingEvidence()) > 0 {
			out[NoteReceipt] = noteFacts{}
		}
		reversed := c.book.ReversedBy(c.today)
		for index := len(c.book.Payments) - 1; index >= 0; index-- {
			payment := c.book.Payments[index]
			if payment.Kind == ledger.KindPayment && !reversed[payment.ID] {
				var applied ledger.Money
				for _, a := range payment.Allocations {
					applied += a.Amount
				}
				out[NoteVerified] = noteFacts{date: day(payment.ValueDate), amount: strings.TrimPrefix(ugx(applied), "UGX ")}
				break
			}
		}
	}
	if len(r.Collateral) > 0 && c.settled() {
		out[NoteCollateral] = noteFacts{}
	}
	if inProcess {
		out[NoteGeneral] = noteFacts{}
	}
	if !sender.IsLender {
		for kind := range lenderOnlyNotes {
			delete(out, kind)
		}
	}
	return out
}

// notifyNote says, in a line, why nothing can be sent for the case right
// now; it is empty when something can.
func (c *caseData) notifyNote(sender Sender) string {
	if len(c.eligibleNotes(sender)) > 0 {
		return ""
	}
	r := c.record
	switch {
	case c.stage() == StageClosed:
		return "The loan is closed. There is nothing to send."
	case c.stage() == StageDeclined:
		return "The application was declined. The lender tells the school."
	case r.Referral.Status == StatusDisbursed && !c.disbursed():
		return "Nothing to send until the lender records the disbursement in the ledger."
	case r.LatestDecision() != nil || r.Referral.Status == StatusApproved:
		return "Approved. The next notification is the disbursement, once the ledger shows it."
	default:
		return "No notification fits what is recorded for this loan yet."
	}
}

// renderNote fills a template.
func renderNote(kind string, c *caseData, facts noteFacts, link string) string {
	return strings.NewReplacer(slotLender, c.record.Referral.LenderName, slotReference, c.record.Referral.Reference,
		slotDate, facts.date, slotAmount, facts.amount, slotLink, link).Replace(noteTemplates[kind])
}

// NoteRecord is one notification as people see it.
type NoteRecord struct {
	ID, Type, Recipient, Body, TriggeredByName, SenderRole, Organisation, Status, Failure, ExceptionReason string
	CreatedAt                                                                                              time.Time
}

// Notifications are an application's notifications, newest first.
func (s *Store) Notifications(ctx context.Context, applicationID string, limit int) ([]NoteRecord, error) {
	rows, err := s.db.Query(ctx, `
SELECT id::text, type, recipient, body, triggered_by_name, sender_role, sending_organisation, status,
  CASE WHEN failure_category <> '' THEN failure_category ELSE '' END, exception_reason, created_at
FROM school_loans.notification WHERE application_id = $1 ORDER BY created_at DESC LIMIT $2`, applicationID, limit)
	if err != nil {
		return nil, fmt.Errorf("loans: reading notifications: %w", err)
	}
	defer rows.Close()
	var out []NoteRecord
	for rows.Next() {
		var n NoteRecord
		if err := rows.Scan(&n.ID, &n.Type, &n.Recipient, &n.Body, &n.TriggeredByName, &n.SenderRole, &n.Organisation,
			&n.Status, &n.Failure, &n.ExceptionReason, &n.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, rows.Err()
}

// cooldown says why a notification of this kind may not go now: one of the
// kind inside the cooldown (overridable with a reason), or the school's
// daily or weekly limit (never overridable).
func (s *Store) cooldown(ctx context.Context, q rowQuerier, applicationID, kind string, cooldownDays int, now time.Time) (sameKind, limit string, err error) {
	var lastAt *time.Time
	var lastBy string
	var today, week int
	err = q.QueryRow(ctx, `
SELECT (SELECT max(created_at) FROM school_loans.notification
        WHERE application_id = $1 AND type = $2 AND status <> 'suppressed' AND created_at > $3),
  COALESCE((SELECT triggered_by_name FROM school_loans.notification
        WHERE application_id = $1 AND type = $2 AND status <> 'suppressed' ORDER BY created_at DESC LIMIT 1), ''),
  (SELECT count(*) FROM school_loans.notification WHERE application_id = $1 AND status <> 'suppressed' AND created_at > $4),
  (SELECT count(*) FROM school_loans.notification WHERE application_id = $1 AND status <> 'suppressed' AND created_at > $5)`,
		applicationID, kind, now.AddDate(0, 0, -cooldownDays), now.Add(-24*time.Hour), now.AddDate(0, 0, -7)).
		Scan(&lastAt, &lastBy, &today, &week)
	if err != nil {
		return "", "", fmt.Errorf("loans: checking the notification cooldown: %w", err)
	}
	switch {
	case today >= maxPerSchoolPerDay:
		limit = fmt.Sprintf("This school has had %d messages today, the most it may receive in a day.", today)
	case week >= maxPerSchoolPerWeek:
		limit = fmt.Sprintf("This school has had %d messages this week, the most it may receive in a week.", week)
	}
	if lastAt != nil {
		by := lastBy
		if by == "" || by == "system" {
			by = "the weekly reminder"
		}
		sameKind = fmt.Sprintf("Sent %s by %s; the next may go after %d days.", lastAt.In(kampala).Format("2 Jan 15:04"), by, cooldownDays)
	}
	return sameKind, limit, nil
}

// NoteDraft is a notification about to be queued.
type NoteDraft struct {
	ApplicationID, SchoolID, LoanID, Type, Recipient, RecipientName, Body string
	ExceptionReason, FollowUpID, DedupeKey                                string
}

// ErrNoteDuplicate: the same notification is already queued or sent.
var ErrNoteDuplicate = errors.New("loans: this notification was already sent")

// QueueNote checks the limits and queues a notification in one
// transaction, so two people pressing Send together cannot both pass.
// An opted-out number is recorded as suppressed, not sent.
func (s *Store) QueueNote(ctx context.Context, draft NoteDraft, sender Sender, cooldownDays int, now time.Time) (string, string, error) {
	id, err := NewID()
	if err != nil {
		return "", "", err
	}
	status := "queued"
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		// One sender at a time per application.
		if _, err := tx.Exec(ctx, `SELECT 1 FROM school_loans.application WHERE id = $1 FOR UPDATE`, draft.ApplicationID); err != nil {
			return err
		}
		sameKind, limit, err := s.cooldown(ctx, tx, draft.ApplicationID, draft.Type, cooldownDays, now)
		if err != nil {
			return err
		}
		if transactionalNotes[draft.Type] {
			sameKind = ""
		}
		switch {
		case limit != "":
			return need("type", limit)
		case sameKind != "" && draft.ExceptionReason == "":
			return need("type", sameKind)
		case sameKind != "" && !sender.CanOverride:
			return need("type", sameKind+" Only the BTO, the Country Director or the lender's administrator may send it sooner.")
		}
		var optedOut bool
		if err := tx.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM school_loans.sms_preference WHERE phone = $1 AND opted_out_at IS NOT NULL)`, draft.Recipient).
			Scan(&optedOut); err != nil {
			return err
		}
		failure := ""
		if optedOut {
			status, failure = "suppressed", "opted_out"
		}
		var school, loan, followUp *string
		if draft.SchoolID != "" {
			school = &draft.SchoolID
		}
		if draft.LoanID != "" {
			loan = &draft.LoanID
		}
		if draft.FollowUpID != "" {
			followUp = &draft.FollowUpID
		}
		tag, err := tx.Exec(ctx, `
INSERT INTO school_loans.notification (id, application_id, school_id, mfi_loan_id, type, recipient, recipient_name, body,
  template_version, triggered_by, triggered_by_name, sender_role, sending_organisation, exception_reason,
  related_follow_up_id, dedupe_key, status, failure_category, next_attempt_at, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15::uuid, $16, $17, $18, $19, $19, $19)
ON CONFLICT (dedupe_key) DO NOTHING`, id, draft.ApplicationID, school, loan, draft.Type, draft.Recipient, draft.RecipientName,
			draft.Body, templateVersion, sender.ID, sender.Name, sender.Role, sender.Organisation, draft.ExceptionReason,
			followUp, draft.DedupeKey, status, failure, now)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return ErrNoteDuplicate
		}
		note := NoteLabels[draft.Type] + " queued to the school."
		if status == "suppressed" {
			note = NoteLabels[draft.Type] + " not sent: the school's number has opted out of messages."
		}
		return appendEvent(ctx, tx, Event{ApplicationID: draft.ApplicationID, Kind: "notification", ActorKind: actorKindOf(sender),
			ActorID: sender.ID, ActorName: sender.Name, Note: note})
	})
	return id, status, err
}

func actorKindOf(sender Sender) string {
	switch {
	case sender.ID == "system":
		return "system"
	case sender.IsLender:
		return "lender"
	}
	return "staff"
}

// deliveryStatusLabels word a notification's delivery honestly.
var deliveryStatusLabels = map[string]string{
	"queued": "Queued", "submitted": "Handed to the SMS provider", "delivered": "Delivered",
	"failed": "Failed", "suppressed": "Not sent (opted out)",
}

var deliveryTones = map[string]string{"queued": "info", "submitted": "info", "delivered": "good", "failed": "alert", "suppressed": "caution"}

// failureLabels explain a failure category.
var failureLabels = map[string]string{
	"provider_refused": "The SMS provider refused it", "provider_unreachable": "The SMS provider could not be reached",
	"undeliverable": "The phone network could not deliver it", "opted_out": "The number has opted out",
	"no_provider": "No SMS provider is set up on this server",
}

// sendSchoolNote renders, links and queues a notification for a case.
func (l *Lending) sendSchoolNote(ctx context.Context, c *caseData, kind string, sender Sender, exception, followUpID string) (string, string, error) {
	facts, ok := c.eligibleNotes(sender)[kind]
	if !ok {
		return "", "", need("type", "That notification does not fit this loan's present state.")
	}
	phone := c.record.Referral.DirectorPhone
	if phone == "" {
		return "", "", need("type", "The application has no director's phone to send to.")
	}
	link := ""
	if purpose, linked := linkedNotes[kind]; linked {
		base, err := publicLink(l.cfg.PublicBaseURL, "")
		if err != nil {
			return "", "", need("type", "This server has no HTTPS public address set, so it cannot send a secure link.")
		}
		token, err := l.store.IssueSchoolAccess(ctx, c.record.Referral.ID, purpose, "sms", phone, sender.ID, l.now())
		if err != nil {
			return "", "", err
		}
		link = base + "/loan/" + purpose + "?t=" + token
	}
	loanID := ""
	if c.loan != nil {
		loanID = c.loan.ID
	}
	moment := l.now().In(kampala)
	key := fmt.Sprintf("note:%s:%s:%s", c.record.Referral.ID, kind, moment.Format("2006-01-02"))
	if exception != "" {
		key += ":" + moment.Format("150405.000")
	}
	return l.store.QueueNote(ctx, NoteDraft{ApplicationID: c.record.Referral.ID, SchoolID: c.record.Referral.SchoolDirectoryID,
		LoanID: loanID, Type: kind, Recipient: phone, RecipientName: c.record.Referral.DirectorName,
		Body: renderNote(kind, c, facts, link), ExceptionReason: exception, FollowUpID: followUpID, DedupeKey: key},
		sender, l.cooldownDays(), l.now())
}

func (l *Lending) cooldownDays() int {
	if l.cfg.ReminderCooldownDays > 0 {
		return l.cfg.ReminderCooldownDays
	}
	return 7
}

// SendDueNotes hands queued notifications to the SMS provider, keeping every
// attempt. Without a provider they wait, and say so; nothing is called sent
// that the provider did not accept.
func (w *SMSWorker) SendDueNotes(ctx context.Context) (int, error) {
	type due struct {
		id, recipient, body string
		attempts            int
	}
	if w.provider == nil {
		return 0, w.store.inWrite(ctx, func(tx pgx.Tx) error {
			_, err := tx.Exec(ctx, `
UPDATE school_loans.notification SET failure_category = 'no_provider', updated_at = $1
WHERE status = 'queued' AND failure_category = ''`, w.now())
			return err
		})
	}
	var batch []due
	err := w.store.inWrite(ctx, func(tx pgx.Tx) error {
		rows, err := tx.Query(ctx, `
UPDATE school_loans.notification SET lease_until = $2, attempts = attempts + 1, failure_category = '', updated_at = $1
WHERE id IN (SELECT id FROM school_loans.notification
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
			outcome, message := "submitted", ""
			switch {
			case sendErr == nil:
				if _, err := tx.Exec(ctx, `
UPDATE school_loans.notification SET status = 'submitted', provider = $2, provider_message_id = $3, submitted_at = $4,
  lease_until = NULL, last_error = '', updated_at = $4 WHERE id = $1`, d.id, w.provider.Name(), providerID, w.now()); err != nil {
					return err
				}
			case d.attempts >= smsRetries:
				outcome, message = "failed", truncate(sendErr.Error(), 300)
				if _, err := tx.Exec(ctx, `
UPDATE school_loans.notification SET status = 'failed', failure_category = 'provider_refused', lease_until = NULL,
  last_error = $2, updated_at = $3 WHERE id = $1`, d.id, message, w.now()); err != nil {
					return err
				}
			default:
				outcome, message = "retry", truncate(sendErr.Error(), 300)
				if _, err := tx.Exec(ctx, `
UPDATE school_loans.notification SET lease_until = NULL, last_error = $2, failure_category = 'provider_unreachable',
  next_attempt_at = $3, updated_at = $4 WHERE id = $1`,
					d.id, message, w.now().Add(time.Duration(d.attempts*d.attempts)*5*time.Minute), w.now()); err != nil {
					return err
				}
			}
			return noteAttempt(ctx, tx, d.id, outcome, message)
		})
		if err != nil {
			return 0, err
		}
	}
	return len(batch), nil
}

func noteAttempt(ctx context.Context, tx pgx.Tx, notificationID, outcome, message string) error {
	id, err := NewID()
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `
INSERT INTO school_loans.notification_attempt (id, notification_id, outcome, error) VALUES ($1, $2, $3, $4)`,
		id, notificationID, outcome, message)
	return err
}

// noteDeliveryReport applies a provider's delivery report to a notification.
func noteDeliveryReport(ctx context.Context, tx pgx.Tx, providerID, next, reported string) error {
	failure := ""
	if next == "failed" {
		failure = "undeliverable"
	}
	var id string
	err := tx.QueryRow(ctx, `
UPDATE school_loans.notification SET status = $2, delivered_at = CASE WHEN $2 = 'delivered' THEN now() ELSE delivered_at END,
  failure_category = CASE WHEN $3 <> '' THEN $3 ELSE failure_category END, updated_at = now()
WHERE provider_message_id = $1 AND status IN ('submitted', 'delivered', 'failed') RETURNING id::text`, providerID, next, failure).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	outcome := "delivered"
	if next == "failed" {
		outcome = "undeliverable"
	}
	return noteAttempt(ctx, tx, id, outcome, "Delivery report: "+reported)
}
