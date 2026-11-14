package btportfolio

import (
	"context"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Filters is frontend_views._filters: every BT filter the page's query
// carries, trimmed.
type Filters map[string]string

// FilterKeys are the keys _filters reads.
var FilterKeys = []string{"fy", "q", "region", "district", "mfi", "status", "period_type", "quarter", "month", "custom_from",
	"custom_to", "school", "purpose", "edtech", "repayment_health", "salesforce_status", "ia_status", "impact_status",
	"case_status", "partner", "support_status", "page"}

// ReadFilters is _filters over query.
func ReadFilters(query url.Values, keys []string) Filters {
	f := Filters{}
	for _, k := range keys {
		f[k] = strings.TrimSpace(query.Get(k))
	}
	return f
}

// Args builds numbered arguments.
type Args []any

// Add appends v and names it.
func (a *Args) Add(v any) string {
	*a = append(*a, v)
	return "$" + strconv.Itoa(len(*a))
}

// memberships is _mfi_ids_for: the lending partners the reader belongs to
// (as an administrator only, with adminOnly).
func memberships(ctx context.Context, db schooldirectory.Querier, userID string, adminOnly bool) ([]string, error) {
	sql := `SELECT mfi_id FROM bt_mfi_membership WHERE user_id = $1 AND active`
	if adminOnly {
		sql += ` AND role = 'admin'`
	}
	rows, err := db.Query(ctx, sql, userID)
	if err != nil {
		return nil, fmt.Errorf("btportfolio: reading the reader's lending partners: %w", err)
	}
	out, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("btportfolio: reading the reader's lending partners: %w", err)
	}
	return out, nil
}

// MfiIDs is _mfi_ids_for: the lending partners the reader belongs to.
func MfiIDs(ctx context.Context, db schooldirectory.Querier, userID string) ([]string, error) {
	ids, err := memberships(ctx, db, userID, false)
	if ids == nil {
		ids = []string{}
	}
	return ids, err
}

// LoansWhere is scoped_loans as a condition on bt_mfi_loan l with its school
// s: a partner administrator's partners' loans, a loan officer's own, the
// programme's schools for Uganda-wide readers and CCEOs, nothing else.
func LoansWhere(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, a *Args) (string, error) {
	base := "l.deleted_at IS NULL AND "
	switch {
	case p.ActiveRole == "MfiPartnerAdmin":
		ids, err := memberships(ctx, db, p.UserID, true)
		if err != nil {
			return "", err
		}
		return base + "l.mfi_id = ANY(" + a.Add(ids) + ")", nil
	case p.ActiveRole == "MfiLoanOfficer":
		ids, err := memberships(ctx, db, p.UserID, false)
		if err != nil {
			return "", err
		}
		u := a.Add(p.UserID)
		return base + "l.mfi_id = ANY(" + a.Add(ids) + ") AND (l.registered_by = " + u + ` OR l.assigned_officer_reference IN (
  SELECT officer_reference FROM bt_mfi_membership WHERE user_id = ` + u + ` AND role = 'loan_officer' AND active AND officer_reference <> ''))`, nil
	case UgandaWide(p.ActiveRole) || p.ActiveRole == "CCEO":
		scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
		if err != nil {
			return "", fmt.Errorf("btportfolio: resolving the reader's scope: %w", err)
		}
		args := []any(*a)
		reach := schooldirectory.AnalyticsReach(scope, &args)
		*a = Args(args)
		return base + "l.school_id IN (SELECT s.id FROM school s WHERE " + reach + ")", nil
	}
	return "FALSE", nil
}

// CasesWhere is scoped_cases as a condition on bt_case c.
func CasesWhere(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, a *Args) (string, error) {
	switch {
	case UgandaWide(p.ActiveRole):
		return "c.deleted_at IS NULL", nil
	case SummaryOnly(p.ActiveRole) || MfiUser(p.ActiveRole):
		return "FALSE", nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", fmt.Errorf("btportfolio: resolving the reader's scope: %w", err)
	}
	ids := scope.SchoolIDs
	if ids == nil {
		ids = []string{}
	}
	return "c.deleted_at IS NULL AND c.school_id = ANY(" + a.Add(ids) + ")", nil
}

// Partner is one lending partner.
type Partner struct{ ID, Name string }

// Partners is scoped_mfis: the active lending partners by name, a partner
// user's own only.
func Partners(ctx context.Context, db schooldirectory.Querier, p auth.Principal) ([]Partner, error) {
	sql, args := `SELECT id, name FROM bt_mfi_organization WHERE active AND deleted_at IS NULL`, []any{}
	if MfiUser(p.ActiveRole) {
		ids, err := memberships(ctx, db, p.UserID, false)
		if err != nil {
			return nil, err
		}
		sql += ` AND id = ANY($1)`
		args = append(args, ids)
	}
	rows, err := db.Query(ctx, sql+` ORDER BY name`, args...)
	if err != nil {
		return nil, fmt.Errorf("btportfolio: reading the lending partners: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (Partner, error) {
		var x Partner
		return x, r.Scan(&x.ID, &x.Name)
	})
}

var reportMonth = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}$`)

// FilterLoans is filter_loans: the filters' narrowing of the loans l (school
// s, purpose p joined by the caller).
func FilterLoans(f Filters, a *Args) string {
	out := ""
	eq := func(col, key string) {
		if f[key] != "" {
			out += " AND " + col + " = " + a.Add(f[key])
		}
	}
	eq("l.status", "status")
	eq("l.mfi_id", "mfi")
	eq("s.region_id", "region")
	eq("s.district_id", "district")
	eq("l.school_id", "school")
	eq("l.purpose_id", "purpose")
	switch f["edtech"] {
	case "yes":
		out += " AND COALESCE(p.is_edtech, FALSE)"
	case "no":
		out += " AND p.is_edtech IS FALSE"
	}
	eq("l.salesforce_status", "salesforce_status")
	if m := f["report_month"]; reportMonth.MatchString(m) {
		if start, err := time.Parse(time.DateOnly, m+"-01"); err == nil {
			out += " AND l.disbursement_date >= " + a.Add(start.Format(time.DateOnly)) + "::date AND l.disbursement_date < " +
				a.Add(start.AddDate(0, 1, 0).Format(time.DateOnly)) + "::date"
		}
	}
	eq("l.ia_validation_status", "ia_status")
	eq("l.impact_status", "impact_status")
	if f["repayment_health"] != "" {
		out += ` AND (SELECT r.status FROM bt_repayment_snapshot r WHERE r.loan_id = l.id ORDER BY r.as_of_date DESC, r.created_at DESC LIMIT 1) = ` + a.Add(f["repayment_health"])
	}
	if q := f["q"]; q != "" {
		like := a.Add("%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(q) + "%")
		out += " AND (UPPER(s.name::text) LIKE UPPER(" + like + ") OR UPPER(s.school_id::text) LIKE UPPER(" + like +
			") OR UPPER(l.external_loan_reference::text) LIKE UPPER(" + like + ") OR UPPER(l.salesforce_loan_id::text) LIKE UPPER(" + like + "))"
	}
	return out
}

// Period is _selected_period_bounds: [Start, End) in UTC for the FY, a
// quarter, a month of the FY, or a custom local-day range.
func Period(fy string, f Filters) (time.Time, time.Time) {
	n, _ := strconv.Atoi(fy)
	utc := func(y int, m time.Month) time.Time { return time.Date(y, m, 1, 0, 0, 0, 0, time.UTC) }
	switch f["period_type"] {
	case "quarter":
		starts := map[string]struct {
			year  int
			month time.Month
		}{"Q1": {n - 1, 10}, "Q2": {n, 1}, "Q3": {n, 4}, "Q4": {n, 7}}
		if s, ok := starts[f["quarter"]]; ok {
			start := utc(s.year, s.month)
			return start, start.AddDate(0, 3, 0)
		}
	case "month":
		if m, err := strconv.Atoi(f["month"]); err == nil && m >= 1 && m <= 12 {
			start := utc(n-1, 10).AddDate(0, m-1, 0)
			return start, start.AddDate(0, 1, 0)
		}
	case "custom":
		from, err1 := time.Parse(time.DateOnly, f["custom_from"])
		to, err2 := time.Parse(time.DateOnly, f["custom_to"])
		if err1 == nil && err2 == nil && !from.After(to) {
			z := zone
			return time.Date(from.Year(), from.Month(), from.Day(), 0, 0, 0, 0, z).UTC(),
				time.Date(to.Year(), to.Month(), to.Day()+1, 0, 0, 0, 0, z).UTC()
		}
	}
	return utc(n-1, 10), utc(n, 10)
}

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("btportfolio: loading the zone: %v", err))
	}
	return z
}()

// Zone is the project's timezone.
func Zone() *time.Location { return zone }
