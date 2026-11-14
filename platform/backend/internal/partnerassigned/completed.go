package partnerassigned

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// CompletedPath is Completed Work & Payments.
const CompletedPath = "/partner/completed"

// done is one submitted piece of partner work.
type done struct {
	id, kind, status, salesforce string
	schoolID, school             *string
	clusterID, cluster           *string
	scheduled                    *time.Time
}

// payment is a payment made against partner work.
type payment struct {
	kind, reference string
	date            *time.Time
	amount          int64
}

// completed is partner_completed_payments_view: the partner's submitted
// work, newest scheduled first, on the schools or the activities tab, with
// where its IA review, Salesforce record and payment stand.
func (s *Service) completed(ctx context.Context, p auth.Principal, partners []string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if partners == nil {
		partners = []string{}
	}
	tab := "schools"
	if query.Get("tab") == "activities" {
		tab = "activities"
	}
	rows, err := s.db.Query(ctx, `SELECT a.id, a.activity_type, a.status, COALESCE(a.salesforce_activity_id, ''), s.id, s.name, c.id, c.name, a.scheduled_date
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.assigned_partner_id = ANY($1) AND a.deleted_at IS NULL AND a.status = ANY($2) ORDER BY a.scheduled_date DESC LIMIT $3`,
		partners, rules.CompletedStatuses, rules.CompletedLimit)
	if err != nil {
		return nil, true, fmt.Errorf("partnerassigned: reading the completed work: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (done, error) {
		var d done
		return d, r.Scan(&d.id, &d.kind, &d.status, &d.salesforce, &d.schoolID, &d.school, &d.clusterID, &d.cluster, &d.scheduled)
	})
	if err != nil {
		return nil, true, fmt.Errorf("partnerassigned: reading the completed work: %w", err)
	}
	ids := make([]string, len(list))
	for i, d := range list {
		ids[i] = d.id
	}
	payments := map[string][]payment{}
	rows, err = s.db.Query(ctx, `SELECT activity_id, payment_type, COALESCE(payment_reference, ''), payment_date, amount_paid FROM partner_payment WHERE activity_id = ANY($1)`, ids)
	if err != nil {
		return nil, true, fmt.Errorf("partnerassigned: reading the payments: %w", err)
	}
	for rows.Next() {
		var id string
		var x payment
		if err := rows.Scan(&id, &x.kind, &x.reference, &x.date, &x.amount); err != nil {
			rows.Close()
			return nil, true, fmt.Errorf("partnerassigned: reading the payments: %w", err)
		}
		payments[id] = append(payments[id], x)
	}
	rows.Close()
	stage := map[string]string{}
	rows, err = s.db.Query(ctx, `SELECT i.activity_id, v.status FROM partner_invoice_item i JOIN partner_invoice v ON v.id = i.invoice_id
WHERE i.activity_id = ANY($1) AND v.status IN ('submitted_to_pl', 'confirmed_by_pl')`, ids)
	if err != nil {
		return nil, true, fmt.Errorf("partnerassigned: reading the invoices: %w", err)
	}
	for rows.Next() {
		var id, status string
		if err := rows.Scan(&id, &status); err != nil {
			rows.Close()
			return nil, true, fmt.Errorf("partnerassigned: reading the invoices: %w", err)
		}
		if stage[id] != "awaiting_accountant" {
			stage[id] = map[string]string{"confirmed_by_pl": "awaiting_accountant", "submitted_to_pl": "processing"}[status]
		}
	}
	rows.Close()
	return completedPage(p, tab, list, payments, stage, query), true, nil
}

// paymentState is the row's three honest dimensions in partner words.
func paymentState(d done, paid []payment, stage string) (ia, iaTone, pay, payTone string) {
	switch d.status {
	case "awaiting_ia_verification", "submitted_to_ia", "completed":
		ia, iaTone = "Under IA Review", "info"
	case "returned", "returned_by_ia":
		ia, iaTone = "Returned for Correction", "danger"
	default:
		ia, iaTone = "Verified", "success"
	}
	cleared := slices.ContainsFunc(paid, func(x payment) bool { return x.kind == "clearance" })
	switch {
	case cleared:
		pay, payTone = "Paid", "success"
	case stage == "awaiting_accountant":
		pay, payTone = "Awaiting Accountant", "warning"
	case stage == "processing":
		pay, payTone = "Payment Processing", "info"
	case len(paid) > 0:
		pay, payTone = "Advance Paid — Balance Pending", "info"
	case ia == "Verified":
		pay, payTone = "Awaiting Payment", "warning"
	default:
		pay, payTone = "Not Yet Eligible", "neutral"
	}
	return ia, iaTone, pay, payTone
}

// ugx is |ugx_amount: whole shillings with thousands commas.
func ugx(n int64) string {
	s := strconv.FormatInt(n, 10)
	neg := n < 0
	if neg {
		s = s[1:]
	}
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if neg {
		return "-" + s
	}
	return s
}

// completedPage is pages/partner/completed_payments.html as the feed reads
// it.
func completedPage(p auth.Principal, tab string, list []done, payments map[string][]payment, stage map[string]string, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Field Work", Title: "Completed Work & Payments",
		Description: "Where every submitted school or activity stands — IA review, Salesforce confirmation, and payment."}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: []*screensv1.PageLinkTab{
		{Label: "Schools", Href: "?tab=schools", Active: tab == "schools"}, {Label: "Activities", Href: "?tab=activities", Active: tab == "activities"}}}}}}
	linkSchools := slices.Contains(rules.ProfileLinkRoles["schools"], p.ActiveRole)
	linkClusters := slices.Contains(rules.ProfileLinkRoles["clusters"], p.ActiveRole)
	rows := []*screensv1.PageRow{}
	for _, d := range list {
		schoolScoped := d.schoolID != nil && !slices.Contains(rules.ClusterScopeTypes, d.kind)
		if (tab == "schools") != schoolScoped {
			continue
		}
		paid := payments[d.id]
		var total int64
		for _, x := range paid {
			total += x.amount
		}
		ia, iaTone, pay, payTone := paymentState(d, paid, stage[d.id])
		first := &screensv1.PageCell{Text: "Field work"}
		switch {
		case d.schoolID != nil:
			first.Text = closedschools.Collapse(*d.school)
			if linkSchools {
				first.Href = "/schools/" + *d.schoolID
			}
		case d.clusterID != nil:
			first.Text = closedschools.Collapse(*d.cluster)
			if linkClusters {
				first.Href = "/clusters/" + *d.clusterID
			}
		}
		kind, ok := rules.ActivityTypes[d.kind]
		if !ok {
			kind = d.kind
		}
		date := ""
		if d.scheduled != nil {
			date = d.scheduled.In(zone).Format("02 Jan 2006")
		}
		sf, sfTone := "Pending", "neutral"
		if d.salesforce != "" {
			sf, sfTone = "Confirmed", "success"
		}
		amount, reference := "—", "—"
		if total != 0 {
			amount = ugx(total)
		}
		if len(paid) > 0 && paid[len(paid)-1].reference != "" {
			last := paid[len(paid)-1]
			reference = last.reference
			if last.date != nil {
				reference += " · " + last.date.In(zone).Format("02 Jan 2006")
			}
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			first, {Text: kind}, {Text: date}, {Text: ia, Tone: iaTone}, {Text: sf, Tone: sfTone}, {Text: pay, Tone: payTone},
			{Text: amount}, {Text: closedschools.Collapse(reference)},
		}})
	}
	firstColumn := "School"
	if tab == "activities" {
		firstColumn = "Activity"
	}
	t := &screensv1.PageTable{}
	for i, c := range []string{firstColumn, "Activity Type", "Date", "IA Status", "Salesforce", "Payment", "Paid (UGX)", "Reference"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: i == 6})
	}
	size := rules.PageSize
	number, pages := closedschools.PageOf(query.Get("completed_payments_rows_page"), len(rows), size)
	t.Rows = rows[min((number-1)*size, len(rows)):min(number*size, len(rows))]
	if len(rows) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "Nothing submitted yet — completed work appears here after you submit evidence."}}}}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("completed_payments_rows_page", number, pages, len(rows), size, query, rules.QueryKeysNotPassed))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: CompletedPath}
}
