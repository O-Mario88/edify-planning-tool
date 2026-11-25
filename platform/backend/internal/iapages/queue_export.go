package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// The IA queues' exports (apps.activities.ia_export): each queue's own
// rows, filtered and ordered as the page reads them, in one sheet whose
// columns are the same for every queue.

// queueExportHeaders are ia_export.HEADERS.
var queueExportHeaders = []string{"Activity ID", "Activity Type", "Activity", "Delivered By", "Partner",
	"Responsible Staff", "School ID", "School Name", "District", "Cluster", "Planned Date", "Delivered On",
	"Sent for Verification", "Days Waiting", "Purpose of Visit", "Focus Intervention", "SSA Expected",
	"SSA Not Collected Reason", "Teachers Attended", "Leaders Attended", "Other Participants", "Salesforce ID",
	"Evidence", "Status", "Verification", "Verified By", "Verified On", "Return Reasons", "Payment Status",
	"Planned Cost (UGX)"}

// queueExportFormats are the sheet's date and money columns.
var queueExportFormats = map[int]string{11: "d mmm yyyy", 12: "d mmm yyyy", 13: "d mmm yyyy", 27: "d mmm yyyy", 30: "#,##0"}

// waitingStatuses are the statuses whose days waiting the sheet counts.
var waitingStatuses = []string{"awaiting_ia_verification", "submitted_to_pl"}

// queueExport is one queue's export: its file's stem, its sheet's title, and
// the ids of its rows in the page's order (the reach's WHERE given).
type queueExport struct {
	stem, title string
	ids         func(where string) string
}

var queueExports = map[string]queueExport{
	strings.TrimSuffix(ReturnedPath, "/"): {"ia-returned", "Returned Activities", func(where string) string {
		return `SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.status = 'returned_by_ia' AND ` + where + ` ORDER BY a.updated_at DESC`
	}},
	strings.TrimSuffix(PartnerEvidencePath, "/"): {"ia-partner-evidence", "Partner Evidence", func(where string) string {
		return `SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.delivery_type = 'partner' AND a.status = 'awaiting_ia_verification' AND ` + where + `
ORDER BY a.submitted_to_ia_at`
	}},
	strings.TrimSuffix(HistoryPath, "/"): {"ia-verification-history", "Verification History", func(where string) string {
		return `SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE ` + where + ` AND EXISTS (SELECT 1 FROM ia_verification_history h WHERE h.activity_id = a.id)
ORDER BY a.ia_confirmed_at DESC, a.pl_reviewed_at DESC, a.id`
	}},
}

// QueueExportRoute names a queue's export for its page path (the page asked
// with ?export=…), or none.
func (s *Service) QueueExportRoute(target string) (func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error), bool) {
	if target == strings.TrimSuffix(VerificationPath, "/") {
		return s.verificationExport, true
	}
	q, ok := queueExports[target]
	if !ok {
		return nil, false
	}
	page := target + "/"
	return func(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
		return s.queueExport(ctx, p, page, q, query)
	}, true
}

// queueGate is require_export_permission, then the page's own gate; handled
// false when the page did not ask for its export.
func queueGate(p auth.Principal, page string, query url.Values) (bool, error) {
	if strings.TrimSpace(query.Get("export")) == "" {
		return false, nil
	}
	if !slices.Contains(rules.ExportRoles, p.ActiveRole) {
		return true, workbook.Refusal(analyticsExportRefusal)
	}
	if role, ok := rules.Pages[page].Roles[p.ActiveRole]; !ok || !role.Page {
		return true, pagegate.ErrNotAvailable
	}
	return true, nil
}

func (s *Service) queueExport(ctx context.Context, p auth.Principal, page string, q queueExport, query url.Values) (string, []workbook.Sheet, bool, error) {
	if handled, err := queueGate(p, page, query); !handled || err != nil {
		return "", nil, handled, err
	}
	where, args, err := reach(ctx, s.db, p, s.now(), nil)
	if err != nil {
		return "", nil, true, err
	}
	return s.queueFile(ctx, q.stem, q.title, q.ids(where), args)
}

// verificationExport is the Verification queue's: its population filtered
// as the page filters it, in its order, every row.
func (s *Service) verificationExport(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
	if handled, err := queueGate(p, VerificationPath, query); !handled || err != nil {
		return "", nil, handled, err
	}
	for key := range query {
		if !slices.Contains(verificationQuery, key) && key != "export" && key != "format" {
			return "", nil, false, nil
		}
	}
	scope, err := s.verificationScope(ctx, p, query)
	if err != nil {
		return "", nil, true, err
	}
	sql := "SELECT a.id " + scope.sql + " " + scope.order()
	return s.queueFile(ctx, "ia-verification-queue", "Verification Queue", sql, scope.args)
}

// queueFile reads the rows' ids in order and writes their sheet.
func (s *Service) queueFile(ctx context.Context, stem, title, sql string, args []any) (string, []workbook.Sheet, bool, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return "", nil, true, fmt.Errorf("iapages: reading the queue's rows: %w", err)
	}
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return "", nil, true, fmt.Errorf("iapages: reading the queue's rows: %w", err)
		}
		ids = append(ids, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return "", nil, true, fmt.Errorf("iapages: reading the queue's rows: %w", err)
	}
	sheet, err := s.queueSheet(ctx, title, ids)
	if err != nil {
		return "", nil, true, err
	}
	return stem, []workbook.Sheet{sheet}, true, nil
}

// queueRow is what ia_export.sheet reads of one activity.
type queueRow struct {
	id, activityType, name, delivery, partner, owner, schoolCode, schoolName, district, cluster string
	planned, scheduled, delivered, sent, confirmedAt, reviewedAt                                *time.Time
	purpose, purposeText, focus, notCollected, salesforce, evidence, status, verification       string
	confirmedBy, reviewedBy, payment, reasons                                                   string
	expected, hasSchool                                                                         bool
	teachers, leaders, others                                                                   *int
	cost                                                                                        int64
}

// queueSheet is ia_export.sheet for these activities, in the order given.
func (s *Service) queueSheet(ctx context.Context, title string, ids []string) (workbook.Sheet, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.activity_name_snapshot, ''), COALESCE(a.delivery_type, ''),
       COALESCE(a.assigned_partner_id, ''), COALESCE(NULLIF(a.responsible_staff_id, ''), a.monitored_by_staff_id, ''),
       a.school_id IS NOT NULL, COALESCE(sc.school_id, ''), COALESCE(sc.name, ''), COALESCE(d.name, ''), COALESCE(cl.name, ''),
       a.planned_date, a.scheduled_date, a.actual_delivery_date, a.submitted_to_ia_at, a.ia_confirmed_at, a.pl_reviewed_at,
       COALESCE(a.purpose_type, ''), COALESCE(a.activity_purpose_text, ''), COALESCE(a.focus_intervention, ''),
       a.ssa_collection_expected, COALESCE(a.ssa_not_collected_reason, ''), a.teachers_attended, a.leaders_attended,
       a.other_participants, COALESCE(a.salesforce_activity_id, ''), COALESCE(a.evidence_status, ''), COALESCE(a.status, ''),
       COALESCE(a.ia_verification_status, ''), COALESCE(a.ia_confirmed_by, ''), COALESCE(a.pl_reviewed_by, ''),
       COALESCE(a.payment_status, ''), COALESCE(a.est_cost_cents, 0),
       COALESCE((SELECT string_agg(r.reason, ', ') FROM ia_verification v JOIN ia_returned_reason r ON r.verification_id = v.id
                 WHERE v.activity_id = a.id), '')
FROM unnest($1::varchar[]) WITH ORDINALITY AS t(id, n) JOIN activity a ON a.id = t.id
LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN district d ON d.id = sc.district_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
ORDER BY t.n`, ids)
	if err != nil {
		return workbook.Sheet{}, fmt.Errorf("iapages: reading the queue's activities: %w", err)
	}
	var list []queueRow
	for rows.Next() {
		var r queueRow
		if err := rows.Scan(&r.id, &r.activityType, &r.name, &r.delivery, &r.partner, &r.owner, &r.hasSchool, &r.schoolCode,
			&r.schoolName, &r.district, &r.cluster, &r.planned, &r.scheduled, &r.delivered, &r.sent, &r.confirmedAt,
			&r.reviewedAt, &r.purpose, &r.purposeText, &r.focus, &r.expected, &r.notCollected, &r.teachers, &r.leaders,
			&r.others, &r.salesforce, &r.evidence, &r.status, &r.verification, &r.confirmedBy, &r.reviewedBy,
			&r.payment, &r.cost, &r.reasons); err != nil {
			rows.Close()
			return workbook.Sheet{}, fmt.Errorf("iapages: reading the queue's activities: %w", err)
		}
		list = append(list, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return workbook.Sheet{}, fmt.Errorf("iapages: reading the queue's activities: %w", err)
	}
	owners, partnerIDs, verifierIDs := []string{}, []string{}, []string{}
	for _, r := range list {
		owners = append(owners, r.owner)
		if r.partner != "" {
			partnerIDs = append(partnerIDs, r.partner)
		}
		verifierIDs = append(verifierIDs, r.confirmedBy, r.reviewedBy)
	}
	staff, err := staffNames(ctx, s.db, owners)
	if err != nil {
		return workbook.Sheet{}, err
	}
	partners, err := livePartnerNames(ctx, s.db, partnerIDs)
	if err != nil {
		return workbook.Sheet{}, err
	}
	verifiers, err := accountNames(ctx, s.db, verifierIDs)
	if err != nil {
		return workbook.Sheet{}, err
	}
	today := localDay(s.now())
	out := make([][]workbook.Cell, 0, len(list))
	for _, r := range list {
		out = append(out, r.cells(staff, partners, verifiers, today))
	}
	return workbook.Sheet{Title: title, Headers: queueExportHeaders, Rows: out, NumberFormats: queueExportFormats}, nil
}

func (r queueRow) cells(staff, partners, verifiers map[string]string, today time.Time) []workbook.Cell {
	day := func(t *time.Time) *time.Time {
		if t == nil {
			return nil
		}
		d := localDay(*t)
		return &d
	}
	date := func(t *time.Time) workbook.Cell {
		if t == nil {
			return workbook.Empty()
		}
		return workbook.Date(*t)
	}
	count := func(n *int) workbook.Cell {
		if n == nil {
			return workbook.Empty()
		}
		return workbook.Int(int64(*n))
	}
	text := func(m map[string]string, key string) string {
		if v, ok := m[key]; ok {
			return v
		}
		return key
	}
	typeLabel := text(rules.ActivityTypes, r.activityType)
	name := r.name
	if name == "" {
		name = typeLabel
	}
	delivered := "Staff"
	if r.delivery == "partner" {
		delivered = "Partner"
	}
	planned := r.planned
	if planned == nil {
		planned = day(r.scheduled)
	}
	sent := day(r.sent)
	waiting := workbook.Empty()
	if sent != nil && slices.Contains(waitingStatuses, r.status) {
		waiting = workbook.Int(int64(today.Sub(*sent).Hours() / 24))
	}
	verifiedBy := r.confirmedBy
	if verifiedBy == "" {
		verifiedBy = r.reviewedBy
	}
	verifiedOn := day(r.confirmedAt)
	if verifiedOn == nil {
		verifiedOn = day(r.reviewedAt)
	}
	purpose, ok := rules.VisitPurposeLabels[r.purpose]
	if !ok {
		purpose = r.purposeText
	}
	partner := ""
	if r.partner != "" {
		partner = partners[r.partner]
	}
	expected := "No"
	if r.expected {
		expected = "Yes"
	}
	schoolCode, schoolName := "", ""
	if r.hasSchool {
		schoolCode, schoolName = r.schoolCode, r.schoolName
	}
	return []workbook.Cell{
		workbook.Text(r.id), workbook.Text(typeLabel), workbook.Text(name), workbook.Text(delivered), workbook.Text(partner),
		workbook.Text(text(staff, r.owner)), workbook.Text(schoolCode), workbook.Text(schoolName), workbook.Text(r.district),
		workbook.Text(r.cluster), date(planned), date(r.delivered), date(sent), waiting, workbook.Text(purpose),
		workbook.Text(text(rules.InterventionLabels, r.focus)), workbook.Text(expected), workbook.Text(r.notCollected),
		count(r.teachers), count(r.leaders), count(r.others), workbook.Text(r.salesforce), workbook.Text(capitalized(r.evidence)),
		workbook.Text(r.statusLabel()), workbook.Text(capitalized(r.verification)),
		workbook.Text(text(verifiers, verifiedBy)), date(verifiedOn), workbook.Text(r.reasons),
		workbook.Text(capitalized(r.payment)), workbook.Int(r.cost),
	}
}

// statusLabel is Activity.get_status_display: staff work's verification
// statuses say the Programme Lead verifies it.
func (r queueRow) statusLabel() string {
	if label, ok := rules.StaffVerificationLabels[r.status]; ok && r.delivery != "partner" {
		return label
	}
	if label, ok := rules.ActivityStatusLabels[r.status]; ok {
		return label
	}
	return r.status
}

// capitalized is ia_export._label: underscores as spaces, trimmed, the first
// letter upper and the rest lower (str.capitalize).
func capitalized(value string) string {
	value = strings.TrimSpace(strings.ReplaceAll(value, "_", " "))
	if value == "" {
		return ""
	}
	r := []rune(strings.ToLower(value))
	r[0] = []rune(strings.ToUpper(string(r[0])))[0]
	return string(r)
}
