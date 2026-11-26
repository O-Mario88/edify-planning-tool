package partnerpayments

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// The partner's own invoice document, downloaded by Finance from Partner
// Payments (finance_operating_views.partner_invoice_download) and by the
// Programme Lead from Fund Approvals (extended_views.
// pl_partner_invoice_download), both over partner_invoices.invoice_file.

var documentPath = regexp.MustCompile(`^/(?:accounts/partner-invoices|fund-approvals/invoices)/([A-Za-z0-9]{1,30})/download$`)

const (
	invoiceNotFound   = "Invoice not found."
	invoiceNotYours   = "You are not authorized to download this invoice."
	invoiceNoDocument = "This invoice was written by the platform and has no attached document. Open the invoice to read or print it."
)

// Files reads a kept private file (privatestore.Store).
type Files interface {
	Get(ctx context.Context, namespace, name string) ([]byte, error)
}

// DocumentRoute names the download for its two paths.
func DocumentRoute(db schooldirectory.Querier, files Files) func(string) (func(context.Context, auth.Principal, url.Values) (string, []byte, bool, error), bool) {
	return func(target string) (func(context.Context, auth.Principal, url.Values) (string, []byte, bool, error), bool) {
		m := documentPath.FindStringSubmatch(target)
		if m == nil {
			return nil, false
		}
		return func(ctx context.Context, p auth.Principal, _ url.Values) (string, []byte, bool, error) {
			return document(ctx, db, files, p, target, m[1])
		}, true
	}
}

func document(ctx context.Context, db schooldirectory.Querier, files Files, p auth.Principal, target, id string) (string, []byte, bool, error) {
	if p.InActingAppointment {
		return "", nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, target) {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	var stored, original string
	var leadUser *string
	var hasLead bool
	err := db.QueryRow(ctx, `SELECT COALESCE(i.stored_name, ''), COALESCE(i.original_name, ''), i.program_lead_staff_id IS NOT NULL,
  (SELECT sp.user_id FROM staff_profile sp WHERE sp.id = i.program_lead_staff_id)
FROM partner_invoice i WHERE i.id = $1`, id).Scan(&stored, &original, &hasLead, &leadUser)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil, true, workbook.BadRequest(invoiceNotFound)
	}
	if err != nil {
		return "", nil, true, fmt.Errorf("partnerpayments: reading the invoice: %w", err)
	}
	// _pl_may_act: Finance, or the Lead the invoice is addressed to.
	d := rules.Document
	switch {
	case in(d.FinanceRoles, p.ActiveRole):
	case p.ActiveRole != d.LeadRole:
		return "", nil, true, workbook.Refusal(invoiceNotYours)
	case !hasLead:
		// An invoice raised before it named its Lead: every Lead of its
		// schools reads it (invoice_routing), which Go does not resolve here.
		return "", nil, false, nil
	case leadUser == nil || *leadUser != p.UserID:
		return "", nil, true, workbook.Refusal(invoiceNotYours)
	}
	if stored == "" {
		return "", nil, true, workbook.BadRequest(invoiceNoDocument)
	}
	body, err := files.Get(ctx, d.Namespace, stored)
	if err != nil {
		return "", nil, true, fmt.Errorf("partnerpayments: reading the invoice document: %w", err)
	}
	return original, body, true, nil
}

func in(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
