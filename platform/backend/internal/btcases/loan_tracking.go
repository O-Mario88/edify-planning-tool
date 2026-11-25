package btcases

// The loan_tracking_notifications job (apps.business_transformation.
// loan_tracking.run_loan_tracking_notifications): each open loan application
// due for follow-up and each live loan whose next repayment falls within a
// week (or has passed) reminds the school's portfolio owner and the
// country's Country Director, Impact Assessment and Business Transformation
// officers, once per stage; and each Regional Vice President gets the
// previous month's loan report once. Every delivery is claimed in the
// permanent delivery log first, so a rerun sends nothing twice. Inside the
// caller's transaction.

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// applicationRecipientRoles are APPLICATION_RECIPIENT_ROLES.
var applicationRecipientRoles = []string{"CountryDirector", "ImpactAssessment", "BusinessTransformationOfficer"}

// openApplicationStatuses are OPEN_LOAN_APPLICATION_STATUSES, with their labels.
var openApplicationStatuses = map[string]string{
	"submitted": "Submitted", "under_review": "Under review", "referred": "Referred to lender",
	"processing": "Processing", "approved": "Approved",
}

var liveLoanStatuses = []string{"disbursed", "active", "defaulted"}

// recipient is one person told, with the role their link opens for.
type recipient struct{ id, activeRole string }

// LoanTracking is run_loan_tracking_notifications for today in Kampala; it
// says how many notices it sent.
func LoanTracking(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, n Notices) (int, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	sent := 0
	for _, step := range []func(context.Context, pgx.Tx, time.Time, time.Time, Notices) (int, error){
		applicationFollowUps, repaymentFollowUps, monthlyReport,
	} {
		k, err := step(ctx, tx, today, now, n)
		if err != nil {
			return sent, err
		}
		sent += k
	}
	return sent, nil
}

// claim is _claim_delivery: true the first time a delivery is recorded.
func claim(ctx context.Context, tx pgx.Tx, kind, subject, period, to string, now time.Time) (bool, error) {
	tag, err := tx.Exec(ctx, `INSERT INTO bt_loan_tracking_delivery_log (id, created_at, updated_at, delivery_kind, subject_id,
  period_key, recipient_id)
VALUES ($1, $2, $2, $3, $4, $5, $6) ON CONFLICT (delivery_kind, subject_id, period_key, recipient_id) DO NOTHING`,
		cuid.New(), now, kind, subject, period, to)
	if err != nil {
		return false, fmt.Errorf("btcases: claiming a loan tracking delivery: %w", err)
	}
	return tag.RowsAffected() > 0, nil
}

// loanRoute is NotificationLinkResolver.resolve for the loan tracking events.
func loanRoute(event, contextID, activeRole string) (string, string) {
	if strings.EqualFold(activeRole, "Program Lead") {
		return "/schools", "Open School Support"
	}
	if event == "bt.loan_report.monthly" {
		return "/loans?report_month=" + contextID, "Open Monthly Loan Report"
	}
	return "/loans", "Open Loan Tracking"
}

func (n Notices) tell(ctx context.Context, tx pgx.Tx, now time.Time, to recipient, notice activities.Notice, contextID string) error {
	route, label := loanRoute(notice.Event, contextID, to.activeRole)
	_, err := activities.NotifyInTx(ctx, tx, n.Push, n.Logger, now, contextID, notice,
		[]activities.NoticeTo{{UserID: to.id, Route: route, Label: label}})
	return err
}

// applicationRecipients is application_recipients: the portfolio owner,
// then the country's role holders, each once in first-seen order.
func applicationRecipients(ctx context.Context, tx pgx.Tx, schoolID string) ([]recipient, error) {
	var owner *string
	var country string
	if err := tx.QueryRow(ctx, `SELECT s.account_owner_id, COALESCE(NULLIF(r.country, ''), 'Uganda') FROM school s
LEFT JOIN region r ON r.id = s.region_id WHERE s.id = $1`, schoolID).Scan(&owner, &country); err != nil {
		return nil, fmt.Errorf("btcases: reading the loan's school: %w", err)
	}
	var out []recipient
	seen := map[string]bool{}
	add := func(r recipient) {
		if !seen[r.id] {
			seen[r.id] = true
			out = append(out, r)
		}
	}
	if owner != nil && *owner != "" {
		r, ok, err := portfolioOwner(ctx, tx, *owner)
		if err != nil {
			return nil, err
		}
		if ok {
			add(r)
		}
	}
	for _, role := range applicationRecipientRoles {
		rows, err := tx.Query(ctx, `SELECT u.id, COALESCE(u.active_role, '') FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE $1 = ANY(u.roles) AND u.is_active AND u.deleted_at IS NULL AND sp.country = $2 ORDER BY u.created_at DESC`, role, country)
		if err != nil {
			return nil, fmt.Errorf("btcases: reading the country's %s: %w", role, err)
		}
		for rows.Next() {
			var r recipient
			if err := rows.Scan(&r.id, &r.activeRole); err != nil {
				rows.Close()
				return nil, err
			}
			add(r)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// portfolioOwner is _portfolio_owner: the owner's People record's active
// account, or a CCEO account the legacy record names directly.
func portfolioOwner(ctx context.Context, tx pgx.Tx, ownerID string) (recipient, bool, error) {
	var r recipient
	err := tx.QueryRow(ctx, `SELECT u.id, COALESCE(u.active_role, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = $1 AND sp.deleted_at IS NULL AND u.is_active AND u.deleted_at IS NULL`, ownerID).Scan(&r.id, &r.activeRole)
	if err == nil {
		return r, true, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return r, false, fmt.Errorf("btcases: reading the portfolio owner: %w", err)
	}
	err = tx.QueryRow(ctx, `SELECT id, COALESCE(active_role, '') FROM "user" WHERE id = $1 AND 'CCEO' = ANY(roles) AND is_active
  AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1`, ownerID).Scan(&r.id, &r.activeRole)
	if errors.Is(err, pgx.ErrNoRows) {
		return r, false, nil
	}
	if err != nil {
		return r, false, fmt.Errorf("btcases: reading the portfolio owner's account: %w", err)
	}
	return r, true, nil
}

// applicationFollowUps is send_application_follow_up_reminders.
func applicationFollowUps(ctx context.Context, tx pgx.Tx, today, now time.Time, n Notices) (int, error) {
	statuses := make([]string, 0, len(openApplicationStatuses))
	for s := range openApplicationStatuses {
		statuses = append(statuses, s)
	}
	rows, err := tx.Query(ctx, `SELECT a.id, a.status, a.next_follow_up_on, a.school_id, s.name FROM bt_loan_application a
JOIN school s ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND a.status = ANY($1) AND a.next_follow_up_on <= $2
ORDER BY a.created_at DESC`, statuses, today.Format(time.DateOnly))
	if err != nil {
		return 0, fmt.Errorf("btcases: reading the applications due for follow-up: %w", err)
	}
	type due struct {
		id, status, schoolID, school string
		on                           time.Time
	}
	var list []due
	for rows.Next() {
		var d due
		if err := rows.Scan(&d.id, &d.status, &d.on, &d.schoolID, &d.school); err != nil {
			rows.Close()
			return 0, err
		}
		list = append(list, d)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	sent := 0
	for _, d := range list {
		days := int(today.Sub(dayOnly(d.on)).Hours() / 24)
		period := fmt.Sprintf("%s:w%d", dayOnly(d.on).Format(time.DateOnly), days/7)
		people, err := applicationRecipients(ctx, tx, d.schoolID)
		if err != nil {
			return sent, err
		}
		for _, to := range people {
			first, err := claim(ctx, tx, "application_follow_up", d.id, period, to.id, now)
			if err != nil {
				return sent, err
			}
			if !first {
				continue
			}
			if err := n.tell(ctx, tx, now, to, activities.Notice{
				Title: "Loan application follow-up · " + d.school,
				Body: fmt.Sprintf("The %s application is due for follow-up (%d day(s) overdue).",
					strings.ToLower(openApplicationStatuses[d.status]), days),
				Event: "bt.loan_application.follow_up", Category: "business_transformation",
				ContextType: "loan_application", Priority: "high",
			}, d.id); err != nil {
				return sent, err
			}
			sent++
		}
	}
	return sent, nil
}

func dayOnly(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}
