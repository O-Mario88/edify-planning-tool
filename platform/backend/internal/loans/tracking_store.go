package loans

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Filter narrows the staff's lists, dashboard and export.
type Filter struct {
	Search         string
	PartnerID      string
	District       string
	Status         string
	DeliveryStatus string
	From, To       time.Time // submission days, inclusive; zero for open-ended
	MinRequested   int64
	MaxRequested   int64
	NeedsFollowUp  bool
	MatchStatus    string
	PurposeCode    string
	// SummaryOnly: the caller does not see directors' names, so a search
	// never matches on one.
	SummaryOnly bool
}

const pageSize = 50

// openStatuses are the statuses of an application still in progress.
const openStatuses = `('submitted', 'awaiting_lender_receipt', 'received_by_lender', 'under_review', 'information_requested', 'approved')`

// where turns a Filter into SQL conditions on application a (school s).
func (f Filter) where(today time.Time) (string, []any) {
	var conditions []string
	var args []any
	add := func(condition string, value any) {
		args = append(args, value)
		conditions = append(conditions, strings.ReplaceAll(condition, "$?", fmt.Sprintf("$%d", len(args))))
	}
	if term := strings.TrimSpace(f.Search); term != "" {
		escaped := strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(term)
		director := ` OR a.director_name ILIKE $?`
		if f.SummaryOnly {
			director = ""
		}
		add(`(a.school_name ILIKE $? OR a.reference ILIKE $?`+director+` OR COALESCE(s.school_id, '') ILIKE $?)`,
			"%"+escaped+"%")
	}
	if f.PartnerID != "" {
		add(`a.partner_id = $?`, f.PartnerID)
	}
	if f.District != "" {
		add(`lower(a.district_name) = lower($?)`, f.District)
	}
	if f.Status != "" {
		add(`a.status = $?`, f.Status)
	}
	if f.DeliveryStatus != "" {
		add(`a.delivery_status = $?`, f.DeliveryStatus)
	}
	if f.MatchStatus != "" {
		add(`a.school_match_status = $?`, f.MatchStatus)
	}
	if f.PurposeCode != "" {
		add(`a.purpose_code = $?`, f.PurposeCode)
	}
	if !f.From.IsZero() {
		add(`a.submitted_at >= $?`, dayOf(f.From))
	}
	if !f.To.IsZero() {
		add(`a.submitted_at < $?`, dayOf(f.To).AddDate(0, 0, 1))
	}
	if f.MinRequested > 0 {
		add(`a.requested_amount_ugx >= $?`, f.MinRequested)
	}
	if f.MaxRequested > 0 {
		add(`a.requested_amount_ugx <= $?`, f.MaxRequested)
	}
	if f.NeedsFollowUp {
		add(`a.status IN `+openStatuses+` AND (a.next_follow_up_on IS NULL OR a.next_follow_up_on < $?)`, today)
	}
	if len(conditions) == 0 {
		return "TRUE", args
	}
	return strings.Join(conditions, " AND "), args
}

// Row is one application on the staff list.
type Row struct {
	ID, Reference, SchoolName, EdifySchoolID, District, DirectorName, DirectorPhone string
	Total                                                                           int
	FeesCollected                                                                   int64
	PurposeLabel                                                                    string
	Requested                                                                       int64
	PartnerID, LenderName                                                           string
	SubmittedAt                                                                     time.Time
	Status, DeliveryStatus                                                          string
	LastFollowUp                                                                    *time.Time
	NextFollowUp                                                                    *time.Time
	ResponsibleBTOName, MatchStatus                                                 string
	Approved, Disbursed                                                             *int64
}

const rowColumns = `
a.id, a.reference, a.school_name, COALESCE(s.school_id, ''), a.district_name, a.director_name, a.director_phone,
a.total_enrollment, a.average_fees_collected_ugx, a.purpose_label, a.requested_amount_ugx, a.partner_id,
a.lender_name, a.submitted_at, a.status, a.delivery_status, a.last_follow_up_at, a.next_follow_up_on,
a.responsible_bto_name, a.school_match_status, a.approved_amount_ugx, a.disbursed_amount_ugx`

const fromApplications = ` FROM school_loans.application a LEFT JOIN school s ON s.id = a.school_id`

func scanRows(rows pgx.Rows) ([]Row, error) {
	defer rows.Close()
	var out []Row
	for rows.Next() {
		var r Row
		if err := rows.Scan(&r.ID, &r.Reference, &r.SchoolName, &r.EdifySchoolID, &r.District, &r.DirectorName,
			&r.DirectorPhone, &r.Total, &r.FeesCollected, &r.PurposeLabel, &r.Requested, &r.PartnerID, &r.LenderName,
			&r.SubmittedAt, &r.Status, &r.DeliveryStatus, &r.LastFollowUp, &r.NextFollowUp, &r.ResponsibleBTOName,
			&r.MatchStatus, &r.Approved, &r.Disbursed); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// Applications is one page of the filtered applications, newest first, and
// how many match in all.
func (s *Store) Applications(ctx context.Context, filter Filter, page int, today time.Time) ([]Row, int, error) {
	where, args := filter.where(today)
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*)`+fromApplications+` WHERE `+where, args...).Scan(&total); err != nil {
		return nil, 0, fmt.Errorf("loans: counting applications: %w", err)
	}
	if page < 1 {
		page = 1
	}
	rows, err := s.db.Query(ctx, `SELECT `+rowColumns+fromApplications+` WHERE `+where+
		fmt.Sprintf(` ORDER BY a.submitted_at DESC LIMIT %d OFFSET %d`, pageSize, (page-1)*pageSize), args...)
	if err != nil {
		return nil, 0, fmt.Errorf("loans: listing applications: %w", err)
	}
	found, err := scanRows(rows)
	return found, total, err
}

// maxExportRows bounds one export.
const maxExportRows = 5000

// ExportRows are every filtered application, for the CSV export.
func (s *Store) ExportRows(ctx context.Context, filter Filter, today time.Time) ([]Row, error) {
	where, args := filter.where(today)
	rows, err := s.db.Query(ctx, `SELECT `+rowColumns+fromApplications+` WHERE `+where+
		fmt.Sprintf(` ORDER BY a.submitted_at DESC LIMIT %d`, maxExportRows), args...)
	if err != nil {
		return nil, fmt.Errorf("loans: exporting applications: %w", err)
	}
	return scanRows(rows)
}

// SchoolApplications are a directory school's portal applications.
func (s *Store) SchoolApplications(ctx context.Context, schoolID string) ([]Row, error) {
	rows, err := s.db.Query(ctx, `SELECT `+rowColumns+fromApplications+` WHERE a.school_id = $1 ORDER BY a.submitted_at DESC`, schoolID)
	if err != nil {
		return nil, fmt.Errorf("loans: reading a school's applications: %w", err)
	}
	return scanRows(rows)
}

// Totals are the dashboard's headline figures.
type Totals struct {
	Applications, AwaitingReceipt, UnderReview, Approved, Declined, Disbursed int
	Requested, ApprovedAmount, DisbursedAmount                                int64
	NeedsFollowUp, DeliveryProblems, NeedsSchoolMatch                         int
}

// deliveryStuck is how long a queued notification may wait before it counts
// as a delivery problem.
const deliveryStuck = time.Hour

// Totals counts the filtered applications. "Approved" counts every
// application with an approval recorded, including those since disbursed;
// "Disbursed" counts only lender-confirmed disbursements. Neither is ever
// inferred from a requested amount.
func (s *Store) Totals(ctx context.Context, filter Filter, now time.Time) (Totals, error) {
	where, args := filter.where(dayOf(now))
	n := len(args)
	args = append(args, dayOf(now), now.Add(-deliveryStuck))
	var t Totals
	err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*),
  count(*) FILTER (WHERE a.status IN ('submitted', 'awaiting_lender_receipt')),
  count(*) FILTER (WHERE a.status IN ('received_by_lender', 'under_review', 'information_requested')),
  count(*) FILTER (WHERE a.approved_amount_ugx IS NOT NULL),
  count(*) FILTER (WHERE a.status = 'declined'),
  count(*) FILTER (WHERE a.disbursed_amount_ugx IS NOT NULL),
  COALESCE(sum(a.requested_amount_ugx), 0)::bigint,
  COALESCE(sum(a.approved_amount_ugx), 0)::bigint,
  COALESCE(sum(a.disbursed_amount_ugx), 0)::bigint,
  count(*) FILTER (WHERE a.status IN %[1]s AND (a.next_follow_up_on IS NULL OR a.next_follow_up_on < $%[2]d)),
  count(*) FILTER (WHERE a.status IN %[1]s AND (a.delivery_status = 'failed'
    OR (a.delivery_status = 'queued' AND a.submitted_at < $%[3]d))),
  count(*) FILTER (WHERE a.school_match_status IN ('needs_review', 'unmatched'))
`+fromApplications+` WHERE `+where, openStatuses, n+1, n+2), args...).Scan(
		&t.Applications, &t.AwaitingReceipt, &t.UnderReview, &t.Approved, &t.Declined, &t.Disbursed,
		&t.Requested, &t.ApprovedAmount, &t.DisbursedAmount, &t.NeedsFollowUp, &t.DeliveryProblems, &t.NeedsSchoolMatch)
	if err != nil {
		return t, fmt.Errorf("loans: totalling applications: %w", err)
	}
	return t, nil
}

// Group is one line of a breakdown.
type Group struct {
	Key, Label                                 string
	Applications, Approved, Disbursed          int
	Requested, ApprovedAmount, DisbursedAmount int64
}

// Breakdowns the dashboard offers: the grouping key and its label, as SQL.
// Edify's financial year runs October to September and is named by the
// year it ends in; its first quarter is October to December.
var breakdowns = map[string][2]string{
	"lender":   {`a.partner_id`, `max(a.lender_name)`},
	"district": {`lower(a.district_name)`, `max(a.district_name)`},
	"month":    {`to_char(a.submitted_at AT TIME ZONE 'Africa/Kampala', 'YYYY-MM')`, `to_char(min(a.submitted_at AT TIME ZONE 'Africa/Kampala'), 'Mon YYYY')`},
	"quarter":  {`fy_quarter`, `max(fy_quarter)`},
	"year":     {`fy`, `max(fy)`},
	"purpose":  {`a.purpose_code`, `max(a.purpose_label)`},
	"status":   {`a.status`, `a.status`},
}

// Breakdown groups the filtered applications by one of breakdowns' keys.
func (s *Store) Breakdown(ctx context.Context, by string, filter Filter, today time.Time) ([]Group, error) {
	spec, ok := breakdowns[by]
	if !ok {
		return nil, fmt.Errorf("loans: no breakdown by %q", by)
	}
	where, args := filter.where(today)
	order := `count(*) DESC, 1`
	if by == "month" || by == "quarter" || by == "year" {
		order = `1 DESC`
	}
	query := `
WITH a AS (
  SELECT a.*, s.school_id AS edify_school_id,
    'FY' || (extract(year FROM a.submitted_at AT TIME ZONE 'Africa/Kampala')::int
      + CASE WHEN extract(month FROM a.submitted_at AT TIME ZONE 'Africa/Kampala') >= 10 THEN 1 ELSE 0 END) AS fy,
    'FY' || (extract(year FROM a.submitted_at AT TIME ZONE 'Africa/Kampala')::int
      + CASE WHEN extract(month FROM a.submitted_at AT TIME ZONE 'Africa/Kampala') >= 10 THEN 1 ELSE 0 END)
      || ' Q' || (((extract(month FROM a.submitted_at AT TIME ZONE 'Africa/Kampala')::int + 2) % 12) / 3 + 1) AS fy_quarter
  ` + fromApplications + ` WHERE ` + where + `
)
SELECT ` + spec[0] + `, ` + spec[1] + `, count(*),
  count(*) FILTER (WHERE a.approved_amount_ugx IS NOT NULL),
  count(*) FILTER (WHERE a.disbursed_amount_ugx IS NOT NULL),
  COALESCE(sum(a.requested_amount_ugx), 0)::bigint,
  COALESCE(sum(a.approved_amount_ugx), 0)::bigint,
  COALESCE(sum(a.disbursed_amount_ugx), 0)::bigint
FROM a GROUP BY 1` + map[bool]string{true: ", a.status", false: ""}[by == "status"] + ` ORDER BY ` + order + ` LIMIT 60`
	rows, err := s.db.Query(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("loans: breaking applications down by %s: %w", by, err)
	}
	defer rows.Close()
	var out []Group
	for rows.Next() {
		var g Group
		if err := rows.Scan(&g.Key, &g.Label, &g.Applications, &g.Approved, &g.Disbursed, &g.Requested,
			&g.ApprovedAmount, &g.DisbursedAmount); err != nil {
			return nil, err
		}
		if by == "status" {
			g.Label = StatusLabel(g.Key)
		}
		out = append(out, g)
	}
	return out, rows.Err()
}

// Measure is a processing measure, reported only when it rests on enough
// applications to mean something.
type Measure struct {
	Key, Label, Unit, Note string
	Value                  float64
	BasedOn                int
	Available              bool
}

// minimumSample is the fewest applications a measure is reported on.
const minimumSample = 3

// stalledAfter: an open application with no recorded activity this long is
// stalled.
const stalledAfter = 14 * 24 * time.Hour

// Measures computes the processing measures over the filtered applications.
func (s *Store) Measures(ctx context.Context, filter Filter, now time.Time) ([]Measure, error) {
	where, args := filter.where(dayOf(now))
	args = append(args, now.Add(-stalledAfter))
	stalledArg := len(args)
	var (
		ackHours, processingDays, averageLoan                                   *float64
		acknowledged, decided, approvedEver, declined, disbursed, open, stalled int
	)
	err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT
  avg(extract(epoch FROM a.lender_received_at - a.submitted_at) / 3600) FILTER (WHERE a.lender_received_at IS NOT NULL),
  count(*) FILTER (WHERE a.lender_received_at IS NOT NULL),
  avg(extract(epoch FROM a.decided_at - a.submitted_at) / 86400) FILTER (WHERE a.decided_at IS NOT NULL),
  count(*) FILTER (WHERE a.decided_at IS NOT NULL),
  count(*) FILTER (WHERE a.approved_amount_ugx IS NOT NULL),
  count(*) FILTER (WHERE a.status = 'declined'),
  count(*) FILTER (WHERE a.disbursed_amount_ugx IS NOT NULL),
  avg(a.disbursed_amount_ugx) FILTER (WHERE a.disbursed_amount_ugx IS NOT NULL),
  count(*) FILTER (WHERE a.status IN %[1]s),
  count(*) FILTER (WHERE a.status IN %[1]s AND a.updated_at < $%[2]d
    AND (a.last_follow_up_at IS NULL OR a.last_follow_up_at < $%[2]d))
`+fromApplications+` WHERE `+where, openStatuses, stalledArg), args...).Scan(
		&ackHours, &acknowledged, &processingDays, &decided, &approvedEver, &declined, &disbursed,
		&averageLoan, &open, &stalled)
	if err != nil {
		return nil, fmt.Errorf("loans: measuring applications: %w", err)
	}
	ratio := func(part, whole int) float64 {
		if whole == 0 {
			return 0
		}
		return 100 * float64(part) / float64(whole)
	}
	value := func(v *float64) float64 {
		if v == nil {
			return 0
		}
		return *v
	}
	measure := func(key, label, unit, note string, v float64, basedOn int) Measure {
		return Measure{Key: key, Label: label, Unit: unit, Note: note, Value: v, BasedOn: basedOn,
			Available: basedOn >= minimumSample}
	}
	return []Measure{
		measure("acknowledgement_time", "Lender acknowledgement time", "hours",
			"From submission to the lender's first recorded step.", value(ackHours), acknowledged),
		measure("processing_time", "Average processing time", "days",
			"From submission to the lender's approval or decline.", value(processingDays), decided),
		measure("approval_rate", "Approval rate", "percent",
			"Approved out of all applications the lenders decided.", ratio(approvedEver, approvedEver+declined),
			approvedEver+declined),
		measure("disbursement_conversion", "Disbursement conversion", "percent",
			"Disbursed out of all approved.", ratio(disbursed, approvedEver), approvedEver),
		measure("average_loan", "Average loan disbursed", "ugx",
			"Lender-confirmed disbursements only.", value(averageLoan), disbursed),
		measure("stalled_rate", "Stalled applications", "percent",
			"Open applications with nothing recorded for 14 days.", ratio(stalled, open), open),
	}, nil
}

// RecordFollowUp stores a staff follow-up or oversight note and moves the
// application's follow-up dates. It never changes the status.
func (s *Store) RecordFollowUp(ctx context.Context, f FollowUp) (FollowUp, error) {
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		var partnerID string
		if err := tx.QueryRow(ctx, `SELECT partner_id FROM school_loans.application WHERE id = $1 FOR UPDATE`,
			f.ApplicationID).Scan(&partnerID); errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		} else if err != nil {
			return err
		}
		id, err := NewID()
		if err != nil {
			return err
		}
		f.ID, f.LenderPartnerID = id, partnerID
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.follow_up (id, application_id, staff_id, staff_name, staff_active_role, followed_up_on,
  channel, lender_partner_id, notes, lender_feedback, next_action, next_follow_up_on, document_reference,
  is_oversight, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)`,
			f.ID, f.ApplicationID, f.StaffID, f.StaffName, f.StaffRole, f.FollowedUpOn, f.Channel, partnerID,
			f.Notes, f.LenderFeedback, f.NextAction, nullableDate(f.NextFollowUpOn), f.DocumentReference,
			f.IsOversight, f.CreatedAt); err != nil {
			return fmt.Errorf("loans: storing a follow-up: %w", err)
		}
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.application
SET last_follow_up_at = $2, next_follow_up_on = COALESCE($3, next_follow_up_on), updated_at = $2
WHERE id = $1`, f.ApplicationID, f.CreatedAt, nullableDate(f.NextFollowUpOn)); err != nil {
			return err
		}
		kind, note := "follow_up", "Followed up by "+f.Channel+". "+f.Notes
		if f.IsOversight {
			kind, note = "oversight_note", f.Notes
		}
		return appendEvent(ctx, tx, Event{ApplicationID: f.ApplicationID, Kind: kind, ActorKind: "staff",
			ActorID: f.StaffID, ActorName: f.StaffName, Note: note, Evidence: f.DocumentReference})
	})
	return f, err
}

// FollowUp is a staff follow-up or oversight note.
type FollowUp struct {
	ID, ApplicationID, StaffID, StaffName, StaffRole, Channel, LenderPartnerID string
	FollowedUpOn                                                               time.Time
	Notes, LenderFeedback, NextAction, DocumentReference                       string
	NextFollowUpOn                                                             time.Time
	IsOversight                                                                bool
	CreatedAt                                                                  time.Time
	LenderName                                                                 string
}

// FollowUps are an application's follow-ups, newest first.
func (s *Store) FollowUps(ctx context.Context, applicationID string) ([]FollowUp, error) {
	rows, err := s.db.Query(ctx, `
SELECT f.id, f.staff_id, f.staff_name, f.staff_active_role, f.channel, f.followed_up_on, f.notes, f.lender_feedback,
  f.next_action, f.document_reference, f.next_follow_up_on, f.is_oversight, f.created_at, a.lender_name
FROM school_loans.follow_up f JOIN school_loans.application a ON a.id = f.application_id
WHERE f.application_id = $1 ORDER BY f.created_at DESC`, applicationID)
	if err != nil {
		return nil, fmt.Errorf("loans: reading follow-ups: %w", err)
	}
	defer rows.Close()
	var out []FollowUp
	for rows.Next() {
		var f FollowUp
		var next *time.Time
		if err := rows.Scan(&f.ID, &f.StaffID, &f.StaffName, &f.StaffRole, &f.Channel, &f.FollowedUpOn, &f.Notes,
			&f.LenderFeedback, &f.NextAction, &f.DocumentReference, &next, &f.IsOversight, &f.CreatedAt,
			&f.LenderName); err != nil {
			return nil, err
		}
		if next != nil {
			f.NextFollowUpOn = *next
		}
		out = append(out, f)
	}
	return out, rows.Err()
}

// Delivery is one delivery task of an application, as staff see it.
type Delivery struct {
	Kind, Status, LastError, Recipient string
	Attempts                           int
	SentAt                             *time.Time
	NextAttemptAt                      time.Time
}

// Deliveries are an application's delivery tasks, newest first.
func (s *Store) Deliveries(ctx context.Context, applicationID string) ([]Delivery, error) {
	rows, err := s.db.Query(ctx, `
SELECT kind, status, last_error, recipient_email, attempts, sent_at, next_attempt_at
FROM school_loans.delivery_task WHERE application_id = $1 AND kind = 'lender_referral' ORDER BY created_at DESC`,
		applicationID)
	if err != nil {
		return nil, fmt.Errorf("loans: reading deliveries: %w", err)
	}
	defer rows.Close()
	var out []Delivery
	for rows.Next() {
		var d Delivery
		if err := rows.Scan(&d.Kind, &d.Status, &d.LastError, &d.Recipient, &d.Attempts, &d.SentAt, &d.NextAttemptAt); err != nil {
			return nil, err
		}
		if d.Recipient != "" {
			d.Recipient = maskEmail(d.Recipient)
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

// TakeResponsibility makes a BTO responsible for an application and/or
// moves its next follow-up.
func (s *Store) UpdateTracking(ctx context.Context, applicationID, staffID, staffName string, take bool, next time.Time, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE school_loans.application
SET responsible_bto_id = CASE WHEN $2 THEN $3 ELSE responsible_bto_id END,
  responsible_bto_name = CASE WHEN $2 THEN $4 ELSE responsible_bto_name END,
  next_follow_up_on = COALESCE($5, next_follow_up_on), updated_at = $6
WHERE id = $1`, applicationID, take, staffID, staffName, nullableDate(next), now)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return ErrNotFound
		}
		var parts []string
		if take {
			parts = append(parts, staffName+" is now the responsible BTO.")
		}
		if !next.IsZero() {
			parts = append(parts, "Next follow-up "+next.Format("2 January 2006")+".")
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "tracking_updated", ActorKind: "staff",
			ActorID: staffID, ActorName: staffName, Note: strings.Join(parts, " ")})
	})
}

// ResolveMatch links an application to a directory school, or records that
// the school is not in the directory. No directory record is ever created.
func (s *Store) ResolveMatch(ctx context.Context, applicationID string, school *SchoolCandidate, staffID, staffName, note string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		status, schoolID, text := MatchNotInDirectory, (*string)(nil), "Not in the School Directory yet."
		if school != nil {
			status, schoolID = MatchMatched, &school.ID
			text = "Linked to " + school.Name + " (" + school.SchoolID + ")."
		}
		tag, err := tx.Exec(ctx, `
UPDATE school_loans.application
SET school_match_status = $2, school_id = $3, match_method = CASE WHEN $3::text IS NULL THEN '' ELSE 'bto' END,
  matched_by = $4, matched_at = $5, updated_at = $5
WHERE id = $1`, applicationID, status, schoolID, staffID, now)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return ErrNotFound
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "school_match_resolved", ActorKind: "staff",
			ActorID: staffID, ActorName: staffName, Note: strings.TrimSpace(text + " " + note)})
	})
}

// ErrAlreadyQueued: a notification for the application is already waiting.
var ErrAlreadyQueued = errors.New("loans: a notification is already waiting to be sent")

// Resend queues the lender's notification again.
func (s *Store) Resend(ctx context.Context, applicationID, staffID, staffName, note string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var status, partnerID string
		err := tx.QueryRow(ctx, `SELECT status, partner_id FROM school_loans.application WHERE id = $1 FOR UPDATE`,
			applicationID).Scan(&status, &partnerID)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		if !IsOpen(status) {
			return &FieldError{Field: "action", Message: "A " + StatusLabel(status) + " application is not sent again."}
		}
		var waiting int
		if err := tx.QueryRow(ctx, `
SELECT count(*) FROM school_loans.delivery_task
WHERE application_id = $1 AND kind = 'lender_referral' AND status = 'pending'`, applicationID).Scan(&waiting); err != nil {
			return err
		}
		if waiting > 0 {
			return ErrAlreadyQueued
		}
		if err := enqueue(ctx, tx, task{
			Kind: TaskLenderReferral, DedupeKey: "referral:" + applicationID + ":" + now.Format(time.RFC3339Nano),
			ApplicationID: applicationID, PartnerID: partnerID, At: now,
		}); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.application SET delivery_status = 'queued', updated_at = $2
WHERE id = $1 AND delivery_status = 'failed'`, applicationID, now); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "delivery_resent", ActorKind: "staff",
			ActorID: staffID, ActorName: staffName, Note: strings.TrimSpace("Queued to be sent again. " + note)})
	})
}

// LinkLoan links an application to the loan its lender registered in the
// existing loan ledger (bt_mfi_loan), which stays the record of the loan:
// the same school, the same lender, not cancelled.
func (s *Store) LinkLoan(ctx context.Context, applicationID, loanID, staffID, staffName string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var schoolID *string
		var lenderID string
		err := tx.QueryRow(ctx, `SELECT school_id, lender_id FROM school_loans.application WHERE id = $1 FOR UPDATE`,
			applicationID).Scan(&schoolID, &lenderID)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		if schoolID == nil {
			return &FieldError{Field: "mfi_loan_id", Message: "Link the application to its directory school first."}
		}
		var loanSchool, loanLender, loanStatus string
		err = tx.QueryRow(ctx, `SELECT school_id, mfi_id, status FROM bt_mfi_loan WHERE id = $1 AND deleted_at IS NULL`,
			loanID).Scan(&loanSchool, &loanLender, &loanStatus)
		switch {
		case errors.Is(err, pgx.ErrNoRows):
			return &FieldError{Field: "mfi_loan_id", Message: "No registered loan has that id."}
		case err != nil:
			return err
		case loanSchool != *schoolID || loanLender != lenderID:
			return &FieldError{Field: "mfi_loan_id", Message: "That loan belongs to another school or lender."}
		case loanStatus == "canceled":
			return &FieldError{Field: "mfi_loan_id", Message: "A cancelled loan cannot be linked."}
		}
		if _, err := tx.Exec(ctx, `UPDATE school_loans.application SET linked_mfi_loan_id = $2, updated_at = $3 WHERE id = $1`,
			applicationID, loanID, now); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "loan_linked", ActorKind: "staff",
			ActorID: staffID, ActorName: staffName, Note: "Linked to the loan the lender registered (" + loanID + ")."})
	})
}

// invitationLifetime is how long a school-specific link works.
const invitationLifetime = 60 * 24 * time.Hour

// SearchSchools finds directory schools by name or Edify School ID.
func (s *Store) SearchSchools(ctx context.Context, query string) ([]SchoolCandidate, error) {
	escaped := strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(strings.TrimSpace(query))
	return candidates(ctx, s.db, `
SELECT id, COALESCE(school_id, ''), name, COALESCE(district_id, ''), COALESCE(sub_county_id, '')
FROM school WHERE deleted_at IS NULL AND (name ILIKE $1 OR school_id ILIKE $1) ORDER BY name LIMIT 20`,
		"%"+escaped+"%")
}

// DistrictNames maps district ids to names, for showing candidates.
func (s *Store) DistrictNames(ctx context.Context, ids []string) (map[string]string, error) {
	names := map[string]string{}
	if len(ids) == 0 {
		return names, nil
	}
	found, err := places(ctx, s.db, `SELECT id, name FROM district WHERE id = ANY($1)`, ids)
	for _, place := range found {
		names[place.ID] = place.Name
	}
	return names, err
}

// WebFormApplication is an application made through the existing web form.
type WebFormApplication struct {
	ID, Purpose, Status, LenderName string
	Requested                       int64
	SubmittedAt                     time.Time
}

// RegisteredLoan is a loan in the existing loan ledger.
type RegisteredLoan struct {
	ID, LenderName, Purpose, Status string
	Approved, Disbursed             *float64
	DisbursementDate                *time.Time
}

// SchoolLoanRecords are a school's records in the existing loan workflow.
func (s *Store) SchoolLoanRecords(ctx context.Context, schoolID string) ([]WebFormApplication, []RegisteredLoan, error) {
	rows, err := s.db.Query(ctx, `
SELECT la.id, COALESCE(p.label, ''), la.status, COALESCE(m.name, ''), la.requested_amount::bigint, la.submitted_at
FROM bt_loan_application la
LEFT JOIN bt_loan_purpose p ON p.id = la.purpose_id
LEFT JOIN bt_mfi_organization m ON m.id = la.preferred_mfi_id
WHERE la.school_id = $1 AND la.deleted_at IS NULL ORDER BY la.submitted_at DESC`, schoolID)
	if err != nil {
		return nil, nil, fmt.Errorf("loans: reading web-form applications: %w", err)
	}
	var applications []WebFormApplication
	for rows.Next() {
		var a WebFormApplication
		if err := rows.Scan(&a.ID, &a.Purpose, &a.Status, &a.LenderName, &a.Requested, &a.SubmittedAt); err != nil {
			rows.Close()
			return nil, nil, err
		}
		applications = append(applications, a)
	}
	rows.Close()
	rows, err = s.db.Query(ctx, `
SELECT l.id, COALESCE(m.name, ''), COALESCE(p.label, ''), l.status, l.approved_amount::float8,
  l.disbursed_amount::float8, l.disbursement_date
FROM bt_mfi_loan l
LEFT JOIN bt_loan_purpose p ON p.id = l.purpose_id
LEFT JOIN bt_mfi_organization m ON m.id = l.mfi_id
WHERE l.school_id = $1 AND l.deleted_at IS NULL ORDER BY l.disbursement_date DESC NULLS LAST`, schoolID)
	if err != nil {
		return nil, nil, fmt.Errorf("loans: reading registered loans: %w", err)
	}
	defer rows.Close()
	var loans []RegisteredLoan
	for rows.Next() {
		var l RegisteredLoan
		if err := rows.Scan(&l.ID, &l.LenderName, &l.Purpose, &l.Status, &l.Approved, &l.Disbursed, &l.DisbursementDate); err != nil {
			return nil, nil, err
		}
		loans = append(loans, l)
	}
	return applications, loans, rows.Err()
}

// LenderPartnerOf is the Loan Partner a lender's staff member works for
// (through their active membership of its lender), or ErrNotFound.
func (s *Store) LenderPartnerOf(ctx context.Context, userID string) (string, string, error) {
	var partnerID, name string
	err := s.db.QueryRow(ctx, `
SELECT p.id, p.name FROM bt_mfi_membership mm
JOIN partner p ON p.loan_lender_id = mm.mfi_id
WHERE mm.user_id = $1 AND mm.active AND p.deleted_at IS NULL AND p.partner_role = 'loan'
ORDER BY p.name LIMIT 1`, userID).Scan(&partnerID, &name)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", "", ErrNotFound
	}
	return partnerID, name, err
}
