package loans

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// Staff loan tracking: which applications a person follows, and how each is
// worded for them. A CCEO follows the schools assigned to their staff
// profile; a Programme Lead their own and, apart, their supervised CCEOs';
// the BTO, Country Director and RVP every application. The portfolio is
// read from the existing assignments each time, so a school that moves to
// another officer moves with it, while past follow-ups keep who wrote them.

// Staff roles of the existing system that follow their portfolio's loans.
const (
	roleCCEO        = "CCEO"
	roleProgramLead = "Program Lead"
)

// Portfolio scopes.
const (
	ScopeMine = "mine"
	ScopeTeam = "team"
	ScopeAll  = "all"
)

// portfolioLimit bounds one portfolio read.
const portfolioCaseLimit = 2000

// PortfolioIDs are the applications of schools assigned to the staff
// profiles, with the portfolio's size: its operating schools, and how many
// of them have no application.
func (s *Store) PortfolioIDs(ctx context.Context, staffProfiles []string) (ids []string, schools, without int, err error) {
	if len(staffProfiles) == 0 {
		return nil, 0, 0, nil
	}
	const portfolio = `
SELECT s.id FROM school s
WHERE s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
  AND s.id IN (SELECT a.school_id FROM staff_school_assignment a WHERE a.staff_id = ANY($1))`
	if err = s.db.QueryRow(ctx, `
SELECT count(*), count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM school_loans.application a WHERE a.school_id = p.id))
FROM (`+portfolio+`) p`, staffProfiles).Scan(&schools, &without); err != nil {
		return nil, 0, 0, fmt.Errorf("loans: counting a portfolio: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id::text FROM school_loans.application a WHERE a.school_id IN (`+portfolio+`)
ORDER BY a.submitted_at DESC LIMIT $2`, staffProfiles, portfolioCaseLimit)
	if err != nil {
		return nil, 0, 0, fmt.Errorf("loans: reading a portfolio's applications: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, 0, 0, err
		}
		ids = append(ids, id)
	}
	return ids, schools, without, rows.Err()
}

// Supervisees are the staff profiles a Programme Lead supervises.
func (s *Store) Supervisees(ctx context.Context, supervisorProfile string) ([]Option, error) {
	return options(ctx, s, `
SELECT sa.supervisee_id, COALESCE(u.name, sa.supervisee_id)
FROM staff_supervisor_assignment sa
JOIN staff_profile sp ON sp.id = sa.supervisee_id AND sp.deleted_at IS NULL
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sa.supervisor_id = $1 ORDER BY 2`, supervisorProfile)
}

// ResponsibleStaff names the officers each school is assigned to now.
func (s *Store) ResponsibleStaff(ctx context.Context, schoolIDs []string) (map[string]string, error) {
	out := map[string]string{}
	if len(schoolIDs) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT a.school_id, string_agg(DISTINCT COALESCE(u.name, ''), ', ')
FROM staff_school_assignment a
JOIN staff_profile sp ON sp.id = a.staff_id AND sp.deleted_at IS NULL
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE a.school_id = ANY($1) GROUP BY a.school_id`, schoolIDs)
	if err != nil {
		return nil, fmt.Errorf("loans: reading responsible staff: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var school, names string
		if err := rows.Scan(&school, &names); err != nil {
			return nil, err
		}
		out[school] = names
	}
	return out, rows.Err()
}

// Display statuses (brief, staff loan tracking §2): words for people, each
// derived from the authoritative records, never stored beside them.
const (
	ShowSubmitted        = "Application Submitted"
	ShowAwaitingLender   = "Awaiting Lending Partner"
	ShowAssigned         = "Assigned to Loan Officer"
	ShowContactPending   = "Contact Pending"
	ShowAssessment       = "Assessment In Progress"
	ShowRecommended      = "Recommendation Submitted"
	ShowAwaitingDecision = "Awaiting Credit Decision"
	ShowApproved         = "Approved"
	ShowDeclined         = "Declined"
	ShowAwaitingPayout   = "Awaiting Disbursement"
	ShowPartlyDisbursed  = "Partially Disbursed"
	ShowActive           = "Disbursed / Active Loan"
	ShowInstallmentDue   = "Installment Due"
	ShowOverdue          = "Repayment Overdue"
	ShowSettled          = "Fully Settled"
	ShowCollateral       = "Collateral Release Pending"
	ShowClosed           = "Closed"
)

// displayStatus words a case's present state for staff, with its tone.
func (c *caseData) displayStatus() (string, string) {
	r := c.record
	switch c.stage() {
	case StageClosed:
		return ShowClosed, "plain"
	case StageDeclined:
		return ShowDeclined, "alert"
	case StageSettledPending:
		return ShowCollateral, "caution"
	case StageActive:
		switch {
		case !c.disbursed():
			return ShowActive, "good" // recorded through referral tracking alone
		case c.position.Status == ledger.StatusSettled:
			return ShowSettled, "good"
		case c.position.Status == ledger.StatusOverdue:
			return ShowOverdue, "alert"
		case c.position.Status == ledger.StatusPaymentDue || c.position.Status == ledger.StatusPartiallyPaid:
			return ShowInstallmentDue, "caution"
		case c.loan != nil && c.loan.Approved > 0 && c.position.NetDisbursed < c.loan.Approved:
			return ShowPartlyDisbursed, "info"
		}
		return ShowActive, "good"
	case StageAwaitingDisbursement:
		return ShowAwaitingPayout, "info"
	case StageApproved:
		return ShowApproved, "good"
	case StageAwaitingCredit:
		return ShowAwaitingDecision, "info"
	case StageAwaitingAgreement:
		return ShowRecommended, "info"
	case StageAssessment:
		return ShowAssessment, "info"
	case StageContactPending:
		if len(r.Contacts) == 0 {
			return ShowAssigned, "info"
		}
		return ShowContactPending, "caution"
	}
	switch r.Referral.DeliveryStatus {
	case DeliverySent, DeliveryOpened:
		return ShowAwaitingLender, "caution"
	}
	return ShowSubmitted, "info"
}

// disbursementLabel is the money paid out, from the ledger only.
func (c *caseData) disbursementLabel() string {
	switch {
	case c.disbursed() && c.loan != nil && c.position.NetDisbursed < c.loan.Approved:
		return "Partially disbursed"
	case c.disbursed():
		return "Disbursed"
	case c.record.Referral.Status == StatusDisbursed:
		return "Disbursed (lender-reported, not in the ledger)"
	}
	return "Not disbursed"
}

// followUpDueSoon: an installment this close needs a word with the school.
const followUpDueSoonDays = 14

// staleLenderDays: an application the lender has not touched this long is
// followed up with the lender.
const staleLenderDays = 7

// followUp is what repayment follow-up the case calls for now.
func (c *caseData) followUp(nextFollowUp *time.Time) (label, tone string, due bool) {
	if nextFollowUp != nil && !nextFollowUp.After(c.today) {
		defer func() { label, tone, due = "Follow-up due "+day(*nextFollowUp), "caution", true }()
	}
	switch {
	case c.stage() == StageClosed || c.stage() == StageDeclined:
		return "—", "plain", false
	case c.disbursed() && c.position.Status == ledger.StatusSettled:
		return "Settled", "good", false
	case c.disbursed() && c.position.AmountOverdue > 0:
		return fmt.Sprintf("Overdue (%d days)", c.position.DaysPastDue), "alert", true
	case c.disbursed() && c.position.NextDue != nil && !c.position.NextDue.DueDate.After(c.today.AddDate(0, 0, followUpDueSoonDays)):
		return "Due soon", "caution", true
	case c.disbursed():
		return "On track", "good", false
	case c.record.Referral.Status == StatusDisbursed:
		return "No repayment record in the ledger", "plain", false
	case c.stage() == StageUnassigned && c.today.Sub(ledger.DayOf(c.record.Referral.SubmittedAt)) > staleLenderDays*24*time.Hour:
		return "Awaiting lender", "caution", true
	}
	return "Awaiting decision", "info", false
}

// counterOf places a case under the four portfolio counters.
func (c *caseData) counters(due bool) map[string]bool {
	stage := c.stage()
	processing := stage != StageClosed && stage != StageDeclined && !c.disbursed() && c.record.Referral.Status != StatusDisbursed
	disbursed := c.disbursed() || c.record.Referral.Status == StatusDisbursed
	return map[string]bool{"applied": true, "processing": processing, "disbursed": disbursed, "follow_up_due": due}
}

// Counter rules, said to people.
var counterRules = []struct{ key, label, rule string }{
	{"applied", "Applied", "Applications from your schools, and the schools that sent them."},
	{"processing", "Processing", "Applications still with the lender: not declined, closed or disbursed."},
	{"disbursed", "Disbursed", "Loans the lender has paid out, as recorded in the loan ledger."},
	{"follow_up_due", "Follow-up Due", "Overdue or soon-due installments, follow-ups whose date has come, and applications a lender has not picked up in 7 days."},
}

// stageDay formats a recorded day, or nothing.
func stageDay(at *time.Time) string {
	if at == nil || at.IsZero() {
		return ""
	}
	return day(at.In(kampala))
}

// ProgressStep is one stage of an application's progress, as recorded.
type ProgressStep struct {
	Key, Label, State, UpdatedOn, Responsible, NextAction, Note string
}

// progress lays out the stages from submission to collateral release.
// Only recorded facts mark a stage done: none is assumed or dated by guess.
func (c *caseData) progress() []ProgressStep {
	r := c.record
	lender := r.Referral.LenderName
	steps := []ProgressStep{{Key: "submitted", Label: "Application submitted", State: "done",
		UpdatedOn: day(r.Referral.SubmittedAt.In(kampala)), Responsible: "School"}}
	add := func(step ProgressStep) { steps = append(steps, step) }
	reached := func(done bool, at *time.Time) (string, string) {
		if done {
			return "done", stageDay(at)
		}
		return "not_reached", ""
	}

	// Received by the lender.
	received := r.Referral.LenderReceivedAt != nil || r.Referral.DeliveryStatus == DeliveryOpened
	state, on := reached(received, r.Referral.LenderReceivedAt)
	step := ProgressStep{Key: "received", Label: "Lender received", State: state, UpdatedOn: on, Responsible: lender}
	if !received {
		step.State, step.Note, step.NextAction = "waiting", "Awaiting lender update", lender+" to acknowledge the application."
	}
	add(step)

	// Officer assigned.
	var assignedAt *time.Time
	if r.Assignment != nil {
		assignedAt = &r.Assignment.AssignedAt
	}
	state, on = reached(r.Assignment != nil, assignedAt)
	add(ProgressStep{Key: "assigned", Label: "Officer assigned", State: state, UpdatedOn: on, Responsible: lender})

	// Assessment.
	a := r.Assessment
	switch {
	case a != nil && a.Status == "completed":
		add(ProgressStep{Key: "assessment", Label: "School assessment", State: "done", UpdatedOn: day(a.UpdatedAt.In(kampala)), Responsible: lender})
	case a != nil:
		add(ProgressStep{Key: "assessment", Label: "School assessment", State: "current", UpdatedOn: day(a.UpdatedAt.In(kampala)),
			Responsible: lender, Note: assessmentStatusLabels[a.Status]})
	default:
		add(ProgressStep{Key: "assessment", Label: "School assessment", State: "not_reached", Responsible: lender})
	}

	// Recommendation, then the school's agreement.
	rec := r.LatestRecommendation()
	state, on = reached(rec != nil && rec.SubmittedAt != nil, nil)
	if rec != nil {
		on = stageDay(rec.SubmittedAt)
	}
	add(ProgressStep{Key: "recommendation", Label: "Credit recommendation", State: state, UpdatedOn: on, Responsible: lender})

	// Decision.
	d := r.LatestDecision()
	switch {
	case d != nil && d.Decision != "returned":
		label := map[string]string{"approved": "Approved", "declined": "Declined"}[d.Decision]
		add(ProgressStep{Key: "decision", Label: "Decision", State: "done", UpdatedOn: day(d.DecidedAt.In(kampala)), Responsible: lender, Note: label})
	case r.Referral.Status == StatusApproved || r.Referral.Status == StatusDeclined:
		add(ProgressStep{Key: "decision", Label: "Decision", State: "done", UpdatedOn: stageDay(r.Referral.DecidedAt), Responsible: lender,
			Note: StatusLabel(r.Referral.Status) + " (recorded through referral tracking)"})
	default:
		add(ProgressStep{Key: "decision", Label: "Decision", State: "not_reached", Responsible: lender})
	}

	// Disbursement, from the ledger.
	switch {
	case c.disbursed():
		first := c.book.Disbursements[0].ValueDate
		note := ""
		if c.loan != nil && c.position.NetDisbursed < c.loan.Approved {
			note = "Partially disbursed"
		}
		add(ProgressStep{Key: "disbursement", Label: "Disbursement", State: "done", UpdatedOn: day(first), Responsible: lender, Note: note})
	case r.Referral.Status == StatusDisbursed:
		add(ProgressStep{Key: "disbursement", Label: "Disbursement", State: "waiting", UpdatedOn: stageDay(r.Referral.DisbursementDate),
			Responsible: lender, Note: "Reported by the lender; not yet in the loan ledger"})
	default:
		add(ProgressStep{Key: "disbursement", Label: "Disbursement", State: "not_reached", Responsible: lender})
	}

	// Repayment and settlement.
	switch {
	case c.disbursed() && c.position.Status == ledger.StatusSettled:
		add(ProgressStep{Key: "repayment", Label: "Repayment", State: "done", UpdatedOn: stageDay(c.position.LastPaymentDate), Responsible: "School"})
		add(ProgressStep{Key: "settlement", Label: "Settlement", State: "done", UpdatedOn: stageDay(c.position.LastPaymentDate), Responsible: lender,
			Note: "Fully settled on the verified ledger"})
	case c.disbursed():
		step := ProgressStep{Key: "repayment", Label: "Repayment", State: "current", UpdatedOn: stageDay(c.position.LastPaymentDate), Responsible: "School"}
		if next := c.position.NextDue; next != nil {
			step.NextAction = "Next installment due " + day(next.DueDate)
		}
		if c.position.AmountOverdue > 0 {
			step.Note = fmt.Sprintf("Overdue %d days", c.position.DaysPastDue)
		}
		add(step)
		add(ProgressStep{Key: "settlement", Label: "Settlement", State: "not_reached", Responsible: lender})
	default:
		add(ProgressStep{Key: "repayment", Label: "Repayment", State: "not_reached", Responsible: "School"})
		add(ProgressStep{Key: "settlement", Label: "Settlement", State: "not_reached", Responsible: lender})
	}

	// Collateral release.
	release := ProgressStep{Key: "collateral", Label: "Collateral release", State: "not_reached", Responsible: lender}
	switch {
	case len(r.Collateral) == 0:
		release.Note = "No security recorded"
	case !c.collateralHeld() && c.settled():
		release.State, release.Note = "done", "All security returned"
		for _, item := range r.Collateral {
			if item.ReleasedOn != nil {
				release.UpdatedOn = day(*item.ReleasedOn)
			}
		}
	case c.settled():
		release.State, release.NextAction = "current", lender+" to release the security"
	}
	add(release)

	// A step with no record that lies before a later recorded one was taken
	// outside this system (a loan tracked before the lender workflow): say so,
	// and never make it the current step.
	last := -1
	for index, step := range steps {
		if step.State != "not_reached" {
			last = index
		}
	}
	for index := 0; index < last; index++ {
		if steps[index].State != "done" {
			steps[index].State, steps[index].NextAction = "not_reached", ""
			steps[index].Note = "Not recorded in this system"
		}
	}

	// The first stage not done is the current one, unless already marked.
	for index := max(last, 0); index < len(steps); index++ {
		if steps[index].State == "done" {
			continue
		}
		if steps[index].State == "not_reached" {
			steps[index].State = "current"
		}
		break
	}
	return steps
}

// searchable is what a portfolio search matches.
func (c *caseData) searchable() string {
	r := c.record.Referral
	return strings.ToLower(strings.Join([]string{r.SchoolName, r.Reference, r.EdifySchoolID, r.District, r.LenderName}, " "))
}
