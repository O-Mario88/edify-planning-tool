package financedesks

import (
	"context"
	"fmt"
	"net/url"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Finance Blocked directory (blocked_view over FinanceBlockedReasonService
// .blocked_activities and get_blocked_reasons): every planned activity with
// at least one reason its clearance is blocked, newest first, fifty a page.

const (
	blockedParam = "blocked_page"
	blockedEmpty = "Perfect compliance score! No finance items blocked."
)

// blockedWhere is blocked_activities' four rules as one condition on
// activity a: not IA verified; a partner's work with no evidence; no budget
// line; a Salesforce record and no SF ID. Called-off work is owed nothing.
const blockedWhere = `a.deleted_at IS NULL AND NOT (a.status IS NOT NULL AND a.status = ANY($1))
  AND (NOT (a.status IS NOT NULL AND a.status = ANY($2))
    OR (a.delivery_type = 'partner' AND NOT EXISTS (SELECT 1 FROM evidence_record e WHERE e.activity_id = a.id AND NOT e.quarantined))
    OR NOT EXISTS (SELECT 1 FROM activity_schedule_cost_line l WHERE l.activity_id = a.id)
    OR (NOT (UPPER(COALESCE(a.salesforce_record_type_snapshot, '')) = ANY($3)) AND COALESCE(a.salesforce_activity_id, '') = ''))`

func (s *Service) blocked(ctx context.Context, d role, query url.Values) (*screensv1.GetPageResponse, error) {
	var total int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM activity a WHERE `+blockedWhere,
		rules.NotInPlanStatuses, rules.IAVerifiedStatuses, rules.NoSalesforceRecordTypes).Scan(&total); err != nil {
		return nil, fmt.Errorf("financedesks: counting the blocked work: %w", err)
	}
	h := header("Finance", "Finance Blocked Directory",
		"Review activities that are currently gated because of missing compliance items. Final clearance cannot proceed until resolved.")
	cols := columns([]string{"Activity ID", "Owner / Staff", "School ID", "School / Scope", "Blocked Reason(s)", "IA Status",
		"Next Action required", "Actions"}, "Actions")
	if total == 0 {
		return page(h, table(cols, nil, blockedEmpty, blockedParam, query)...), nil
	}
	p := tablepager.Paginate(total, pageSize, query, blockedParam)
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.responsible_staff_id, ''),
  COALESCE(a.school_id, ''), COALESCE(sc.name, ''), COALESCE(CASE WHEN sc.deleted_at IS NULL THEN sc.school_id END, ''), COALESCE(a.delivery_type, ''),
  EXISTS (SELECT 1 FROM evidence_record e WHERE e.activity_id = a.id AND NOT e.quarantined),
  EXISTS (SELECT 1 FROM activity_schedule_cost_line l WHERE l.activity_id = a.id),
  UPPER(COALESCE(a.salesforce_record_type_snapshot, '')), COALESCE(a.salesforce_activity_id, '')
FROM activity a LEFT JOIN school sc ON sc.id = a.school_id
WHERE `+blockedWhere+`
ORDER BY a.created_at DESC, a.id DESC LIMIT $4 OFFSET $5`, rules.NotInPlanStatuses, rules.IAVerifiedStatuses, rules.NoSalesforceRecordTypes, p.End-p.Start, p.Start)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the blocked work: %w", err)
	}
	type work struct {
		id, kind, status, owner, schoolID, name, filled, delivery, recordType, sfID string
		evidence, lines                                                             bool
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (work, error) {
		var w work
		return w, row.Scan(&w.id, &w.kind, &w.status, &w.owner, &w.schoolID, &w.name, &w.filled, &w.delivery, &w.evidence, &w.lines,
			&w.recordType, &w.sfID)
	})
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the blocked work: %w", err)
	}
	owners := make([]string, 0, len(list))
	for _, w := range list {
		owners = append(owners, w.owner)
	}
	names, err := s.staffNames(ctx, owners)
	if err != nil {
		return nil, err
	}
	out := make([]*screensv1.PageRow, 0, len(list))
	for _, w := range list {
		var reasons []string
		if !contains(rules.IAVerifiedStatuses, w.status) {
			reasons = append(reasons, "IA Verification Missing")
		}
		if w.delivery == "partner" && !w.evidence {
			reasons = append(reasons, "Evidence Missing")
		}
		if !contains(rules.NoSalesforceRecordTypes, w.recordType) && w.sfID == "" {
			reasons = append(reasons, "Activity SF ID Missing")
		}
		if !w.lines {
			reasons = append(reasons, "Budget Line Missing")
		}
		label := strings.Join(reasons, ", ")
		ia := "Pending IA"
		if strings.Contains(iaVerifiedIn, w.status) {
			ia = "Verified"
		}
		next := "Reconcile budget lines."
		switch {
		case strings.Contains(label, "Evidence Missing"):
			next = "Staff must upload field photos or forms."
		case strings.Contains(label, "Activity SF ID Missing"):
			next = "CCEO must update Salesforce reference ID."
		case strings.Contains(label, "IA Verification Missing"):
			next = "Waiting on IA auditor check."
		}
		owner, ok := names[w.owner]
		if !ok {
			owner = w.owner
			if owner == "" {
				owner = "Unassigned"
			}
		}
		code, where := "—", cell("Cluster-wide")
		if w.schoolID != "" {
			code, where = closedschools.SchoolCode(w.filled), school(d, w.schoolID, w.name)
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(joined("#"+short(w.id), typeLabel(w.kind))), cell(owner), cell(code), where, badge(label), cell(ia),
			cell(next), button("Inspect", detail(w.id)),
		}})
	}
	t := &screensv1.PageTable{Columns: cols, Rows: out}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(total, pageSize, query, blockedParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return page(h, blocks...), nil
}

// staffNames is verification_analytics._staff_names: a live profile's
// account name (its id when it has no account), else the account's own
// name for a legacy row that holds a user id. A name not on record reads
// "None", as the template prints it.
func (s *Service) staffNames(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT sp.id, u.id IS NOT NULL, u.name FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) AND sp.deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the owners' names: %w", err)
	}
	for rows.Next() {
		var id string
		var hasUser bool
		var name *string
		if err := rows.Scan(&id, &hasUser, &name); err != nil {
			rows.Close()
			return nil, err
		}
		out[id] = id
		if hasUser {
			out[id] = pyStr(name)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var rest []string
	for _, id := range ids {
		if _, ok := out[id]; !ok && id != "" {
			rest = append(rest, id)
		}
	}
	rows, err = s.db.Query(ctx, `SELECT id, name FROM "user" WHERE id = ANY($1)`, rest)
	if err != nil {
		return nil, fmt.Errorf("financedesks: reading the owners' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var name *string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = pyStr(name)
	}
	return out, rows.Err()
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
