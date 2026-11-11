package loans

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// actionInput is what a person submitted with an action.
type actionInput struct {
	values   map[string]string
	file     []byte
	fileName string
	today    time.Time
}

func (in actionInput) text(key, label string, required bool, limit int) (string, error) {
	value := strings.TrimSpace(in.values[key])
	switch {
	case value == "" && required:
		return "", need(key, label+" is required.")
	case len([]rune(value)) > limit:
		return "", need(key, fmt.Sprintf("Keep %s to %d characters.", strings.ToLower(label), limit))
	}
	return value, nil
}

func (in actionInput) money(key, label string, required bool) (ledger.Money, error) {
	raw := strings.TrimSpace(in.values[key])
	if raw == "" {
		if required {
			return 0, need(key, label+" is required.")
		}
		return 0, nil
	}
	amount, err := ParseUGX(raw)
	if err != nil {
		return 0, need(key, label+": "+err.Error())
	}
	return ledger.Shillings(amount), nil
}

func (in actionInput) date(key, label string, required, notFuture bool) (*time.Time, error) {
	raw := strings.TrimSpace(in.values[key])
	if raw == "" {
		if required {
			return nil, need(key, label+" is required.")
		}
		return nil, nil
	}
	day, err := time.Parse("2006-01-02", raw)
	if err != nil {
		return nil, need(key, label+" must be a date such as 2027-02-15.")
	}
	day = ledger.DayOf(day)
	if notFuture && day.After(in.today) {
		return nil, need(key, label+" cannot be in the future.")
	}
	return &day, nil
}

func (in actionInput) dates(key, label string) ([]time.Time, error) {
	raw := strings.FieldsFunc(in.values[key], func(r rune) bool { return r == ',' || r == ';' || r == '\n' || r == ' ' })
	if len(raw) == 0 {
		return nil, need(key, label+" are required: one date per school term.")
	}
	if len(raw) > 36 {
		return nil, need(key, "At most 36 repayment dates.")
	}
	var out []time.Time
	for _, item := range raw {
		day, err := time.Parse("2006-01-02", strings.TrimSpace(item))
		if err != nil {
			return nil, need(key, "Write each date as 2027-02-15, separated by commas.")
		}
		out = append(out, ledger.DayOf(day))
	}
	return out, nil
}

func (in actionInput) choice(key, label string, allowed []Option) (string, error) {
	value := strings.TrimSpace(in.values[key])
	for _, option := range allowed {
		if option.Value == value {
			return value, nil
		}
	}
	return "", need(key, "Choose "+strings.ToLower(label)+".")
}

func (in actionInput) check(key string) bool {
	return in.values[key] == "true" || in.values[key] == "yes"
}

// Field builders.
func field(key, label, kind string, required bool, help, value string, choices ...Option) *loansv1.ActionField {
	f := &loansv1.ActionField{Key: key, Label: label, Kind: kind, Required: required, Help: help, Value: value}
	for _, c := range choices {
		f.Choices = append(f.Choices, &loansv1.Choice{Value: c.Value, Label: c.Label})
	}
	return f
}

var (
	contactMethods = []Option{{"phone", "Phone call"}, {"visit", "In-person visit"}, {"sms", "SMS"}, {"email", "Email"},
		{"whatsapp", "WhatsApp"}, {"other", "Other approved channel"}}
	contactOutcomes = []Option{{"reached", "Reached the director"}, {"no_answer", "No answer"}, {"wrong_number", "Wrong number"},
		{"visit_scheduled", "Assessment visit scheduled"}, {"information_requested", "Information requested"}, {"other", "Other"}}
	assessmentOutcomes = []Option{{"recommend", "Recommend a loan"}, {"recommend_with_conditions", "Recommend with conditions"},
		{"do_not_recommend", "Do not recommend"}, {"more_information", "More information needed"}}
	paymentMethods = []Option{{"bank", "Bank deposit or transfer"}, {"mobile_money", "Mobile money"}, {"cheque", "Cheque"},
		{"cash", "Cash"}, {"other", "Other"}}
	interestMethods = []Option{{string(ledger.MethodDeclining), "Declining balance"}, {string(ledger.MethodFlat), "Flat"},
		{string(ledger.MethodNone), "No interest"}}
	collateralTypes = []Option{{"land_title", "Land title or property document"}, {"equipment", "Equipment"},
		{"vehicle", "Vehicle logbook"}, {"guarantee", "Personal or institutional guarantee"}, {"other", "Other lender-permitted security"}}
)

// caseAction is one thing a person may do on a case.
type caseAction struct {
	key, label, description string
	primary, danger         bool
	allowed                 func(c *caseData, v viewer) bool
	fields                  func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error)
	run                     func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error)
}

func open(c *caseData) bool { return c.stage() != StageClosed && c.stage() != StageDeclined }

func officerOrAdmin(c *caseData, v viewer) bool {
	return v.has(RoleAdministrator) || (v.has(RoleLoanOfficer) && c.assignedTo(v.lender.UserID))
}

func evidenceKey(applicationID, reference string, amount ledger.Money, paidOn time.Time) string {
	sum := sha256.Sum256([]byte(applicationID + "|" + strings.ToLower(reference) + "|" + amount.String() + "|" + paidOn.Format("2006-01-02")))
	return "evidence:" + hex.EncodeToString(sum[:16])
}

// lenderSender is a lender's staff member sending to a school: their
// administrator may send a reminder inside the cooldown, with a reason.
func lenderSender(v viewer) Sender {
	roles := []string{}
	for _, role := range lenderRoleOrder {
		if v.has(role) {
			roles = append(roles, role)
		}
	}
	return Sender{ID: v.lender.UserID, Name: v.lender.Name, Role: strings.Join(roles, ","), Organisation: v.lender.LenderName,
		IsLender: true, CanOverride: v.has(RoleAdministrator)}
}

func lenderActor(v viewer) Actor {
	return Actor{Kind: ActorLender, ID: v.lender.UserID, Name: v.lender.Name + " (" + v.lender.LenderName + ")", PartnerID: v.lender.PartnerID}
}

// caseActions is every action, in the order they are offered.
var caseActions = []caseAction{
	{
		key: "assign", label: "Assign a loan officer", primary: true,
		description: "The officer is notified in the app and the case appears in their list. Earlier assignments stay in the history.",
		allowed:     func(c *caseData, v viewer) bool { return v.has(RoleAdministrator) && c.stage() != StageClosed },
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			team, err := l.store.Team(ctx, v.lender.PartnerID)
			if err != nil {
				return nil, err
			}
			var officers []Option
			for _, m := range team {
				if m.MembershipActive && m.PlatformActive && contains(m.Roles, RoleLoanOfficer) {
					officers = append(officers, Option{m.UserID, fmt.Sprintf("%s (%d open cases)", m.Name, m.OpenCases)})
				}
			}
			return []*loansv1.ActionField{
				field("officer", "Loan officer", "choice", true, "", "", officers...),
				field("reason", "Reason", "text", c.record.Assignment != nil, "Required when reassigning.", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			team, err := l.store.Team(ctx, v.lender.PartnerID)
			if err != nil {
				return "", err
			}
			var officers []Option
			names := map[string]string{}
			for _, m := range team {
				if m.MembershipActive && m.PlatformActive && contains(m.Roles, RoleLoanOfficer) {
					officers = append(officers, Option{m.UserID, m.Name})
					names[m.UserID] = m.Name
				}
			}
			officer, err := in.choice("officer", "a loan officer", officers)
			if err != nil {
				return "", err
			}
			reason, err := in.text("reason", "A reason", c.record.Assignment != nil, 500)
			if err != nil {
				return "", err
			}
			if c.assignedTo(officer) {
				return "", need("officer", "The case is already assigned to "+names[officer]+".")
			}
			if err := l.store.Assign(ctx, c.record.Referral.ID, officer, names[officer], v.lender.UserID, v.lender.Name, reason, l.now()); err != nil {
				return "", err
			}
			if c.hasLoan() && !c.disbursed() {
				// The ledger's loan follows the new officer while it is
				// still being processed.
				reference := ""
				for _, m := range team {
					if m.UserID == officer {
						reference = m.OfficerReference
					}
				}
				if _, err := l.ledger.RegisterLoan(ctx, LoanRegistration{ReferralID: c.loan.ReferralID,
					ExternalReference: c.loan.ExternalReference, OfficerReference: reference, Approved: c.loan.Approved,
					Requested: c.loan.Requested}); err != nil {
					return "", err
				}
			}
			if c.record.Referral.Status == StatusSubmitted || c.record.Referral.Status == StatusAwaitingReceipt {
				if _, err := l.store.Act(ctx, c.record.Referral.ID, lenderActor(v), ActionAcknowledge, ActDetails{}, l.now()); err != nil {
					return "", err
				}
			}
			return "Assigned to " + names[officer] + ".", nil
		},
	},
	{
		key: "log_contact", label: "Record a contact attempt",
		description: "What you did and what happened. The platform records your entry; it does not call or message the school for you.",
		allowed:     func(c *caseData, v viewer) bool { return officerOrAdmin(c, v) && c.stage() != StageClosed },
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{
				field("contacted_on", "Date", "date", true, "", c.today.Format("2006-01-02")),
				field("method", "How", "choice", true, "", "phone", contactMethods...),
				field("outcome", "Outcome", "choice", true, "", "", contactOutcomes...),
				field("notes", "Notes", "multiline", false, "", ""),
				field("visit_on", "Assessment visit date", "date", false, "If a visit was scheduled.", ""),
				field("next_action_on", "Next action by", "date", false, "", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			on, err := in.date("contacted_on", "The date", true, true)
			if err != nil {
				return "", err
			}
			method, err := in.choice("method", "how you made contact", contactMethods)
			if err != nil {
				return "", err
			}
			outcome, err := in.choice("outcome", "the outcome", contactOutcomes)
			if err != nil {
				return "", err
			}
			notes, err := in.text("notes", "Notes", false, 2000)
			if err != nil {
				return "", err
			}
			visit, err := in.date("visit_on", "The visit date", false, false)
			if err != nil {
				return "", err
			}
			next, err := in.date("next_action_on", "The next action date", false, false)
			if err != nil {
				return "", err
			}
			err = l.store.AddContact(ctx, c.record.Referral.ID, Contact{OfficerName: v.lender.Name, Method: method,
				Outcome: outcome, Notes: notes, ContactedOn: *on, VisitOn: visit, NextActionOn: next, CreatedAt: l.now()}, v.lender.UserID)
			if err != nil {
				return "", err
			}
			if outcome == "reached" || outcome == "visit_scheduled" {
				if _, err := NextStatus(c.record.Referral.Status, ActionStartReview, ActorLender); err == nil {
					if _, err := l.store.Act(ctx, c.record.Referral.ID, lenderActor(v), ActionStartReview, ActDetails{}, l.now()); err != nil {
						return "", err
					}
				}
			}
			return "Contact recorded.", nil
		},
	},
	assessmentAction(),
	{
		key: "review_assessment", label: "Review the assessment",
		allowed: func(c *caseData, v viewer) bool {
			return v.has(RoleCreditApprover) && c.record.Assessment != nil && c.record.Assessment.Status == "submitted"
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{
				field("decision", "Decision", "choice", true, "", "", Option{"completed", "Complete it"}, Option{"returned", "Return for revision"}),
				field("note", "Note", "multiline", false, "Required when returning.", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			decision, err := in.choice("decision", "a decision", []Option{{"completed", ""}, {"returned", ""}})
			if err != nil {
				return "", err
			}
			note, err := in.text("note", "A note", decision == "returned", 2000)
			if err != nil {
				return "", err
			}
			a := *c.record.Assessment
			a.Status = decision
			return "Assessment " + decision + ".", l.store.SaveAssessment(ctx, c.record.Referral.ID, a, v.lender.UserID, v.lender.Name, note, l.now())
		},
	},
	recommendationAction(),
	agreementAction(),
	collateralAddAction(),
	collateralStatusAction(),
	decisionAction(),
	existingTermsAction(),
	{
		key: "register_loan", label: "Register the loan in the loan ledger", primary: true,
		description: "Records the approved loan in Edify's existing loan ledger, which holds its money from here on.",
		allowed: func(c *caseData, v viewer) bool {
			return (v.has(RoleAdministrator) || v.has(RoleFinance)) && c.record.LedgerReferral != "" &&
				(c.stage() == StageApproved || c.reportedOnly() && c.record.Existing != nil && !c.hasLoan())
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			reference := ""
			if e := c.record.Existing; e != nil {
				reference = e.ExternalReference
			}
			return []*loansv1.ActionField{field("external_reference", "Your loan number", "text", true,
				"The reference your own loan system gives this loan.", reference)}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			reference, err := in.text("external_reference", "Your loan number", true, 120)
			if err != nil {
				return "", err
			}
			var approved ledger.Money
			switch decision, existing := c.record.LatestDecision(), c.record.Existing; {
			case decision != nil && decision.ApprovedAmount != nil:
				approved = *decision.ApprovedAmount
			case existing != nil:
				approved = existing.Approved
			default:
				return "", need("action", "The approved amount is missing.")
			}
			officerReference := ""
			if c.record.Assignment != nil {
				team, err := l.store.Team(ctx, v.lender.PartnerID)
				if err != nil {
					return "", err
				}
				for _, m := range team {
					if m.UserID == c.record.Assignment.OfficerUserID {
						officerReference = m.OfficerReference
					}
				}
				if officerReference == "" {
					return "", need("external_reference", c.record.Assignment.OfficerName+
						" has no officer reference in your team, so the loan ledger would not let them work this loan. "+
						"Set it on the Team page first.")
				}
			}
			loanID, err := l.ledger.RegisterLoan(ctx, LoanRegistration{ReferralID: c.record.LedgerReferral, ExternalReference: reference,
				OfficerReference: officerReference, Approved: approved, Requested: ledger.Shillings(c.record.Referral.Requested)})
			if err != nil {
				return "", err
			}
			if loanID == "" {
				return "", errors.New("loans: the ledger did not return the loan's id")
			}
			return "Registered in the loan ledger.", l.store.SetLedgerLoan(ctx, c.record.Referral.ID, loanID, v.lender.UserID, v.lender.Name)
		},
	},
	prepareDisbursementAction(),
	disbursementAction(),
	finishDisbursementAction(),
	{
		key: "record_payment", label: "Record a payment", primary: true,
		description: "Records what the school paid, with its receipt. It counts towards the balance only once a finance officer verifies it.",
		allowed: func(c *caseData, v viewer) bool {
			// A payment is recorded against the ledger's loan, so the ledger must
			// hold the disbursement, not only the lender's report of it.
			return c.stage() == StageActive && c.disbursed() && !c.settled() &&
				(officerOrAdmin(c, v) || v.has(RoleCollections) || v.has(RoleFinance))
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{
				field("amount", "Amount paid (UGX)", "money", true, "", ""),
				field("paid_on", "Payment date", "date", true, "", c.today.Format("2006-01-02")),
				field("method", "Payment method", "choice", true, "", "", paymentMethods...),
				field("reference", "Transaction reference", "text", true, "As it appears on the receipt or statement.", ""),
				field("received_by", "Received by", "text", false, "", ""),
				field("notes", "Notes", "multiline", false, "", ""),
				field("file", "Receipt (PDF, JPEG or PNG)", "file", true, "", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			amount, err := in.money("amount", "The amount", true)
			if err != nil {
				return "", err
			}
			if amount <= 0 {
				return "", need("amount", "The amount must be more than UGX 0.")
			}
			paidOn, err := in.date("paid_on", "The payment date", true, true)
			if err != nil {
				return "", err
			}
			method, err := in.choice("method", "the payment method", paymentMethods)
			if err != nil {
				return "", err
			}
			reference, err := in.text("reference", "The transaction reference", true, 120)
			if err != nil {
				return "", err
			}
			receivedBy, err := in.text("received_by", "Received by", false, 200)
			if err != nil {
				return "", err
			}
			notes, err := in.text("notes", "Notes", false, 2000)
			if err != nil {
				return "", err
			}
			if len(in.file) == 0 {
				return "", need("file", "Attach the receipt.")
			}
			documentID, err := l.store.StoreDocument(ctx, c.record.Referral.ID, "receipt", in.fileName, in.file, v.lender.UserID, "lender")
			if err != nil {
				return "", err
			}
			_, already, err := l.store.SubmitEvidence(ctx, c.record.Referral.ID, Evidence{MFILoanID: c.loan.ID, Amount: amount, PaidOn: *paidOn,
				Method: method, Reference: reference, ReceivedBy: receivedBy, Notes: notes, DocumentID: documentID, Source: "lender",
				SubmittedBy: v.lender.UserID, SubmittedByName: v.lender.Name}, evidenceKey(c.record.Referral.ID, reference, amount, *paidOn), l.now())
			if err != nil {
				return "", err
			}
			if already {
				return "This payment was already recorded; nothing new was added.", nil
			}
			return "Payment recorded. It now awaits a finance officer's verification.", nil
		},
	},
	verifyAction(),
	reversalAction(),
	{
		key: "send_statement", label: "Send the school its statement link",
		description: "The director gets a private link; a one-time code sent to them opens it.",
		allowed: func(c *caseData, v viewer) bool {
			return c.disbursed() && (officerOrAdmin(c, v) || v.has(RoleCollections) || v.has(RoleFinance))
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{field("channel", "Send by", "choice", true, "", "sms", channelChoices(c)...)}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			channel, err := in.choice("channel", "how to send it", channelChoices(c))
			if err != nil {
				return "", err
			}
			_, message, err := l.sendSchoolLink(ctx, c, "statement", channel, lenderSender(v))
			return message, err
		},
	},
	{
		key: "answer_request", label: "Answer the school's request",
		allowed: func(c *caseData, v viewer) bool {
			if !(officerOrAdmin(c, v) || v.has(RoleCollections) || v.has(RoleFinance)) {
				return false
			}
			for _, r := range c.record.Requests {
				if r.Status == "open" {
					return true
				}
			}
			return false
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{
				field("request", "Request", "choice", true, "", "", openRequests(c)...),
				field("answer", "Answer", "multiline", true, "The school sees this on its statement.", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			request, err := in.choice("request", "a request", openRequests(c))
			if err != nil {
				return "", err
			}
			answer, err := in.text("answer", "The answer", true, 2000)
			if err != nil {
				return "", err
			}
			return "Answered.", l.store.AnswerSchoolRequest(ctx, c.record.Referral.ID, request, answer, v.lender.Name, l.now())
		},
	},
	{
		key: "close_loan", label: "Close the loan", danger: true,
		description: "Only a loan with nothing outstanding, no payment awaiting verification and all security returned can be closed.",
		allowed: func(c *caseData, v viewer) bool {
			return (v.has(RoleAdministrator) || v.has(RoleFinance)) && c.disbursed() &&
				(c.stage() == StageActive || c.stage() == StageSettledPending)
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			fields := []*loansv1.ActionField{field("note", "Closing note", "multiline", true, "", "")}
			if excess := c.overpaid(); excess > 0 {
				fields = append(fields, field("overpayment_settled", "The overpayment of "+ledger.FormatUGX(excess)+
					" has been refunded or settled with the school", "check", true, "Say how in the closing note.", ""))
			}
			return fields, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			note, err := in.text("note", "A closing note", true, 2000)
			if err != nil {
				return "", err
			}
			switch {
			case c.overpaid() > 0 && !in.check("overpayment_settled"):
				return "", need("overpayment_settled", "Confirm the overpayment of "+ledger.FormatUGX(c.overpaid())+" was refunded or settled.")
			case !c.settled():
				return "", need("action", fmt.Sprintf("The loan still has %s outstanding on the verified ledger.", ledger.FormatUGX(c.position.TotalOutstanding)))
			case len(c.pendingEvidence()) > 0:
				return "", need("action", "A payment is still awaiting verification.")
			case c.collateralHeld():
				return "", need("action", "Fully settled — collateral release pending. Release or return every security item first.")
			}
			if err := l.store.Close(ctx, c.record.Referral.ID, "closed", note, v.lender.UserID, v.lender.Name, l.now()); err != nil {
				return "", err
			}
			if _, err := NextStatus(c.record.Referral.Status, ActionClose, ActorLender); err == nil {
				if _, err := l.store.Act(ctx, c.record.Referral.ID, lenderActor(v), ActionClose, ActDetails{Note: note}, l.now()); err != nil {
					return "", err
				}
			}
			return "Loan closed.", nil
		},
	},
	{
		key: "refer_in_ledger", label: "Refer the school in the loan ledger", primary: true,
		description: "Creates the existing workflow's referral of this school to its lender, so the lender can register the approved loan.",
		allowed: func(c *caseData, v viewer) bool {
			return v.edify != nil && v.edify.managesLender && c.record.LedgerReferral == "" &&
				(c.stage() == StageApproved || c.reportedOnly() && c.record.Existing != nil)
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			if c.record.Referral.SchoolDirectoryID == "" {
				return nil, nil
			}
			cases, err := l.store.OpenCases(ctx, c.record.Referral.SchoolDirectoryID)
			if err != nil {
				return nil, err
			}
			purposes, err := l.store.GovernedPurposes(ctx)
			if err != nil {
				return nil, err
			}
			return []*loansv1.ActionField{
				field("case", "Business Transformation case", "choice", true, "The school's open case.", "", cases...),
				field("purpose", "Governed loan purpose", "choice", true, "", "", purposes...),
				field("intended_use", "Intended use", "multiline", true, "", strings.TrimSpace(c.record.Referral.PurposeLabel+". "+c.record.Referral.PurposeDetails)),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			if c.record.Referral.SchoolDirectoryID == "" {
				return "", need("action", "Link the application to its School Directory school first.")
			}
			cases, err := l.store.OpenCases(ctx, c.record.Referral.SchoolDirectoryID)
			if err != nil {
				return "", err
			}
			if len(cases) == 0 {
				return "", need("case", "This school has no open Business Transformation case. A referral in the loan ledger is made under one.")
			}
			caseID, err := in.choice("case", "a case", cases)
			if err != nil {
				return "", err
			}
			purposes, err := l.store.GovernedPurposes(ctx)
			if err != nil {
				return "", err
			}
			purpose, err := in.choice("purpose", "a governed purpose", purposes)
			if err != nil {
				return "", err
			}
			use, err := in.text("intended_use", "The intended use", true, 2000)
			if err != nil {
				return "", err
			}
			mfi, err := l.store.MFIOfPartner(ctx, c.record.Referral.PartnerID)
			if err != nil {
				return "", err
			}
			consent, err := l.store.ConsentRecordedAt(ctx, c.record.Referral.ID)
			if err != nil {
				return "", err
			}
			referralID, err := l.ledger.CreateReferral(ctx, ReferralRequest{CaseID: caseID, MFIID: mfi, PurposeID: purpose, IntendedUse: use,
				Requested: ledger.Shillings(c.record.Referral.Requested), ConsentRecordedAt: consent})
			if err != nil {
				return "", err
			}
			return "Referred in the loan ledger.", l.store.SetLedgerReferral(ctx, c.record.Referral.ID, referralID, v.principal.UserID, v.principal.Name)
		},
	},
	{
		key: "reserve_facility", label: "Reserve the loan in a funding facility", primary: true,
		description: "The existing workflow reserves every loan's amount in its lender's funding facility before money can be disbursed.",
		allowed: func(c *caseData, v viewer) bool {
			return v.edify != nil && v.edify.followsUp && c.hasLoan() && !c.hasAllocation && !c.disbursed()
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			facilities, err := l.store.Facilities(ctx, c.loan.MFIID)
			if err != nil {
				return nil, err
			}
			return []*loansv1.ActionField{
				field("facility", "Funding facility", "choice", true, "", "", facilities...),
				field("amount", "Amount (UGX)", "money", true, "", c.loan.Approved.String()),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			facilities, err := l.store.Facilities(ctx, c.loan.MFIID)
			if err != nil {
				return "", err
			}
			facility, err := in.choice("facility", "a facility", facilities)
			if err != nil {
				return "", err
			}
			amount, err := in.money("amount", "The amount", true)
			if err != nil {
				return "", err
			}
			if _, err := l.ledger.ReserveFacility(ctx, facility, c.loan.ID, amount, "allocation:"+c.loan.ID); err != nil {
				return "", err
			}
			return "Reserved in the funding facility.", nil
		},
	},
}

// overpaid is what verified payments brought in beyond what the loan owed.
func (c *caseData) overpaid() ledger.Money {
	var excess ledger.Money
	for _, e := range c.record.Evidence {
		if e.Status == "verified" {
			excess += e.Excess
		}
	}
	return excess
}

func contains(list []string, value string) bool {
	for _, item := range list {
		if item == value {
			return true
		}
	}
	return false
}

func channelChoices(c *caseData) []Option {
	choices := []Option{{"sms", "SMS to " + maskPhone(c.record.Referral.DirectorPhone)}}
	if c.record.Referral.DirectorEmail != "" {
		choices = append(choices, Option{"email", "Email to " + maskEmail(c.record.Referral.DirectorEmail)})
	}
	return choices
}

func maskPhone(phone string) string {
	if len(phone) < 6 {
		return "***"
	}
	return phone[:4] + strings.Repeat("•", len(phone)-7) + phone[len(phone)-3:]
}

func openRequests(c *caseData) []Option {
	var out []Option
	for _, r := range c.record.Requests {
		if r.Status == "open" {
			out = append(out, Option{r.ID, r.Kind + ": " + truncate(r.Message, 60)})
		}
	}
	return out
}

// sendSchoolLink sends the director a private link to their proposed terms
// or statement: by SMS through the school's notification history (so it
// counts towards the school's limits), or by email.
func (l *Lending) sendSchoolLink(ctx context.Context, c *caseData, purpose, channel string, sender Sender) (string, string, error) {
	byID := sender.ID
	kind := NoteStatement
	if purpose == "agreement" {
		kind = NoteAgreement
	}
	if channel != "email" {
		id, status, err := l.sendSchoolNote(ctx, c, kind, sender, "", "")
		if err != nil {
			return "", "", err
		}
		if status == "suppressed" {
			return id, "Not sent: the school's number has opted out of text messages. Send it by email instead.", nil
		}
		if l.sms == nil {
			return id, "Link queued. No SMS provider is configured on this server, so it has not been sent.", nil
		}
		return id, "Link queued to " + maskPhone(c.record.Referral.DirectorPhone) + "; it is sent within a minute.", nil
	}
	if l.mailer == nil {
		return "", "", need("channel", "Email is not configured on this server; send it by SMS.")
	}
	base, err := publicLink(l.cfg.PublicBaseURL, "")
	if err != nil {
		return "", "", need("action", "This server has no HTTPS public address set, so no link can be sent.")
	}
	destination := c.record.Referral.DirectorEmail
	token, err := l.store.IssueSchoolAccess(ctx, c.record.Referral.ID, purpose, "email", destination, byID, l.now())
	if err != nil {
		return "", "", err
	}
	facts := c.eligibleNotes(sender)[kind]
	body := renderNote(kind, c, facts, base+"/loan/"+purpose+"?t="+token)
	if _, err := l.mailer.Send(ctx, Message{To: destination, Subject: "Your school loan " + purpose + " from " + c.record.Referral.LenderName,
		Text: body + "\n\nEdify School Loans\n"}); err != nil {
		return "", "", err
	}
	return "", "Link emailed to " + maskEmail(destination) + ".", nil
}

func parseInt(raw string) (int, bool) {
	value, err := strconv.Atoi(strings.TrimSpace(raw))
	return value, err == nil
}
