package loans

import (
	"context"
	"fmt"
	"strings"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// A loan the lender reported as disbursed before the lender workflow enters
// the loan ledger through the same steps as any loan (owner, 2026-11-11:
// "Lender registers them"): the lender records its existing terms with the
// signed agreement, Edify's Country Director refers it in the ledger, the
// lender registers it, the BTO reserves the facility, the lender records the
// purpose plan and baseline, and a finance officer other than the person who
// recorded the terms posts the disbursement. Nothing is invented: no
// recommendation or credit decision is created for it.

func existingTermsAction() caseAction {
	return caseAction{
		key: "record_existing_terms", label: "Record the existing loan's terms", primary: true,
		description: "This loan was reported disbursed before it was in the loan ledger. Record the terms the school signed, " +
			"with the signed agreement, so the loan can be registered and its repayment schedule posted.",
		allowed: func(c *caseData, v viewer) bool {
			return (v.has(RoleAdministrator) || v.has(RoleFinance)) && c.reportedOnly() && c.record.Existing == nil
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			r := c.record.Referral
			approved := ""
			switch {
			case r.Approved != nil:
				approved = fmt.Sprint(*r.Approved)
			case r.Disbursed != nil:
				approved = fmt.Sprint(*r.Disbursed)
			}
			return []*loansv1.ActionField{
				field("external_reference", "Your loan number", "text", true, "The reference your own loan system gives this loan.", ""),
				field("amount", "Approved amount (UGX)", "money", true, "As in the signed agreement.", approved),
				field("approved_on", "Approval date", "date", true, "", ""),
				field("rate", "Interest rate per term (%)", "percent", true, "As in the signed agreement. 0 for no interest.", r.InterestRate),
				field("method", "Interest calculation", "choice", true, "", string(ledger.MethodDeclining), interestMethods...),
				field("fee", "Fee per installment (UGX)", "money", false, "Only charges in the signed agreement.", "0"),
				field("due_dates", "Repayment dates", "dates", true, "Every date in the signed agreement, e.g. 2027-02-15, 2027-06-01.", ""),
				field("file", "Signed loan agreement", "file", true, "", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			terms, err := readExistingTerms(c, in)
			if err != nil {
				return "", err
			}
			if len(in.file) == 0 {
				return "", need("file", "Attach the signed loan agreement.")
			}
			documentID, err := l.store.StoreDocument(ctx, c.record.Referral.ID, "agreement", in.fileName, in.file, v.lender.UserID, "lender")
			if err != nil {
				return "", err
			}
			terms.AgreementDocumentID, terms.RecordedBy, terms.RecordedByName = documentID, v.lender.UserID, v.lender.Name
			if err := l.store.RecordExistingTerms(ctx, c.record.Referral.ID, terms); err != nil {
				return "", err
			}
			return "Terms recorded. Edify's Country Director now refers the loan in the loan ledger, then you register it.", nil
		},
	}
}

// readExistingTerms checks the terms as entered; they must build a schedule.
func readExistingTerms(c *caseData, in actionInput) (ExistingTerms, error) {
	reference, err := in.text("external_reference", "Your loan number", true, 120)
	if err != nil {
		return ExistingTerms{}, err
	}
	amount, err := in.money("amount", "The approved amount", true)
	if err != nil {
		return ExistingTerms{}, err
	}
	if amount <= 0 {
		return ExistingTerms{}, need("amount", "The approved amount must be more than UGX 0.")
	}
	approvedOn, err := in.date("approved_on", "The approval date", true, true)
	if err != nil {
		return ExistingTerms{}, err
	}
	// Form dates are calendar days at UTC midnight; compare like with like.
	if approvedOn.Before(ledger.DayOf(dayOf(c.record.Referral.SubmittedAt))) {
		return ExistingTerms{}, need("approved_on", "The approval cannot be dated before the application was submitted.")
	}
	if on := c.record.Referral.DisbursementDate; on != nil && approvedOn.After(ledger.DayOf(dayOf(*on))) {
		return ExistingTerms{}, need("approved_on", "The approval cannot be dated after the reported disbursement ("+day(*on)+").")
	}
	ratePercent := strings.TrimSpace(strings.TrimSuffix(in.values["rate"], "%"))
	rate, err := ledger.ParseRate(ratePercent)
	if err != nil {
		return ExistingTerms{}, need("rate", "Write the rate per term as a percentage, such as 2.5.")
	}
	method, err := in.choice("method", "how interest is calculated", interestMethods)
	if err != nil {
		return ExistingTerms{}, err
	}
	if (method == string(ledger.MethodNone)) != (rate.PPM == 0) {
		return ExistingTerms{}, need("rate", "Use a rate of 0 with no interest, and a rate above 0 otherwise.")
	}
	fee, err := in.money("fee", "The fee", false)
	if err != nil {
		return ExistingTerms{}, err
	}
	dueDates, err := in.dates("due_dates", "The repayment dates")
	if err != nil {
		return ExistingTerms{}, err
	}
	e := ExistingTerms{ExternalReference: reference, Approved: amount, ApprovedOn: *approvedOn, RatePercent: ratePercent,
		Method: method, Fee: fee, DueDates: dueDates}
	terms, err := e.Terms(amount)
	if err != nil {
		return ExistingTerms{}, err
	}
	if _, err := ledger.BuildSchedule(terms); err != nil {
		return ExistingTerms{}, need("due_dates", "These terms do not make a schedule: "+err.Error())
	}
	return e, nil
}

// existingLoanSection lists the steps that bring a lender-reported loan into
// the loan ledger: done, the next one (and who takes it), and those after.
func (c *caseData) existingLoanSection() *loansv1.CaseSection {
	if !c.reportedOnly() {
		return nil
	}
	e := c.record.Existing
	termsDone := ""
	if e != nil {
		termsDone = "Recorded by " + e.RecordedByName + " on " + day(e.RecordedAt.In(kampala))
	}
	steps := []struct {
		label, who, done string
		isDone           bool
	}{
		{"Existing terms and signed agreement", "Lender administrator or finance officer", termsDone, e != nil},
		{"Referral in the loan ledger", "Edify Country Director", "Done", c.record.LedgerReferral != ""},
		{"Registration in the loan ledger", "Lender administrator or finance officer", "Done", c.hasLoan()},
		{"Funding facility reserved", "Edify BTO", "Done", c.hasAllocation},
		{"Purpose plan and enrolment baseline", "Lender", "Done", c.readyToDisburse()},
		{"Disbursement and repayment schedule", "A lender finance officer other than whoever recorded the terms", "Done", false},
	}
	var lines []*loansv1.CaseLine
	waiting := false
	for _, step := range steps {
		switch {
		case step.isDone:
			lines = append(lines, toned(step.label, step.done, "good"))
		case !waiting:
			waiting = true
			lines = append(lines, toned(step.label, "Next: "+step.who, "caution"))
		default:
			lines = append(lines, line(step.label, step.who))
		}
	}
	return section("existing_loan", "Bringing this loan into the ledger",
		"The lender reported this loan disbursed before it was in the loan ledger. Until these steps are done, "+
			"payments cannot be recorded against it and the school's balance is not shown.", lines...)
}
