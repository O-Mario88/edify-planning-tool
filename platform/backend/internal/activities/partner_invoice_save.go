package activities

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// The partner's invoice save (partner_views.partner_invoice_submit over
// partner_invoices.submit_invoice): the period's basis, one invoice and its
// lines for each Lead, and the Lead's notice. A document of the partner's
// own is optional; the feed's drawer posts none.

const (
	invoiceNothing     = "Nothing is invoiceable for that period — the advance may already be invoiced, or the work is not yet completed with its evidence and verified by IA."
	invoiceBadTotal    = "Enter the period's total cost as a whole number."
	invoiceStatus      = "submitted_to_pl"
	invoiceEvent       = "partner_invoice_submitted"
	invoiceNoticeTitle = "Partner invoice awaiting your confirmation"
	invoiceContext     = "PartnerInvoice"
	invoiceRoute       = "/dashboard"
	invoiceRouteLabel  = "View Dashboard"
	financeCategory    = "finance"
	highPriority       = "high"
)

// InvoiceSubmit is the invoice form as posted.
type InvoiceSubmit struct {
	Kind, Instalment, Anchor, EnteredTotal string
	// HasFile: the post carries the partner's own document, which Go does
	// not keep.
	HasFile bool
}

// isoDay is date.fromisoformat for the form's anchor: a YYYY-MM-DD day, the
// refusal Python gives an empty one, or false for a form Go leaves to
// Django (fromisoformat reads more spellings than Go does).
func isoDay(raw string) (time.Time, error, bool) {
	raw = truncateRunes(raw, 10)
	if raw == "" {
		return time.Time{}, refuse("Invalid isoformat string: ''"), true
	}
	day, err := time.Parse(time.DateOnly, raw)
	if err != nil {
		return time.Time{}, nil, false
	}
	return day, nil, true
}

// SubmitPartnerInvoice is submit_invoice for the organisations partnerIDs,
// or a refusal in the existing words, or ErrHandOn before anything is
// written. The caller has asked the page's door.
func (s *Service) SubmitPartnerInvoice(ctx context.Context, p auth.Principal, partnerIDs []string, req InvoiceSubmit, origin Origin) (Answer, error) {
	if req.HasFile {
		return Answer{}, handOn("an invoice with the partner's own document")
	}
	anchor, err, taken := isoDay(req.Anchor)
	if !taken {
		return Answer{}, handOn("an anchor day Go does not read")
	}
	if err != nil {
		return Answer{}, err
	}
	b, err := s.PartnerInvoiceBasis(ctx, partnerIDs, OrThenStrip(req.Kind, "month"), anchor, OrThenStrip(req.Instalment, invoiceAdvance))
	if err != nil {
		return Answer{}, err
	}
	if len(b.Items) == 0 {
		return Answer{}, refuse(invoiceNothing)
	}
	if req.EnteredTotal != "" {
		entered, err := strconv.ParseInt(req.EnteredTotal, 10, 64)
		if err != nil {
			return Answer{}, refuse(invoiceBadTotal)
		}
		if entered != b.SystemTotal {
			return Answer{}, refuse("The amount entered must equal the period's total planned cost of %s UGX — that is how the system links your invoice to the plan.",
				thousands(int(b.SystemTotal)))
		}
	}
	ids, err := s.writePartnerInvoices(ctx, p, b)
	if err != nil {
		return Answer{}, err
	}
	for i, g := range b.ByLead {
		s.noticeInvoice(ctx, p, ids[i], b, g, origin)
	}
	return Answer{ActivityID: ids[0], Message: invoiceSentMessage(b)}, nil
}

// OrThenStrip is Python's (value or fallback).strip(): the fallback only
// for an empty value, so one of spaces strips to empty.
func OrThenStrip(value, fallback string) string {
	if value == "" {
		value = fallback
	}
	return strings.TrimSpace(value)
}

// paidPartner is paid_partner_id: the delivering partner of partner work,
// else the facilitating partner.
func (it InvoiceItem) paidPartner() string {
	if it.delivery == "partner" {
		return it.assigned
	}
	return it.facilitating
}

// writePartnerInvoices is submit_invoice's transaction: an invoice for each
// Lead, its lines, kept equal to the plan.
func (s *Service) writePartnerInvoices(ctx context.Context, p auth.Principal, b *InvoiceBasis) ([]string, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return nil, fmt.Errorf("activities: opening the invoice: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	now := s.now()
	partner := b.Items[0].paidPartner()
	ids := make([]string, 0, len(b.ByLead))
	for _, g := range b.ByLead {
		id := cuid.New()
		var lead any
		if g.Lead != nil {
			lead = g.Lead.StaffID
		}
		if _, err := tx.Exec(ctx, `INSERT INTO partner_invoice (id, created_at, updated_at, partner_id, invoice_type, period_kind,
  period_start, period_end, system_total, entered_total, payable_amount, stored_name, original_name, mime_type, file_size,
  status, submitted_by, pl_confirmed_by, pl_confirmed_at, pl_note, program_lead_staff_id)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $8, $9, '', '', '', 0, $10, $11, NULL, NULL, '', $12)`,
			id, now, partner, b.Instalment, b.Kind, b.Start, b.End, g.SystemTotal, g.Payable, invoiceStatus, p.UserID, lead); err != nil {
			return nil, fmt.Errorf("activities: writing the invoice: %w", err)
		}
		for _, it := range g.Items {
			if _, err := tx.Exec(ctx, `INSERT INTO partner_invoice_item (id, created_at, updated_at, instalment, planned_amount,
  payable_amount, category, activity_id, invoice_id, payment_id) VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, NULL)`,
				cuid.New(), now, b.Instalment, it.Planned, it.Payable, it.Category, it.ActivityID, id); err != nil {
				return nil, fmt.Errorf("activities: writing an invoice line: %w", err)
			}
		}
		ids = append(ids, id)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("activities: committing the invoice: %w", err)
	}
	return ids, nil
}

// invoiceSentMessage is the view's confirmation.
func invoiceSentMessage(b *InvoiceBasis) string {
	label := "balance"
	if b.Instalment == invoiceAdvance {
		label = "50% advance"
	}
	what := "Invoice for " + b.Label + " sent"
	sentTo := "is with Edify's finance team for confirmation"
	if len(b.ByLead) > 1 {
		what = fmt.Sprintf("%d invoices for %s sent", len(b.ByLead), b.Label)
		sentTo = "is with each Programme Lead for confirmation"
	} else if l := b.ByLead[0].Lead; l != nil {
		sentTo = "is with " + l.Name + ", the Programme Lead, for confirmation"
	}
	return fmt.Sprintf("%s: the %s of UGX %s %s.", what, label, thousands(int(b.Payable)), sentTo)
}

// noticeInvoice is _notify_pls_of_invoice: the invoice's Lead, or every
// active Country Director when no Lead holds its schools. It never blocks
// the invoice.
func (s *Service) noticeInvoice(ctx context.Context, p auth.Principal, id string, b *InvoiceBasis, g InvoiceGroup, origin Origin) {
	var recipients []string
	var err error
	if g.Lead != nil {
		recipients, err = s.userIDs(ctx, `SELECT user_id FROM staff_profile WHERE id = $1 AND user_id IS NOT NULL`, g.Lead.StaffID)
	} else {
		recipients, err = s.userIDs(ctx, `SELECT id FROM "user" WHERE active_role = $1 AND is_active`, rules.PartnerInvoice.DirectorRole)
	}
	if err != nil || len(recipients) == 0 {
		if err != nil {
			s.logger.Warn("activities: the invoice's Lead was not read", "invoice", id, "err", err)
		}
		return
	}
	typeLabel := rules.PartnerInvoice.InvoiceTypeLabels[b.Instalment]
	people := make([]noticeRecipient, 0, len(recipients))
	for _, r := range recipients {
		people = append(people, noticeRecipient{id: r, route: invoiceRoute, label: invoiceRouteLabel})
	}
	notice := scheduledNotice{title: invoiceNoticeTitle, event: invoiceEvent, category: financeCategory, priority: highPriority,
		contextType: invoiceContext,
		body: fmt.Sprintf("A partner submitted a %s for %s (payable UGX %s). Confirm it against the plan on Fund Approvals.",
			typeLabel, b.Label, thousands(int(g.Payable)))}
	w := workflowNotices{db: s.db, push: s.noticePush, live: s.live, logger: s.logger}
	if err := w.sendTo(ctx, s.now(), id, p.UserID, origin, notice, people); err != nil {
		s.logger.Warn("activities: the invoice's Lead was not told", "invoice", id, "err", err)
	}
}

func (s *Service) userIDs(ctx context.Context, sql string, arg string) ([]string, error) {
	rows, err := s.db.Query(ctx, sql, arg)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}
