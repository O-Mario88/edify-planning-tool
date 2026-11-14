package leaveapprovals

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// seniority is _APPROVER_SENIORITY: the ladder a leave type's approval floor
// is tested on.
var seniority = map[string]int{"cceo": 1, "pl": 2, "cd": 3, "rvp": 4}

// normalizeRole is is_authorized_approver's normalize_role.
func normalizeRole(r string) string {
	r = strings.ToLower(strings.NewReplacer(" ", "", "_", "").Replace(r))
	switch r {
	case "programlead":
		return "pl"
	case "countrydirector":
		return "cd"
	case "regionalvicepresident":
		return "rvp"
	case "humanresources":
		return "hr"
	case "impactassessment":
		return "ia"
	case "programaccountant", "acct":
		return "accountant"
	case "projectcoordinator":
		return "pc"
	}
	return r
}

// leave is one leave request as the page reads it.
type leave struct {
	id, staffID, staffUser, staffName, staffEmail, staffRole string
	staffCountry                                             *string
	kind, start, end, status, coverageStatus                 string
	days                                                     int
	charged                                                  *int
	reason                                                   string
	hasAttachment                                            bool
	coverID, coverName, coverRole                            string
	created                                                  time.Time
}

// reviewer is what deciding leave asks of the reader, read once (the
// existing page's approval_lookups).
type reviewer struct {
	userID, role, profile          string
	country                        *string
	supervised                     map[string]bool
	policyFloor                    map[string]int
	rvpRegionScoped, hasProfileRow bool
}

func loadReviewer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (reviewer, error) {
	r := reviewer{userID: p.UserID, role: normalizeRole(p.ActiveRole), supervised: map[string]bool{}, policyFloor: map[string]int{}}
	err := db.QueryRow(ctx, `SELECT id, country FROM staff_profile WHERE user_id = $1`, p.UserID).Scan(&r.profile, &r.country)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
	case err != nil:
		return r, fmt.Errorf("leaveapprovals: reading the reviewer's People record: %w", err)
	default:
		r.hasProfileRow = true
	}
	if r.hasProfileRow {
		rows, err := db.Query(ctx, `SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1 OR supervisor_id IN (
  SELECT original_staff_id FROM temporary_coverage_assignment WHERE covering_staff_id = $1 AND start_datetime <= $2 AND end_datetime >= $2 AND status = 'active')`, r.profile, now)
		if err != nil {
			return r, fmt.Errorf("leaveapprovals: reading the reviewer's team: %w", err)
		}
		ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			return r, fmt.Errorf("leaveapprovals: reading the reviewer's team: %w", err)
		}
		for _, id := range ids {
			r.supervised[id] = true
		}
	}
	rows, err := db.Query(ctx, `SELECT DISTINCT ON (leave_type) leave_type, COALESCE(approver_role, '') FROM leave_type_policy ORDER BY leave_type, id`)
	if err != nil {
		return r, fmt.Errorf("leaveapprovals: reading the leave policies: %w", err)
	}
	for rows.Next() {
		var kind, role string
		if err := rows.Scan(&kind, &role); err != nil {
			rows.Close()
			return r, fmt.Errorf("leaveapprovals: reading the leave policies: %w", err)
		}
		r.policyFloor[kind] = seniority[normalizeRole(role)]
	}
	rows.Close()
	if p.ActiveRole == "RegionalVicePresident" {
		scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
		if err != nil {
			return r, fmt.Errorf("leaveapprovals: resolving the reviewer's scope: %w", err)
		}
		r.rvpRegionScoped = scope.SummaryOnly && len(scope.RegionIDs) > 0
	}
	return r, nil
}

// sameCountry is Python's ==, where two missing countries match.
func sameCountry(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

// rvpCovers is _rvp_covers.
func (r reviewer) rvpCovers(l leave) bool {
	if !r.rvpRegionScoped {
		return true
	}
	if l.staffCountry != nil && *l.staffCountry != "" && r.country != nil && *r.country != "" {
		return *l.staffCountry == *r.country
	}
	return true
}

// authorized is LeaveApprovalService.is_authorized_approver (the acting
// arm is the caller's: an acting reader's page is passed on).
func (r reviewer) authorized(l leave) bool {
	if l.staffUser == r.userID || r.role == "admin" {
		return false
	}
	if l.status != "hr_review" {
		if required := r.policyFloor[l.kind]; required > 0 && seniority[r.role] < required {
			return false
		}
	}
	if !r.hasProfileRow {
		return false
	}
	if l.status == "hr_review" && r.role == "hr" {
		return true
	}
	direct := r.supervised[l.staffID]
	switch normalizeRole(l.staffRole) {
	case "cceo":
		return r.role == "pl" && direct
	case "pl":
		return r.role == "cd" && (direct || sameCountry(r.country, l.staffCountry))
	case "pc", "ia", "accountant", "hr":
		switch {
		case direct:
			return slices.Contains([]string{"cd", "rvp"}, r.role)
		case r.role == "cd" && sameCountry(r.country, l.staffCountry):
			return true
		case r.role == "rvp":
			return r.rvpCovers(l)
		}
		return false
	case "cd":
		return r.role == "rvp" && r.rvpCovers(l)
	case "rvp":
		return r.role == "executive"
	}
	return direct
}
