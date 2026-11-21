package loans

import (
	"context"
	"log/slog"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// Lending is the lender portal and Edify's servicing oversight: the case
// workflow from assignment to closure. Money postings go to the existing
// ledger through ledgerClient as the person acting; positions and
// statements are computed from that ledger's postings.
type Lending struct {
	store  *Store
	ledger Ledger
	keys   Keys
	cfg    config.Loans
	mailer Mailer
	sms    SMSProvider
	logger *slog.Logger
	now    func() time.Time
	ready  func(context.Context) error
}

// NewLending returns the lender portal.
func NewLending(store *Store, ledgerClient Ledger, keys Keys, cfg config.Loans, mailer Mailer, sms SMSProvider,
	ready func(context.Context) error, logger *slog.Logger, now func() time.Time) *Lending {
	if now == nil {
		now = time.Now
	}
	return &Lending{store: store, ledger: ledgerClient, keys: keys, cfg: cfg, mailer: mailer, sms: sms, ready: ready,
		logger: logger, now: now}
}

// dueWindowDays: an installment due this soon is "due", not "upcoming".
const dueWindowDays = 14

// viewer is who is looking at a case: a lender's staff member, or Edify.
type viewer struct {
	principal auth.Principal
	lender    *LenderIdentity
	edify     *access
}

func (v viewer) isLender() bool { return v.lender != nil }

func (v viewer) has(role string) bool { return v.lender != nil && v.lender.Has(role) }

// seesAllLenderCases: an administrator, approver, finance or collections
// officer works across the lender's cases; a loan officer only on theirs.
func (v viewer) seesAllLenderCases() bool {
	return v.has(RoleAdministrator) || v.has(RoleCreditApprover) || v.has(RoleFinance) || v.has(RoleCollections)
}

// caseData is a case with its ledger position, if it has a ledger loan.
type caseData struct {
	record        CaseRecord
	loan          *LedgerLoan
	book          ledger.Book
	position      ledger.Position
	penaltyPaid   ledger.Money
	hasAllocation bool
	// The existing ledger's conditions for a first disbursement.
	purposePlanned ledger.Money
	hasBaseline    bool
	today          time.Time
}

func (c *caseData) hasLoan() bool { return c.loan != nil }

// readyToDisburse: the ledger's purpose plan matches the approved amount and
// an enrolment baseline is recorded.
func (c *caseData) readyToDisburse() bool {
	return c.loan != nil && c.purposePlanned == c.loan.Approved && c.hasBaseline
}

func (c *caseData) disbursed() bool { return c.loan != nil && c.position.NetDisbursed > 0 }

// reportedOnly: the lender reported the loan disbursed through referral
// tracking, before the lender workflow, and the ledger does not hold it yet.
func (c *caseData) reportedOnly() bool {
	return c.record.Referral.Status == StatusDisbursed && !c.disbursed() && c.stage() != StageClosed
}

// scheduleTerms are the terms the repayment schedule follows, on the
// principal actually disbursed: the school's accepted terms, or a
// lender-reported loan's recorded existing terms.
func (c *caseData) scheduleTerms(principal ledger.Money) (ledger.Terms, error) {
	if agreement := c.record.LatestAgreement(); agreement != nil && agreement.Status == "accepted" {
		for _, rec := range c.record.Recommendations {
			if rec.ID == agreement.RecommendationID {
				terms, err := rec.Terms()
				terms.Principal = principal
				return terms, err
			}
		}
		return ledger.Terms{}, need("action", "The accepted recommendation is missing.")
	}
	if e := c.record.Existing; e != nil {
		return e.Terms(principal)
	}
	return ledger.Terms{}, need("action", "The school's accepted terms are missing.")
}

func (c *caseData) settled() bool { return c.disbursed() && c.position.Status == ledger.StatusSettled }

func (c *caseData) assignedTo(userID string) bool {
	return c.record.Assignment != nil && c.record.Assignment.OfficerUserID == userID
}

func (l *Lending) load(ctx context.Context, applicationID string, v viewer) (*caseData, error) {
	partner := ""
	if v.lender != nil {
		partner = v.lender.PartnerID
	}
	record, err := l.store.CaseRecord(ctx, applicationID, partner)
	if err != nil {
		return nil, err
	}
	c := &caseData{record: record, today: ledger.DayOf(l.now().In(kampala))}
	if v.lender != nil && !v.seesAllLenderCases() && !c.assignedTo(v.lender.UserID) {
		return nil, ErrNotFound
	}
	if loanID := record.Referral.LinkedMFILoanID; loanID != "" {
		loan, book, penalty, err := l.store.LedgerBook(ctx, loanID)
		if err != nil {
			return nil, err
		}
		c.loan, c.book, c.penaltyPaid = &loan, book, penalty
		c.position = book.Position(c.today, dueWindowDays)
		if c.hasAllocation, err = l.store.HasFacilityAllocation(ctx, loanID); err != nil {
			return nil, err
		}
		planned, baseline, err := l.store.DisbursementReadiness(ctx, loanID)
		if err != nil {
			return nil, err
		}
		c.purposePlanned, c.hasBaseline = money(&planned), baseline
	}
	return c, nil
}

// Lender case stages: the lender's working filters (brief §9). Derived from
// the case's records, never stored, so they cannot drift.
const (
	StageUnassigned           = "unassigned"
	StageContactPending       = "contact_pending"
	StageAssessment           = "assessment_in_progress"
	StageAwaitingAgreement    = "awaiting_school_agreement"
	StageAwaitingCredit       = "awaiting_credit_review"
	StageApproved             = "approved"
	StageDeclined             = "declined"
	StageAwaitingDisbursement = "awaiting_disbursement"
	StageActive               = "active_loan"
	StageSettledPending       = "settled_collateral_pending"
	StageClosed               = "closed"
)

// StageLabels name the stages.
var StageLabels = map[string]string{
	StageUnassigned: "Unassigned", StageContactPending: "Contact pending", StageAssessment: "Assessment in progress",
	StageAwaitingAgreement: "Awaiting school agreement", StageAwaitingCredit: "Awaiting credit review",
	StageApproved: "Approved", StageDeclined: "Declined", StageAwaitingDisbursement: "Awaiting disbursement",
	StageActive: "Active loan", StageSettledPending: "Fully settled — collateral release pending", StageClosed: "Closed",
}

// StageOrder is the order the filters are offered in.
var StageOrder = []string{StageUnassigned, StageContactPending, StageAssessment, StageAwaitingAgreement,
	StageAwaitingCredit, StageApproved, StageAwaitingDisbursement, StageActive, StageSettledPending, StageDeclined, StageClosed}

func (c *caseData) collateralHeld() bool {
	for _, item := range c.record.Collateral {
		switch item.Status {
		case "verified", "accepted", "release_pending", "documents_requested", "under_verification", "disputed":
			return true
		}
	}
	return false
}

func (c *caseData) stage() string {
	r := c.record
	switch {
	case r.ClosureStatus == "closed" || r.Referral.Status == StatusWithdrawn || r.Referral.Status == StatusClosed:
		return StageClosed
	case c.settled() && c.collateralHeld():
		return StageSettledPending
	case c.disbursed():
		return StageActive
	case r.Referral.Status == StatusDeclined:
		return StageDeclined
	}
	if d := r.LatestDecision(); d != nil {
		switch d.Decision {
		case "declined":
			return StageDeclined
		case "approved":
			if c.hasLoan() {
				return StageAwaitingDisbursement
			}
			return StageApproved
		}
	}
	if rec := r.LatestRecommendation(); rec != nil && rec.Status == "submitted" {
		if a := r.LatestAgreement(); a != nil && a.RecommendationID == rec.ID && a.Status == "accepted" {
			return StageAwaitingCredit
		}
		return StageAwaitingAgreement
	}
	// Progress recorded through referral tracking alone, before this workflow.
	switch r.Referral.Status {
	case StatusDisbursed:
		return StageActive
	case StatusApproved:
		return StageApproved
	}
	if r.Assignment == nil {
		return StageUnassigned
	}
	for _, contact := range r.Contacts {
		if contact.Outcome == "reached" || contact.Outcome == "visit_scheduled" {
			return StageAssessment
		}
	}
	if r.Assessment != nil {
		return StageAssessment
	}
	return StageContactPending
}

func (c *caseData) pendingEvidence() []Evidence {
	var out []Evidence
	for _, e := range c.record.Evidence {
		if e.Status == "verification_pending" {
			out = append(out, e)
		}
	}
	return out
}
