// Package batchpayments builds the Batch Payments Center
// (/accounts/batch-payments/): the staff work confirmed for an advance and
// the verified partner work still to be paid, each under its own tab with
// the work's type, place and amount
// (apps.frontend.views.finance_operating_views.batch_payments_view and
// pages/accounts/batch_payments.html, as the existing feed reads them).
//
// It reads; it never writes. It hands the page on for a payment file (the
// export query) and any query it does not know. The doors, names and
// statuses are exported to rules.json by `manage.py
// export_batch_payments_rules`; apps/fund_requests/
// test_batch_payments_rules_export.py fails when the two differ.
package batchpayments

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundworkspace"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// PagePath is the page's path.
const PagePath = "/accounts/batch-payments/"

// tab is read by the page's own tab switch, which the feed does not follow.
var ownQuery = map[string]bool{"tab": true}

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page  bool            `json:"page"`
		Strip json.RawMessage `json:"strip"`
	} `json:"roles"`
	ActivityTypes          map[string]string `json:"activity_types"`
	AdvancePayableStatus   string            `json:"advance_payable_status"`
	PartnerPayableStatuses []string          `json:"partner_payable_statuses"`
	PartnerPaidStatuses    []string          `json:"partner_paid_statuses"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("batchpayments: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || r.AdvancePayableStatus == "" || len(r.PartnerPayableStatuses) == 0 {
		panic("batchpayments: rules.json lacks the doors or the payment statuses")
	}
	return r
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService returns the page's builder.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// payment is one piece of work waiting on a payment file.
type payment struct {
	id, kind, school, partner string
	hasSchool                 bool
	amount                    int64
}

// Build answers /accounts/batch-payments/.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !ownQuery[key] {
			return nil, false, nil
		}
	}
	if len(role.Strip) > 0 && string(role.Strip) != "null" {
		return nil, false, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, true, fmt.Errorf("batchpayments: resolving the reader's scope: %w", err)
	}
	// A country reader's money is the request's country's (docs/migration/
	// 80, §19): the Admin and the regional roles read the country they work
	// in, so money is never summed across countries.
	var country []string
	switch {
	case scope.CountryScope && p.Country != nil:
		country = []string{p.Country.ID}
	case scope.CountryScope && scope.Country != "":
		country = scope.CountryIDs()
	}
	advances, err := s.read(ctx, country, `a.delivery_type = 'staff' AND NOT (a.payment_status = ANY($2))
  AND EXISTS (SELECT 1 FROM advance_request r WHERE r.activity_id = a.id AND r.status = $3)`,
		rules.PartnerPaidStatuses, rules.AdvancePayableStatus)
	if err != nil {
		return nil, true, err
	}
	partners, err := s.read(ctx, country, `a.delivery_type = 'partner' AND a.status = 'ia_verified' AND a.payment_status = ANY($2)`,
		rules.PartnerPayableStatuses)
	if err != nil {
		return nil, true, err
	}
	h := &screensv1.PageHeader{Eyebrow: "Finance", Title: "Batch Payments Center",
		Description: "Export payment files for confirmed advances and verified Partner work. Staff reimbursements remain in the Disbursement Dashboard through receipt confirmation."}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks(budgetpage.CurrencyCode(p.Country), advances, partners), WebPath: PagePath}, true, nil
}

// read is the live work matching where, in the reader's country when the
// reader is held to one, latest first (the activity's own ordering).
func (s *Service) read(ctx context.Context, country []string, where string, args ...any) ([]payment, error) {
	countryArg := any(nil)
	if country != nil {
		countryArg = country
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.activity_type, COALESCE(s.name, ''), s.id IS NOT NULL, COALESCE(a.assigned_partner_id, ''), a.est_cost_cents
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.deleted_at IS NULL AND `+where+`
  AND ($1::text[] IS NULL OR `+schoolprofile.ActivityInCountry(1)+`)
ORDER BY a.created_at DESC`, append([]any{countryArg}, args...)...)
	if err != nil {
		return nil, fmt.Errorf("batchpayments: reading the payable work: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (payment, error) {
		var p payment
		err := row.Scan(&p.id, &p.kind, &p.school, &p.hasSchool, &p.partner, &p.amount)
		return p, err
	})
	if err != nil {
		return nil, fmt.Errorf("batchpayments: reading the payable work: %w", err)
	}
	return out, nil
}

// short is the template's id|slice:":8".
func short(id string) string {
	r := []rune(id)
	return string(r[:min(len(r), 8)])
}

func kind(p payment) string {
	if l, ok := rules.ActivityTypes[p.kind]; ok {
		return l
	}
	return p.kind
}

// panelFor is one tab's card: its heading with the export action, the
// select-all line and the work, or the words for none.
func panelFor(code, heading, export, empty string, list []payment, line func(payment) (string, string)) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{fundworkspace.Panel(heading, fundworkspace.Text("None selected"),
		fundworkspace.Links(&screensv1.PageLink{Text: fmt.Sprintf("Export all eligible (%d)", len(list)), Href: "?export=" + export}))}
	if len(list) == 0 {
		return append(out, fundworkspace.Panel("", fundworkspace.Text(empty)))
	}
	items := []*screensv1.PagePanelItem{}
	for _, p := range list {
		first, second := line(p)
		items = append(items, fundworkspace.Text(first), fundworkspace.Text(second), fundworkspace.Text(budgetpage.In(code, p.amount)))
	}
	return append(out, fundworkspace.Panel("", fundworkspace.Text("Select all in this list")), fundworkspace.Panel("", feeddom.Paired(items)...))
}

func blocks(code string, advances, partners []payment) []*screensv1.PageBlock {
	advanceBlocks := panelFor(code, "Batch Advances ready for payment file", "advances", "No pending advances for batch payment.", advances,
		func(p payment) (string, string) {
			place := p.school
			if !p.hasSchool {
				place = "Cluster-wide"
			}
			return "#" + short(p.id) + " • " + kind(p), place
		})
	partnerBlocks := panelFor(code, "Batch Partner Payments ready for payment file", "partners", "No pending partner payments for batch payout.", partners,
		func(p payment) (string, string) { return p.partner + " • #" + short(p.id), kind(p) })
	segments := &screensv1.PageSegments{Caption: "Finance", Segments: []*screensv1.PageSegment{
		{Label: fmt.Sprintf("Advances (%d)", len(advances)), Blocks: advanceBlocks},
		{Label: fmt.Sprintf("Partner Payments (%d)", len(partners)), Blocks: partnerBlocks},
	}}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Segments{Segments: segments}},
		// The feed reads the advances card's heading a second time, with the
		// selection line as its subtitle.
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Batch Advances ready for payment file", Subtitle: "None selected"}}},
	}
}
