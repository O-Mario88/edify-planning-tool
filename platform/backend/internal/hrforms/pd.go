package hrforms

import (
	"context"
	"errors"
	"fmt"
	"math"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationjobs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
)

// PDPath is the page the PD form's save returns to.
const PDPath = "/my-professional-development"

// PDCurrencies are SDF_CURRENCIES.
var PDCurrencies = []string{"USD", "UGX", "KES", "RWF", "TZS", "ZMW", "GHS", "NGN"}

// pdCommitted are COMMITTED_STATUSES.
var pdCommitted = []string{"submitted_to_supervisor", "submitted_to_hr", "pending_exception", "submitted_to_cd",
	"approved_pending_funding", "disbursed", "enrollment_pending", "enrollment_confirmed", "in_progress", "ended",
	"marked_complete", "certificate_uploaded", "bamboohr_confirmed", "accountability_submitted", "awaiting_hr_signoff"}

// operationalFY is get_operational_fy: the year from 1 October, by the UTC day.
func operationalFY(t time.Time) string {
	u := t.UTC()
	if u.Month() >= time.October {
		return strconv.Itoa(u.Year() + 1)
	}
	return strconv.Itoa(u.Year())
}

// PDYears is _fy_choices: the year before the operational one, it and the
// next; and the operational year.
func PDYears(now time.Time) ([]string, string) {
	fy, _ := strconv.Atoi(operationalFY(now))
	return []string{strconv.Itoa(fy - 1), strconv.Itoa(fy), strconv.Itoa(fy + 1)}, strconv.Itoa(fy)
}

// whole is the `currency` filter: thousands separated, no decimals, half to
// even as Python's format rounds.
func whole(v float64) string {
	n := int64(math.RoundToEven(v))
	neg := n < 0
	if neg {
		n = -n
	}
	s := strconv.FormatInt(n, 10)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if neg {
		s = "-" + s
	}
	return s
}

// PDBalanceLine is the form's balance sentence (StaffPDService.balances for
// the operational year). The existing read makes the year's allocation when
// there is none; Go hands that reader on (ErrHandOn) rather than write on a
// read, as the page itself makes it first.
func (f Forms) PDBalanceLine(ctx context.Context, p auth.Principal) (string, error) {
	me, err := ownProfile(ctx, f.DB, p)
	if err != nil {
		return "", err
	}
	if me == "" {
		return "", ErrHandOn
	}
	_, fy := PDYears(f.now())
	var allocation int64
	var currency string
	err = f.DB.QueryRow(ctx, `SELECT annual_allocation, currency FROM pd_allocation WHERE staff_id = $1 AND fy = $2`, me, fy).
		Scan(&allocation, &currency)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrHandOn
	}
	if err != nil {
		return "", fmt.Errorf("hrforms: reading the PD allocation: %w", err)
	}
	var committed, accounted int64
	if err := f.DB.QueryRow(ctx, `SELECT COALESCE(SUM(requested_amount_cents) FILTER (WHERE status = ANY($3) AND NOT COALESCE(accounted_amount, 0) <> 0), 0),
  COALESCE(SUM(COALESCE(accounted_amount, 0)), 0) FROM pd_request WHERE staff_id = $1 AND fy = $2`, me, fy, pdCommitted).
		Scan(&committed, &accounted); err != nil {
		return "", fmt.Errorf("hrforms: reading the PD requests: %w", err)
	}
	remaining := max(allocation-committed-accounted, 0)
	return "Your Staff Development Fund: " + currency + " " + whole(float64(remaining)/100) + " remaining of " + currency + " " +
		whole(float64(allocation)/100) + " (FY " + fy + "). A request above it goes to HR as an exception.", nil
}

// pdCents is pd_request_view's _cents: commas dropped, anything not a
// finite, non-negative amount reads as nothing, else whole cents (half to
// even).
func pdCents(raw string) int64 {
	raw = strings.TrimSpace(strings.ReplaceAll(raw, ",", ""))
	if raw == "" {
		return 0
	}
	d, err := pydecimal.Parse(raw)
	if err != nil || d.Sign() < 0 {
		return 0
	}
	n, err := strconv.ParseInt(d.Mul(pydecimal.Int(100)).Quantize(0).String(), 10, 64)
	if err != nil {
		return 0
	}
	return n
}

// SavePDDraft is pd_request_view's POST for a new request saved as a draft:
// the reader's People record and its header (name, position, country,
// department, and the reviewer supervisor_for names); the form's details;
// the budget in cents (an amount requested in another currency kept beside
// the USD cost); filed under its dates, which it must have. Submitting,
// attachments and editing a saved request are the existing application's.
func (f Forms) SavePDDraft(ctx context.Context, p auth.Principal, values map[string]string) (string, error) {
	if strings.TrimSpace(values["id"]) != "" || values["intent"] == "submit" {
		return "", ErrHandOn
	}
	start, end := strings.TrimSpace(values["start_date"]), strings.TrimSpace(values["end_date"])
	if start == "" || end == "" {
		return "", refuse("Give the start and end dates of the activity to save the form.")
	}
	startDay, err1 := time.Parse("2006-01-02", start)
	endDay, err2 := time.Parse("2006-01-02", end)
	if err1 != nil || err2 != nil {
		// The model reads the dates as it saves; a date it cannot read fails
		// there. Left to the existing application.
		return "", ErrHandOn
	}
	err := f.write(ctx, func(tx pgx.Tx) error {
		var sp, title, department, country *string
		var name string
		err := tx.QueryRow(ctx, `SELECT sp.id, sp.title, sp.department, sp.country, u.name FROM "user" u
LEFT JOIN staff_profile sp ON sp.user_id = u.id WHERE u.id = $1 ORDER BY sp.deleted_at NULLS FIRST LIMIT 1`, p.UserID).
			Scan(&sp, &title, &department, &country, &name)
		if err != nil || sp == nil || country == nil {
			if err != nil && !errors.Is(err, pgx.ErrNoRows) {
				return fmt.Errorf("hrforms: reading the reader's People record: %w", err)
			}
			return ErrHandOn
		}
		supervisorProfile, supervisorUser, err := notificationjobs.PDSupervisorOf(ctx, tx, *sp)
		if err != nil {
			return err
		}
		var supervisorName any
		if supervisorUser != "" {
			var n string
			if err := tx.QueryRow(ctx, `SELECT name FROM "user" WHERE id = $1`, supervisorUser).Scan(&n); err != nil {
				return fmt.Errorf("hrforms: reading the supervisor: %w", err)
			}
			supervisorName = n
		}
		years, fy := PDYears(f.now())
		if chosen := strings.TrimSpace(values["fy"]); slices.Contains(years, chosen) {
			fy = chosen
		} else if raw := values["fy"]; raw != "" {
			fy = raw
		}
		cost, requested := pdCents(values["approximate_cost"]), pdCents(values["requested_amount"])
		currency := strings.TrimSpace(values["requested_currency"])
		if !slices.Contains(PDCurrencies, currency) {
			currency = "USD"
		}
		requestedUSD := requested
		var localCurrency, localAmount any
		if currency != "USD" {
			requestedUSD, localCurrency, localAmount = cost, currency, requested
		}
		purpose := strings.TrimSpace(values["purpose"])
		category := purpose
		if r := []rune(category); len(r) > 64 {
			category = string(r[:64])
		}
		funding := "self_funded"
		if requestedUSD != 0 {
			funding = "fully_funded"
		}
		now, id := f.now(), cuid.New()
		_, err = tx.Exec(ctx, `INSERT INTO pd_request (id, created_at, updated_at, fy, staff_id, staff_name, position, country, department,
  supervisor_staff_id, supervisor_name, course_name, course_category, course_type, institution, start_date, end_date,
  certification_expected, relevance_to_role, course_fee_cents, other_costs_cents, total_cost_cents, employee_contribution_cents,
  requested_amount_cents, funding_type, currency, is_exception, status, hr_is_independent_reviewer, enrollment_confirmed,
  bamboohr_uploaded, created_by, duration, purpose, requested_local_amount_cents, requested_local_currency)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'online', '', $13, $14, TRUE, $15, $16, 0, $16, 0, $17, $18, 'USD',
  FALSE, 'draft', FALSE, FALSE, FALSE, $19, $20, $21, $22, $23)`,
			id, now, fy, *sp, name, title, *country, department, orNull(supervisorProfile), supervisorName,
			strings.TrimSpace(values["course_name"]), category, startDay, endDay, strings.TrimSpace(values["relevance_to_role"]),
			cost, requestedUSD, funding, nullable(p.UserID), strings.TrimSpace(values["duration"]), purpose, localAmount, localCurrency)
		if err != nil {
			return fmt.Errorf("hrforms: saving the PD draft: %w", err)
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	return "Draft saved.", nil
}
