package activities

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"
)

// The partner's period invoice (apps.fund_requests.partner_invoices): one
// invoice for each Programme Lead whose schools the period's work is at,
// written from the plan. invoice_basis is what the drawer shows and the save
// writes.

const (
	invoiceAdvance       = "advance"
	invoiceClearance     = "clearance"
	invoiceBadInstalment = "Choose the 50% advance or the clearance invoice."
	invoiceNotPartner    = "Only a partner account can submit partner invoices."
	invoiceBadPeriod     = "Choose a week, month or quarter for the invoice."
)

// InvoiceItem is one activity the invoice asks to be paid for.
type InvoiceItem struct {
	ActivityID, Category               string
	Planned, Payable                   int64
	Day                                time.Time
	Place, District, Work, DeliveredBy string
	// The activity as the Lead and the paid partner are read from it.
	schoolID, responsible, monitor   string
	delivery, assigned, facilitating string
}

// InvoiceLead is a Programme Lead an invoice is addressed to.
type InvoiceLead struct{ StaffID, UserID, Name string }

// InvoiceGroup is one invoice of the period: its Lead (nil: none holds the
// schools) and its lines.
type InvoiceGroup struct {
	Lead                 *InvoiceLead
	Items                []InvoiceItem
	SystemTotal, Payable int64
}

// InvoiceBasis is invoice_basis.
type InvoiceBasis struct {
	Kind, Label, Instalment string
	Start, End              time.Time
	Items                   []InvoiceItem
	ByLead                  []InvoiceGroup
	SystemTotal, Payable    int64
}

// invoicePeriod is period_bounds: Monday to Sunday, the calendar month, or
// the operational quarter as get_quarter_date_range gives it (its end is the
// next quarter's first day).
func invoicePeriod(kind string, anchor time.Time) (time.Time, time.Time, error) {
	switch kind {
	case "week":
		start := anchor.AddDate(0, 0, -((int(anchor.Weekday()) + 6) % 7))
		return start, start.AddDate(0, 0, 6), nil
	case "month":
		start := time.Date(anchor.Year(), anchor.Month(), 1, 0, 0, 0, 0, time.UTC)
		return start, start.AddDate(0, 1, -1), nil
	case "quarter":
		first := time.Month(((int(anchor.Month())-1)/3)*3 + 1)
		start := time.Date(anchor.Year(), first, 1, 0, 0, 0, 0, time.UTC)
		return start, start.AddDate(0, 3, 0), nil
	}
	return time.Time{}, time.Time{}, refuse(invoiceBadPeriod)
}

// invoicePeriodLabel is period_label.
func invoicePeriodLabel(kind string, start, end time.Time) string {
	switch kind {
	case "week":
		return "Week of " + start.Format("02 Jan") + " – " + end.Format("02 Jan 2006")
	case "month":
		return start.Format("January 2006")
	}
	return start.Format("02 Jan") + " – " + end.Format("02 Jan 2006")
}

// invoiceCategory is _category_of.
func invoiceCategory(it InvoiceItem, activityType string) string {
	r := rules.PartnerInvoice
	switch {
	case in(r.TrainingTypes, activityType) || strings.Contains(activityType, "training"):
		return "Training Facilitation Fee"
	case in(r.ClusterMeetingTypes, activityType) && it.facilitating != "" && it.delivery != "partner":
		return "Meeting Facilitation Fee"
	case it.schoolID != "":
		return "School Visits"
	}
	return "Other Field Work"
}

// invoicePayable is the instalment's amount of one activity, or false when
// the instalment does not take it: the 50% advance of scheduled work never
// paid and not yet completed, or the full cost (less a 50% paid) of work
// completed with its evidence whose advance is not still on an invoice.
func invoicePayable(instalment string, planned int64, paid map[string]int64, done, advanceInFlight bool) (int64, bool) {
	var payable int64
	if instalment == invoiceAdvance {
		if paid[invoiceAdvance] != 0 || paid[invoiceClearance] != 0 || done {
			return 0, false
		}
		payable = planned / 2
	} else {
		if !done || advanceInFlight || paid[invoiceClearance] != 0 {
			return 0, false
		}
		payable = planned
		for _, v := range paid {
			payable -= v
		}
	}
	return payable, payable > 0
}

// PartnerInvoiceBasis is invoice_basis for the organisations partnerIDs
// (resolve_partner_ids): refusals in the existing words.
func (s *Service) PartnerInvoiceBasis(ctx context.Context, partnerIDs []string, kind string, anchor time.Time, instalment string) (*InvoiceBasis, error) {
	if instalment != invoiceAdvance && instalment != invoiceClearance {
		return nil, refuse("%s", invoiceBadInstalment)
	}
	if len(partnerIDs) == 0 {
		return nil, refuse(invoiceNotPartner)
	}
	start, end, err := invoicePeriod(kind, anchor)
	if err != nil {
		return nil, err
	}
	b := &InvoiceBasis{Kind: kind, Instalment: instalment, Start: start, End: end, Label: invoicePeriodLabel(kind, start, end)}
	r := rules.PartnerInvoice
	rows, err := s.db.Query(ctx, `
WITH work AS (
  SELECT a.id, a.scheduled_date, COALESCE(a.activity_type, '') AS activity_type, COALESCE(a.status, '') AS status,
         COALESCE(a.delivery_type, '') AS delivery_type, COALESCE(a.assigned_partner_id, '') AS assigned,
         COALESCE(a.facilitating_partner_id, '') AS facilitating, COALESCE(a.school_id, '') AS school_id,
         COALESCE(a.responsible_staff_id, '') AS responsible, COALESCE(a.monitored_by_staff_id, '') AS monitor,
         COALESCE(CASE WHEN s.id IS NOT NULL THEN s.name ELSE cl.name END, '') AS place,
         COALESCE(CASE WHEN s.id IS NOT NULL THEN sd.name ELSE cd.name END, '') AS district,
         COALESCE(a.activity_name_snapshot, '') AS work, COALESCE(a.delivery_contact_name, '') AS delivered_by
  FROM activity a
  LEFT JOIN school s ON s.id = a.school_id LEFT JOIN district sd ON sd.id = s.district_id
  LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN district cd ON cd.id = cl.district_id
  WHERE a.deleted_at IS NULL
    AND ((a.assigned_partner_id = ANY($1) AND a.delivery_type = 'partner') OR (a.facilitating_partner_id = ANY($1) AND a.delivery_type = 'staff'))
    AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date BETWEEN $2 AND $3
    AND NOT COALESCE(a.status = ANY($4), false))
SELECT w.id, w.scheduled_date, w.activity_type, w.status, w.delivery_type, w.assigned, w.facilitating, w.school_id,
  w.responsible, w.monitor, w.place, w.district, w.work, w.delivered_by,
  COALESCE((SELECT SUM(l.amount) FROM activity_schedule_cost_line l WHERE l.activity_id = w.id
    AND (w.delivery_type = 'partner' OR w.facilitating = '' OR l.line_item_type = $5)), 0)::bigint,
  COALESCE((SELECT jsonb_object_agg(t.payment_type, t.paid) FROM (SELECT COALESCE(p.payment_type, '') AS payment_type,
    SUM(p.amount_paid)::bigint AS paid FROM partner_payment p WHERE p.activity_id = w.id GROUP BY 1) t), '{}'::jsonb),
  EXISTS (SELECT 1 FROM partner_invoice_item i JOIN activity ia ON ia.id = i.activity_id WHERE i.activity_id = w.id
    AND i.instalment = $6 AND (ia.assigned_partner_id = ANY($1) OR ia.facilitating_partner_id = ANY($1))),
  w.status = ANY($7) AND (w.delivery_type <> 'partner'
    OR EXISTS (SELECT 1 FROM evidence_record e WHERE e.activity_id = w.id AND NOT e.quarantined)),
  EXISTS (SELECT 1 FROM partner_invoice_item i WHERE i.activity_id = w.id AND i.instalment = 'advance' AND i.payment_id IS NULL)
FROM work w ORDER BY w.scheduled_date, w.id`,
		partnerIDs, start, end, r.NonFundable, r.FeeLineType, instalment, r.Cleared)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the period's invoiceable work: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var it InvoiceItem
		var day time.Time
		var activityType, status string
		var paid map[string]int64
		var invoiced, done, inFlight bool
		if err := rows.Scan(&it.ActivityID, &day, &activityType, &status, &it.delivery, &it.assigned, &it.facilitating, &it.schoolID,
			&it.responsible, &it.monitor, &it.Place, &it.District, &it.Work, &it.DeliveredBy, &it.Planned, &paid,
			&invoiced, &done, &inFlight); err != nil {
			return nil, fmt.Errorf("activities: reading an invoiceable activity: %w", err)
		}
		if invoiced || it.Planned <= 0 {
			continue
		}
		payable, ok := invoicePayable(instalment, it.Planned, paid, done, inFlight)
		if !ok {
			continue
		}
		it.Payable, it.Day = payable, day.In(s.kampala)
		if it.Work == "" {
			it.Work = activityType
			if label, ok := r.ActivityTypeLabels[activityType]; ok {
				it.Work = label
			}
		}
		it.Category = invoiceCategory(it, activityType)
		b.Items = append(b.Items, it)
		b.SystemTotal += it.Planned
		b.Payable += it.Payable
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("activities: reading the period's invoiceable work: %w", err)
	}
	if b.ByLead, err = s.invoiceGroups(ctx, b.Items); err != nil {
		return nil, err
	}
	return b, nil
}

// invoiceGroups is split_by_lead: the lines folded by the Lead each goes to,
// Leads by name and the lines with no Lead last.
func (s *Service) invoiceGroups(ctx context.Context, items []InvoiceItem) ([]InvoiceGroup, error) {
	if len(items) == 0 {
		return nil, nil
	}
	resolver, err := s.newLeadResolver(ctx, items)
	if err != nil {
		return nil, err
	}
	groups := []InvoiceGroup{}
	at := map[string]int{}
	for _, it := range items {
		lead := resolver.leadOf(it)
		key := ""
		if lead != nil {
			key = lead.StaffID
		}
		i, ok := at[key]
		if !ok {
			i = len(groups)
			at[key] = i
			groups = append(groups, InvoiceGroup{Lead: lead})
		}
		groups[i].Items = append(groups[i].Items, it)
		groups[i].SystemTotal += it.Planned
		groups[i].Payable += it.Payable
	}
	slices.SortStableFunc(groups, func(a, b InvoiceGroup) int {
		switch {
		case (a.Lead == nil) != (b.Lead == nil):
			if a.Lead == nil {
				return 1
			}
			return -1
		case a.Lead == nil:
			return 0
		}
		return strings.Compare(a.Lead.Name, b.Lead.Name)
	})
	return groups, nil
}

// leadResolver is invoice_routing.LeadResolver: who holds each school, who
// among them and the officers named is a Lead, and the Lead each reports to.
type leadResolver struct {
	holders   map[string][]string
	lead      map[string]*InvoiceLead
	staffFor  map[string]string
	reportsTo map[string]*InvoiceLead
}

func (s *Service) newLeadResolver(ctx context.Context, items []InvoiceItem) (*leadResolver, error) {
	r := &leadResolver{holders: map[string][]string{}, lead: map[string]*InvoiceLead{}, staffFor: map[string]string{},
		reportsTo: map[string]*InvoiceLead{}}
	schools, officers := []string{}, []string{}
	for _, it := range items {
		if it.schoolID != "" {
			schools = append(schools, it.schoolID)
		}
		for _, v := range []string{it.responsible, it.monitor} {
			if v != "" {
				officers = append(officers, v)
			}
		}
	}
	role := rules.PartnerInvoice.LeadRole
	rows, err := s.db.Query(ctx, `SELECT a.school_id, a.staff_id FROM staff_school_assignment a
JOIN staff_profile sp ON sp.id = a.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE a.school_id = ANY($1) ORDER BY u.name, a.staff_id`, schools)
	if err != nil {
		return nil, fmt.Errorf("activities: reading who holds the invoice's schools: %w", err)
	}
	holderIDs := []string{}
	for rows.Next() {
		var school, staff string
		if err := rows.Scan(&school, &staff); err != nil {
			rows.Close()
			return nil, err
		}
		r.holders[school] = append(r.holders[school], staff)
		holderIDs = append(holderIDs, staff)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT sp.id, sp.user_id, COALESCE(NULLIF(u.name, ''), u.email, ''),
  (u.active_role = $3 OR COALESCE($3 = ANY(u.roles), false))
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE (sp.id = ANY($1) OR sp.id = ANY($2) OR sp.user_id = ANY($2)) AND sp.deleted_at IS NULL`,
		holderIDs, officers, role)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the invoice's people: %w", err)
	}
	staffIDs := []string{}
	for rows.Next() {
		var l InvoiceLead
		var lead bool
		if err := rows.Scan(&l.StaffID, &l.UserID, &l.Name, &lead); err != nil {
			rows.Close()
			return nil, err
		}
		r.staffFor[l.StaffID] = l.StaffID
		if l.UserID != "" {
			r.staffFor[l.UserID] = l.StaffID
		}
		staffIDs = append(staffIDs, l.StaffID)
		if lead {
			r.lead[l.StaffID] = &l
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT l.supervisee_id, sup.id, sup.user_id, COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_supervisor_assignment l JOIN staff_profile sup ON sup.id = l.supervisor_id JOIN "user" u ON u.id = sup.user_id
WHERE (u.active_role = $2 OR COALESCE($2 = ANY(u.roles), false)) AND l.supervisee_id = ANY($1) AND sup.deleted_at IS NULL
ORDER BY u.name, l.supervisor_id`, staffIDs, role)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the Leads the invoice's people report to: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var supervisee string
		var l InvoiceLead
		if err := rows.Scan(&supervisee, &l.StaffID, &l.UserID, &l.Name); err != nil {
			return nil, err
		}
		if _, ok := r.reportsTo[supervisee]; !ok {
			r.reportsTo[supervisee] = &l
		}
	}
	return r, rows.Err()
}

func (r *leadResolver) leadOfPerson(person string) *InvoiceLead {
	staff, ok := r.staffFor[person]
	if !ok || person == "" {
		return nil
	}
	if l, ok := r.lead[staff]; ok {
		return l
	}
	return r.reportsTo[staff]
}

// leadOf is lead_of: a Lead who holds the school, else the Lead a holder
// reports to, else the Lead of the officer the activity names.
func (r *leadResolver) leadOf(it InvoiceItem) *InvoiceLead {
	holders := r.holders[it.schoolID]
	for _, staff := range holders {
		if l, ok := r.lead[staff]; ok {
			return l
		}
	}
	for _, staff := range holders {
		if l, ok := r.reportsTo[staff]; ok {
			return l
		}
	}
	for _, person := range []string{it.monitor, it.responsible} {
		if l := r.leadOfPerson(person); l != nil {
			return l
		}
	}
	return nil
}
