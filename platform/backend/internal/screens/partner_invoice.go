package screens

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"strings"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
)

// The partner's Send invoice drawer and its save (partner_views.
// partner_invoice_drawer, partner_invoice_submit), drawn and saved in Go
// with Django absent.

const (
	invoiceDrawerPath  = "/partner/invoices/new"
	invoicePageDenied  = "Access Denied: Your active role does not have permission to view Partner My Plan."
	invoiceIntro       = "The invoice is written from your plan: every activity in the period with its cost. It goes to the Programme Lead whose schools the work is for."
	invoiceNothingHead = "Nothing to invoice in this period"
	invoiceNothingAdv  = "All scheduled work here is already invoiced or paid, or is completed and invoiced in full instead. Try another period, or choose Full payment."
	invoiceNothingFull = "Work is paid in full once it is completed with its evidence and IA has verified it. Where a 50% advance is on an invoice still being processed, the rest follows when that invoice is paid."
	invoiceNoLead      = "No Programme Lead holds these schools yet"
	invoiceNoLeadNote  = "This invoice goes to Edify's finance team, who confirm it in the Lead's place."
	invoiceFileHelp    = "Attach it only if your organisation issues its own numbered invoice. The platform's invoice is what the Programme Lead confirms and the accountant pays."
)

// PartnerInvoicer is the invoice's basis and save (internal/activities.Service).
type PartnerInvoicer interface {
	PartnerInvoiceBasis(ctx context.Context, partnerIDs []string, kind string, anchor time.Time, instalment string) (*activities.InvoiceBasis, error)
	SubmitPartnerInvoice(ctx context.Context, p auth.Principal, partnerIDs []string, req activities.InvoiceSubmit, origin activities.Origin) (activities.Answer, error)
}

// WithPartnerInvoice makes the partner's invoice Go's with Django absent.
func (s *Service) WithPartnerInvoice(invoicer PartnerInvoicer) *Service {
	s.partnerInvoice = invoicer
	return s
}

func (s *Service) invoiceTaken(path string) (url.Values, bool) {
	if s.partnerInvoice == nil || s.existingApp != nil {
		return nil, false
	}
	pathOnly, rawQuery, _ := strings.Cut(path, "?")
	if strings.TrimSuffix(pathOnly, "/") != invoiceDrawerPath {
		return nil, false
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, false
	}
	return query, true
}

// invoiceToday is date.today() on the server's clock, in Kampala.
func (s *Service) invoiceToday() time.Time {
	now := time.Now()
	if s.now != nil {
		now = s.now()
	}
	l := now.In(activitiesZone)
	return time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
}

// activitiesZone is the zone the partner's days are read in.
var activitiesZone = func() *time.Location {
	zone, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return zone
}()

// invoiceDrawerInGo is partner_invoice_drawer.
func (s *Service) invoiceDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	query, ok := s.invoiceTaken(path)
	if !ok || p.InActingAppointment {
		return nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, invoiceDrawerPath) {
		return &screensv1.GetDrawerResponse{Refusal: invoicePageDenied}, true, nil
	}
	kind := activities.OrThenStrip(query.Get("period_kind"), "month")
	instalment := activities.OrThenStrip(query.Get("instalment"), "advance")
	anchor := s.invoiceToday()
	if raw := strings.TrimSpace(query.Get("anchor")); raw != "" {
		day, err := time.Parse(time.DateOnly, raw[:min(len(raw), 10)])
		if err != nil {
			// fromisoformat reads more spellings than Go; an unreadable one is today.
			return nil, false, nil
		}
		anchor = day
	}
	partners, err := partnerassigned.PartnerIDs(ctx, s.db, p)
	if err != nil {
		return nil, true, err
	}
	basis, err := s.partnerInvoice.PartnerInvoiceBasis(ctx, partners, kind, anchor, instalment)
	var refusal *activities.Refusal
	basisError := ""
	switch {
	case errors.As(err, &refusal):
		basis, basisError = nil, refusal.Message
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: invoiceDrawer(basis, basisError, kind, instalment, anchor)}, true, nil
}

// chosenOrFirst is the feed's reading of a select: the chosen option's value,
// else the first option's.
func chosenOrFirst(chosen string, options []*screensv1.DrawerOption) string {
	for _, o := range options {
		if o.GetValue() == chosen {
			return chosen
		}
	}
	return options[0].GetValue()
}

// invoiceDrawer is partials/partner/invoice_drawer.html as the feed reads
// it: the choices, then what will be sent under each Lead, or why nothing.
func invoiceDrawer(basis *activities.InvoiceBasis, basisError, kind, instalment string, anchor time.Time) *screensv1.PageDrawer {
	reload := func(f *screensv1.DrawerField) *screensv1.DrawerItem {
		f.ReloadsPath = invoiceDrawerPath
		return drawerField(f)
	}
	instalments := []*screensv1.DrawerOption{{Value: "advance", Label: "50% advance: scheduled work"},
		{Value: "clearance", Label: "Full payment: completed work with evidence"}}
	periods := []*screensv1.DrawerOption{{Value: "week", Label: "Week"}, {Value: "month", Label: "Month"}, {Value: "quarter", Label: "Quarter"}}
	items := []*screensv1.DrawerItem{drawerText(invoiceIntro),
		reload(&screensv1.DrawerField{Name: "instalment", Label: "Invoice for", Kind: "select", Options: instalments,
			Value: chosenOrFirst(instalment, instalments)}),
		reload(&screensv1.DrawerField{Name: "period_kind", Label: "Period", Kind: "select", Options: periods, Value: chosenOrFirst(kind, periods)}),
		reload(&screensv1.DrawerField{Name: "anchor", Label: "Date in the period", Kind: "date", Value: anchor.Format(time.DateOnly)}),
	}
	d := &screensv1.PageDrawer{Title: "Send invoice", HasRequired: true, CancelLabel: "Cancel"}
	switch {
	case basisError != "":
		items = append(items, note(basisError, "danger"))
	case basis != nil && len(basis.Items) > 0:
		summary := fmt.Sprintf("%s · %d %s", basis.Label, len(basis.Items), pluralWord(len(basis.Items), "activity", "activities"))
		if len(basis.ByLead) > 1 {
			summary += fmt.Sprintf(" · %d invoices, one for each Programme Lead", len(basis.ByLead))
		}
		items = append(items, drawerText(summary))
		for _, g := range basis.ByLead {
			head := invoiceNoLead
			if g.Lead != nil {
				head = "To Programme Lead: " + g.Lead.Name
			}
			items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: head}})
			if g.Lead == nil {
				items = append(items, drawerText(invoiceNoLeadNote))
			}
			lines := &screensv1.PageFacts{}
			for _, it := range g.Items {
				label := strings.TrimSpace(it.Place + " " + it.Day.Format("2 Jan 2006") + " · " + it.Work)
				if it.DeliveredBy != "" {
					label += " · " + it.DeliveredBy
				}
				value := ugxAmount(it.Payable) + " in full"
				if it.Payable != it.Planned {
					value = ugxAmount(it.Payable) + " of " + ugxAmount(it.Planned)
				}
				lines.Facts = append(lines.Facts, &screensv1.PageFact{Label: label, Value: value})
			}
			items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Lines{Lines: lines}})
		}
		items = append(items, drawerField(&screensv1.DrawerField{Name: "invoice_file", Label: "Your own invoice document (optional)",
			Kind: "file", Help: invoiceFileHelp}))
		d.SubmitLabel, d.CanSubmit = "Send invoice"+pluralWord(len(basis.ByLead), "", "s"), true
	default:
		why := invoiceNothingFull
		if instalment == "advance" {
			why = invoiceNothingAdv
		}
		items = append(items, drawerText(invoiceNothingHead), drawerText(why))
	}
	d.Items = items
	return d
}

// ugxAmount is the ugx_amount filter: the whole number with its thousands.
func ugxAmount(n int64) string {
	sign, text := "", fmt.Sprint(n)
	if n < 0 {
		sign, text = "-", text[1:]
	}
	for i := len(text) - 3; i > 0; i -= 3 {
		text = text[:i] + "," + text[i:]
	}
	return sign + text
}

// invoiceInGo is partner_invoice_submit, posted from the drawer.
func (s *Service) invoiceInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	query, ok := s.invoiceTaken(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed || p.InActingAppointment {
		return nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, invoiceDrawerPath) {
		return &screensv1.SaveDrawerResponse{Saved: false, Error: invoicePageDenied}, true, nil
	}
	values := message.GetValues()
	field := func(name string) string {
		if v, posted := values[name]; posted {
			return v
		}
		return query.Get(name)
	}
	partners, err := partnerassigned.PartnerIDs(ctx, s.db, p)
	if err != nil {
		return nil, true, err
	}
	saved, err := s.partnerInvoice.SubmitPartnerInvoice(ctx, p, partners, activities.InvoiceSubmit{
		Kind: field("period_kind"), Instalment: field("instalment"), Anchor: field("anchor"),
		EnteredTotal: values["entered_total"], HasFile: values["invoice_file"] != ""}, from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go partner invoice failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(saved.Message)}, true, nil
}
