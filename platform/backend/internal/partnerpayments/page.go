// Package partnerpayments builds the Partner Payment Queue
// (/accounts/partner-payments/): the partner invoices the Programme Lead
// confirmed, awaiting payment, and the partner work IA verified, awaiting
// clearance of its balance
// (apps.frontend.views.finance_operating_views.partner_payments_view and
// pages/accounts/partner_payments.html, as the existing feed reads them).
//
// It reads; it never writes (paying goes to the existing application). It
// hands the page on for any query and for a table longer than one page. The
// doors and words are exported to rules.json by `manage.py
// export_partner_payments_rules`; apps/fund_requests/
// test_partner_payments_rules_export.py fails when the two differ.
package partnerpayments

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
	"time"

	_ "time/tzdata" // dates are Nairobi's wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundworkspace"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PagePath is the page's path.
const PagePath = "/accounts/partner-payments/"

//go:embed rules.json
var rulesJSON []byte

type roleRules struct {
	Page         bool            `json:"page"`
	Strip        json.RawMessage `json:"strip"`
	SchoolLinks  bool            `json:"school_links"`
	PartnerLinks bool            `json:"partner_links"`
}

var rules = func() (r struct {
	Roles                  map[string]roleRules `json:"roles"`
	ActivityTypes          map[string]string    `json:"activity_types"`
	InvoiceTypes           map[string]string    `json:"invoice_types"`
	NonFundableStatuses    []string             `json:"non_fundable_statuses"`
	PartnerPayableStatuses []string             `json:"partner_payable_statuses"`
	PageSize               int                  `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("partnerpayments: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || r.PageSize <= 0 || len(r.PartnerPayableStatuses) == 0 {
		panic("partnerpayments: rules.json lacks the doors, the page size or the payable statuses")
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("partnerpayments: " + err.Error())
	}
	return z
}()

// Service builds the page.
type Service struct {
	db schooldirectory.Querier
}

// NewService returns the page's builder.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

// invoice is one PL-confirmed partner invoice.
type invoice struct {
	id, partnerID, partner, kind string
	created                      time.Time
	start, end                   time.Time
	items                        int
	entered, payable             int64
	document                     bool
}

// work is one piece of verified partner work awaiting clearance.
type work struct {
	id, kind, partnerID, partner, staff, schoolID, school string
	scheduled                                             *time.Time
	planned, paid                                         int64
}

// Build answers /accounts/partner-payments/.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if len(query) > 0 || (len(role.Strip) > 0 && string(role.Strip) != "null") {
		return nil, false, nil
	}
	// The request's country's partners and work only (docs/migration/80,
	// §19); the Admin and the regional roles read the country they work in.
	var countryIDs []string
	if p.Country != nil {
		countryIDs = []string{p.Country.ID}
	}
	code := budgetpage.CurrencyCode(p.Country)
	invoices, err := s.invoices(ctx, countryIDs)
	if err != nil {
		return nil, true, err
	}
	works, err := s.works(ctx, countryIDs)
	if err != nil {
		return nil, true, err
	}
	if len(invoices) > rules.PageSize || len(works) > rules.PageSize {
		return nil, false, nil
	}
	h := &screensv1.PageHeader{Eyebrow: "Finance", Title: "Partner Payment Queue",
		Description: "The MOU pays partners in two instalments: 50% of the planned activity cost up front, and the balance cleared once the partner finishes the work and IA verifies it."}
	out := []*screensv1.PageBlock{}
	if len(invoices) > 0 {
		out = append(out, fundworkspace.Panel("Partner Invoices — Awaiting Payment", fundworkspace.Text(
			"Confirmed by the Programme Lead against the plan. Each invoice is written from the plan's costs; the payable instalment is derived from them.")),
			invoiceTable(invoices, role, code))
	}
	out = append(out, fundworkspace.Panel("Verified — Awaiting Clearance",
		fundworkspace.Text("The partner finished and IA verified the work; the remaining balance clears here.")),
		workTable(works, role, code))
	dialog := &screensv1.PageDialog{Key: "payOpen", Title: "Process Partner Payment ·", Blocks: []*screensv1.PageBlock{
		fundworkspace.Panel("Process Partner Payment ·"),
		fundworkspace.Panel("", fundworkspace.Text("Confirm Payment"), fundworkspace.Text("Cancel")),
	}}
	return &screensv1.GetPageResponse{Header: h, Blocks: out, Dialogs: []*screensv1.PageDialog{dialog}, WebPath: PagePath}, true, nil
}

// invoices is every invoice the Programme Lead confirmed, oldest first,
// with its partner's name (its id when no live partner has it) and items.
func (s *Service) invoices(ctx context.Context, countryIDs []string) ([]invoice, error) {
	rows, err := s.db.Query(ctx, `
SELECT i.id, i.partner_id, COALESCE((SELECT p.name FROM partner p WHERE p.id = i.partner_id AND p.deleted_at IS NULL), i.partner_id),
  i.invoice_type, i.created_at, i.period_start, i.period_end,
  (SELECT COUNT(*) FROM partner_invoice_item it WHERE it.invoice_id = i.id), i.entered_total, i.payable_amount, i.stored_name <> ''
FROM partner_invoice i WHERE i.status = 'confirmed_by_pl'
  AND ($1::text[] IS NULL OR EXISTS (SELECT 1 FROM partner ip WHERE ip.id = i.partner_id AND `+registry.PartnerIn("ip", "$1")+`))
ORDER BY i.created_at`, countryIDs)
	if err != nil {
		return nil, fmt.Errorf("partnerpayments: reading the invoices: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (invoice, error) {
		var v invoice
		err := row.Scan(&v.id, &v.partnerID, &v.partner, &v.kind, &v.created, &v.start, &v.end, &v.items, &v.entered, &v.payable, &v.document)
		return v, err
	})
	if err != nil {
		return nil, fmt.Errorf("partnerpayments: reading the invoices: %w", err)
	}
	return out, nil
}

// works is the live partner work IA verified with a payable payment status,
// latest first (the activity's own ordering), with its planned cost, what
// was paid on it, its partner's and responsible person's names.
func (s *Service) works(ctx context.Context, countryIDs []string) ([]work, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.activity_type, COALESCE(a.assigned_partner_id, ''),
  COALESCE((SELECT p.name FROM partner p WHERE p.id = a.assigned_partner_id AND p.deleted_at IS NULL), NULLIF(a.assigned_partner_id, ''), '—'),
  COALESCE((SELECT CASE WHEN u.id IS NULL THEN sp.id ELSE u.name END FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
            WHERE sp.id = a.responsible_staff_id AND sp.deleted_at IS NULL),
           (SELECT u.name FROM "user" u WHERE u.id = a.responsible_staff_id), ''),
  COALESCE(s.id, ''), COALESCE(s.name, ''), a.scheduled_date,
  COALESCE((SELECT SUM(l.amount) FROM activity_schedule_cost_line l WHERE l.activity_id = a.id), 0),
  COALESCE((SELECT SUM(pp.amount_paid) FROM partner_payment pp WHERE pp.activity_id = a.id), 0)
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND a.delivery_type = 'partner' AND NOT (a.status = ANY($1))
  AND a.status = 'ia_verified' AND a.payment_status = ANY($2)
  AND ($3::text[] IS NULL OR `+registry.ActivityRowIn("a.id", "$3")+`)
ORDER BY a.created_at DESC`, rules.NonFundableStatuses, rules.PartnerPayableStatuses, countryIDs)
	if err != nil {
		return nil, fmt.Errorf("partnerpayments: reading the verified work: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (work, error) {
		var w work
		err := row.Scan(&w.id, &w.kind, &w.partnerID, &w.partner, &w.staff, &w.schoolID, &w.school, &w.scheduled, &w.planned, &w.paid)
		return w, err
	})
	if err != nil {
		return nil, fmt.Errorf("partnerpayments: reading the verified work: %w", err)
	}
	return out, nil
}

func cell(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: text} }

func menu(items ...[2]string) *screensv1.PageCell {
	c := &screensv1.PageCell{}
	for _, it := range items {
		c.Actions = append(c.Actions, &screensv1.PageAction{Key: "menu", Label: it[0], Enabled: true, Href: it[1]})
	}
	return c
}

// amount is the ugx_amount filter: the whole figure with thousands commas,
// its currency written in the column's label.
func amount(n int64) string { return strings.TrimPrefix(budgetpage.UGX(n), "UGX ") }

func plural(n int) string {
	if n == 1 {
		return "y"
	}
	return "ies"
}

func invoiceTable(invoices []invoice, role roleRules, code string) *screensv1.PageBlock {
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{
		{Label: "Invoice"}, {Label: "Period"}, {Label: "Payable (" + code + ")", Numeric: true}, {Label: "Reference"}, {Label: "Actions", Numeric: true}}}
	for _, v := range invoices {
		who := cell(v.partner)
		if role.PartnerLinks && v.partner != "" && strings.TrimSpace(v.partnerID) != "" {
			who.Href = "/partners/" + url.PathEscape(strings.TrimSpace(v.partnerID))
		}
		kind := v.kind
		if l, ok := rules.InvoiceTypes[v.kind]; ok {
			kind = l
		}
		who.Text = kind + " " + v.created.In(zone).Format("Jan 02, 2006") + " · " + who.Text
		actions := [][2]string{{"Open Invoice", "/partner-invoices/" + v.id}}
		if v.document {
			actions = append(actions, [2]string{"Partner's Document", "/accounts/partner-invoices/" + v.id + "/download"})
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			who,
			cell(fmt.Sprintf("%s – %s %d activit%s · plan %s · PL-confirmed", v.start.Format("02 Jan"), v.end.Format("02 Jan 2006"),
				v.items, plural(v.items), amount(v.entered))),
			cell(amount(v.payable)),
			menu(actions...),
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func workTable(works []work, role roleRules, currency string) *screensv1.PageBlock {
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{
		{Label: "Partner"}, {Label: "Activity"}, {Label: "School ID"}, {Label: "School / Cluster"}, {Label: "Assigned Staff"},
		{Label: "Activity Date"}, {Label: "IA Status"}, {Label: "Payment Amount"}, {Label: "Actions", Numeric: true}}}
	if len(works) == 0 {
		msg := "No partner activities verified and awaiting payment."
		t.EmptyMessage = msg
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{cell(msg)}}}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
	}
	for _, w := range works {
		kind := w.kind
		if l, ok := rules.ActivityTypes[w.kind]; ok {
			kind = l
		}
		// school_code writes an empty holder the web fills in; the feed
		// reads it as nothing.
		code, place := "—", cell("Cluster-wide")
		if w.schoolID != "" {
			code, place = "", cell(w.school)
			if role.SchoolLinks && w.school != "" {
				place.Href = "/schools/" + url.PathEscape(w.schoolID)
			}
		}
		staff := w.staff
		if staff == "" {
			staff = "N/A"
		}
		date := ""
		if w.scheduled != nil {
			date = w.scheduled.In(zone).Format("Jan 02, 2006")
		}
		balance := budgetpage.In(currency, max(w.planned-w.paid, 0))
		if w.paid != 0 {
			balance += " Advance paid " + amount(w.paid)
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(w.partner), cell(kind), cell(code), place, cell(staff), cell(date),
			{Text: "Verified", Tone: "primary", Badge: true},
			cell(balance),
			menu([2]string{"View activity finance detail", "/accounts/activities/" + w.id + "/"}),
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}
