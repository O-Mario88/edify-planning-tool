package loans

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// Ledger is the posting boundary for loan money events, satisfied by both
// LedgerClient (legacy Django HTTP) and NativeLedger (Go PostgreSQL SECURITY DEFINER).
type Ledger interface {
	CreateReferral(ctx context.Context, r ReferralRequest) (string, error)
	RegisterLoan(ctx context.Context, r LoanRegistration) (string, error)
	ReserveFacility(ctx context.Context, facilityID, loanID string, amount ledger.Money, key string) (string, error)
	PostDisbursement(ctx context.Context, d DisbursementPosting) (string, error)
	PostSchedule(ctx context.Context, loanID string, version int, rows []ledger.Installment) error
	PostRepayment(ctx context.Context, r RepaymentPosting) (string, error)
	ReverseRepayment(ctx context.Context, transactionID, key, reason, reference, evidence string) (string, error)
	SetOfficerReference(ctx context.Context, mfiID, userID, reference string) error
	SetPurposePlan(ctx context.Context, loanID string, lines []PurposeLine) error
	RecordEnrolmentBaseline(ctx context.Context, loanID string, learners int, asOf time.Time, cohort, evidence string) error
}

// LedgerClient posts the money events of a loan to the existing ledger
// (apps/business_transformation, /api/business-transformation/...), as the
// signed-in person: the existing application checks their permission and
// lender scope, writes the posting and its audit event, and stays the only
// writer of loans, disbursements, schedules and repayments (owner,
// 2026-11-11: "Existing ledger, Go orchestrates").
type LedgerClient struct {
	base string
	http *http.Client
}

// NewLedgerClient returns a client for the existing application at base;
// base empty means there is no ledger to post to on this server.
func NewLedgerClient(base string) *LedgerClient {
	return &LedgerClient{base: strings.TrimRight(base, "/"), http: &http.Client{Timeout: 30 * time.Second}}
}

// ErrLedgerUnavailable: no existing application is configured, or it did
// not answer. Nothing was posted.
var ErrLedgerUnavailable = errors.New("loans: the loan ledger is not reachable")

// LedgerRefusal is the existing ledger refusing a posting, with its reason.
type LedgerRefusal struct {
	Status  int
	Message string
}

func (e *LedgerRefusal) Error() string { return "The loan ledger refused this: " + e.Message }

func (c *LedgerClient) post(ctx context.Context, path string, body any) (map[string]any, error) {
	if c == nil || c.base == "" {
		return nil, ErrLedgerUnavailable
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/api/business-transformation/"+path, bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Authorization", "Bearer "+auth.BearerFrom(ctx))
	if span := trace.FromContext(ctx); span.RequestID != "" {
		request.Header.Set(trace.HeaderRequestID, span.RequestID)
	}
	response, err := c.http.Do(request)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrLedgerUnavailable, err)
	}
	defer func() { _ = response.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	if response.StatusCode >= 500 {
		return nil, fmt.Errorf("%w: status %d", ErrLedgerUnavailable, response.StatusCode)
	}
	var decoded any
	_ = json.Unmarshal(raw, &decoded)
	if response.StatusCode >= 300 {
		return nil, &LedgerRefusal{Status: response.StatusCode, Message: refusalText(decoded)}
	}
	if object, ok := decoded.(map[string]any); ok {
		return object, nil
	}
	if list, ok := decoded.([]any); ok {
		return map[string]any{"items": list}, nil
	}
	return map[string]any{}, nil
}

// refusalText is the message the existing application gave.
func refusalText(decoded any) string {
	if object, ok := decoded.(map[string]any); ok {
		for _, key := range []string{"message", "detail", "error"} {
			if text, ok := object[key].(string); ok && text != "" {
				return text
			}
		}
		for key, value := range object {
			if list, ok := value.([]any); ok && len(list) > 0 {
				return fmt.Sprintf("%s: %v", key, list[0])
			}
		}
	}
	return "no reason given"
}

func idOf(answer map[string]any) string {
	if id, ok := answer["id"].(string); ok {
		return id
	}
	if items, ok := answer["items"].([]any); ok && len(items) > 0 {
		if first, ok := items[0].(map[string]any); ok {
			if id, ok := first["id"].(string); ok {
				return id
			}
		}
	}
	return ""
}

// ReferralRequest is the existing workflow's referral of a school to its
// lender (staff with referral permission).
type ReferralRequest struct {
	CaseID, MFIID, PurposeID, IntendedUse string
	Requested                             ledger.Money
	ConsentRecordedAt                     time.Time
}

// CreateReferral records the referral and returns its id.
func (c *LedgerClient) CreateReferral(ctx context.Context, r ReferralRequest) (string, error) {
	answer, err := c.post(ctx, "referrals", map[string]any{
		"caseId": r.CaseID, "mfiId": r.MFIID, "purposeId": r.PurposeID, "requestedAmount": r.Requested.String(),
		"intendedUse": r.IntendedUse, "consentRecordedAt": r.ConsentRecordedAt.UTC().Format(time.RFC3339),
	})
	if err != nil {
		return "", err
	}
	return idOf(answer), nil
}

// LoanRegistration registers the approved loan in the ledger (the lender).
type LoanRegistration struct {
	ReferralID, ExternalReference, OfficerReference string
	Approved, Requested                             ledger.Money
	TermMonths                                      int
}

// RegisterLoan records the loan and returns its id.
func (c *LedgerClient) RegisterLoan(ctx context.Context, r LoanRegistration) (string, error) {
	body := map[string]any{
		"referralId": r.ReferralID, "externalLoanReference": r.ExternalReference,
		"approvedAmount": r.Approved.String(), "requestedAmount": r.Requested.String(),
		"assignedOfficerReference": r.OfficerReference, "status": "processing",
	}
	if r.TermMonths > 0 {
		body["termMonths"] = r.TermMonths
	}
	answer, err := c.post(ctx, "loans", body)
	if err != nil {
		return "", err
	}
	return idOf(answer), nil
}

// ReserveFacility reserves the loan's amount in a funding facility (BTO).
func (c *LedgerClient) ReserveFacility(ctx context.Context, facilityID, loanID string, amount ledger.Money, key string) (string, error) {
	answer, err := c.post(ctx, "facility-allocations", map[string]any{
		"facilityId": facilityID, "loanId": loanID, "amount": amount.String(), "idempotencyKey": key,
	})
	if err != nil {
		return "", err
	}
	return idOf(answer), nil
}

// DisbursementPosting is money the lender paid out.
type DisbursementPosting struct {
	LoanID, IdempotencyKey, ExternalReference, BankReference string
	Amount                                                   ledger.Money
	Sequence                                                 int
	DisbursedOn, ValueDate                                   time.Time
}

// PostDisbursement records a disbursement and returns its id.
func (c *LedgerClient) PostDisbursement(ctx context.Context, d DisbursementPosting) (string, error) {
	answer, err := c.post(ctx, "loan-disbursements", map[string]any{
		"loanId": d.LoanID, "idempotencyKey": d.IdempotencyKey, "amount": d.Amount.String(), "sequence": d.Sequence,
		"externalReference": d.ExternalReference, "bankReference": d.BankReference,
		"disbursedOn": d.DisbursedOn.Format("2006-01-02"), "valueDate": d.ValueDate.Format("2006-01-02"),
	})
	if err != nil {
		return "", err
	}
	return idOf(answer), nil
}

// PostSchedule records a schedule version (a version is posted once).
func (c *LedgerClient) PostSchedule(ctx context.Context, loanID string, version int, rows []ledger.Installment) error {
	installments := make([]map[string]any, len(rows))
	for index, row := range rows {
		installments[index] = map[string]any{
			"installmentNumber": row.Number, "dueDate": row.DueDate.Format("2006-01-02"),
			"principalDue": row.Principal.String(), "interestDue": row.Interest.String(), "feeDue": row.Fee.String(),
		}
	}
	_, err := c.post(ctx, "loans/"+url.PathEscape(loanID)+"/repayment-schedule", map[string]any{"version": version, "installments": installments})
	return err
}

// RepaymentPosting is a verified repayment with its allocations.
type RepaymentPosting struct {
	LoanID, IdempotencyKey, ExternalReference, EvidenceReference string
	Amount                                                       ledger.Money
	ReceivedOn, ValueDate                                        time.Time
	Allocations                                                  []ledger.Allocation
}

// PostRepayment records a verified repayment and returns its id.
func (c *LedgerClient) PostRepayment(ctx context.Context, r RepaymentPosting) (string, error) {
	allocations := make([]map[string]any, len(r.Allocations))
	for index, a := range r.Allocations {
		allocations[index] = map[string]any{"installmentId": a.InstallmentID, "component": string(a.Component), "amount": a.Amount.String()}
	}
	answer, err := c.post(ctx, "repayment-transactions", map[string]any{
		"loanId": r.LoanID, "idempotencyKey": r.IdempotencyKey, "amount": r.Amount.String(),
		"externalReference": r.ExternalReference, "evidenceReference": r.EvidenceReference,
		"receivedOn": r.ReceivedOn.Format("2006-01-02"), "valueDate": r.ValueDate.Format("2006-01-02"),
		"allocations": allocations,
	})
	if err != nil {
		return "", err
	}
	return idOf(answer), nil
}

// ReverseRepayment reverses a posted repayment, with its reason and evidence.
func (c *LedgerClient) ReverseRepayment(ctx context.Context, transactionID, key, reason, reference, evidence string) (string, error) {
	answer, err := c.post(ctx, "repayment-transactions/"+url.PathEscape(transactionID)+"/reverse", map[string]any{
		"idempotencyKey": key, "reason": reason, "externalReference": reference, "evidenceReference": evidence,
	})
	if err != nil {
		return "", err
	}
	return idOf(answer), nil
}

// SetOfficerReference records a loan officer's reference on their lender
// membership. The existing application keeps the membership; the caller
// must be that lender's administrator.
func (c *LedgerClient) SetOfficerReference(ctx context.Context, mfiID, userID, reference string) error {
	_, err := c.post(ctx, "mfi-members", map[string]any{"mfiId": mfiID, "userId": userID, "officerReference": reference})
	return err
}

// PurposeLine is one line of a loan's purpose plan.
type PurposeLine struct {
	PurposeID, IntendedOutput string
	Amount                    ledger.Money
}

// SetPurposePlan records how the approved amount is to be used; the plan
// must add up to the approved amount exactly.
func (c *LedgerClient) SetPurposePlan(ctx context.Context, loanID string, lines []PurposeLine) error {
	rows := make([]map[string]any, len(lines))
	for index, line := range lines {
		rows[index] = map[string]any{"purposeId": line.PurposeID, "plannedAmount": line.Amount.String(),
			"intendedOutput": line.IntendedOutput}
	}
	_, err := c.post(ctx, "loans/"+url.PathEscape(loanID)+"/purpose-allocations", map[string]any{"allocations": rows})
	return err
}

// RecordEnrolmentBaseline records the learners enrolled before the loan.
func (c *LedgerClient) RecordEnrolmentBaseline(ctx context.Context, loanID string, learners int, asOf time.Time, cohort, evidence string) error {
	_, err := c.post(ctx, "loans/"+url.PathEscape(loanID)+"/enrolment-snapshots", map[string]any{"kind": "baseline",
		"learnerCount": learners, "asOfDate": asOf.Format("2006-01-02"), "cohortDefinition": cohort, "evidenceReference": evidence})
	return err
}
