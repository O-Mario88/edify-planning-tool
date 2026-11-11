package loans

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math/big"
	"strings"
	"time"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// assessmentFacts are the verified facts an assessment records, kept apart
// from the officer's findings. Only what a lender reasonably needs.
var assessmentFacts = []struct{ key, label, kind, help string }{
	{"enrollment_verified", "Enrollment verified", "number", "Learners counted or confirmed from registers."},
	{"registration", "Ownership or registration details", "text", ""},
	{"fees_collected_per_term", "Average fees actually collected per term (verified)", "money", "From fee records, preferably the last three terms."},
	{"fee_collection_history", "Fee collection history", "multiline", ""},
	{"operating_expenses_per_term", "Necessary operating expenses per term", "money", "Salaries, food, utilities, rent and other essentials."},
	{"existing_loans", "Existing loans and outstanding debts", "multiline", ""},
	{"debt_service_per_term", "Existing debt repayments per term", "money", ""},
	{"cash_flow", "Cash-flow notes and seasonal constraints", "multiline", ""},
}

var assessmentStatuses = []Option{{"in_progress", "In progress"}, {"information_required", "Additional information required"},
	{"submitted", "Submitted for review"}}

func assessmentAction() caseAction {
	return caseAction{
		key: "save_assessment", label: "Assess the school",
		description: "Facts you verified, then your findings. This never changes the School Directory.",
		allowed: func(c *caseData, v viewer) bool {
			if !(v.has(RoleLoanOfficer) && c.assignedTo(v.lender.UserID)) || !open(c) || c.disbursed() {
				return false
			}
			a := c.record.Assessment
			return a == nil || a.Status == "not_started" || a.Status == "in_progress" || a.Status == "information_required" || a.Status == "returned"
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			a := c.record.Assessment
			if a == nil {
				a = &Assessment{Facts: map[string]string{}}
			}
			value := func(key string) string { return a.Facts[key] }
			visit := ""
			if a.VisitOn != nil {
				visit = a.VisitOn.Format("2006-01-02")
			}
			fields := []*loansv1.ActionField{field("visit_on", "School visit date", "date", false, "", visit)}
			for _, fact := range assessmentFacts {
				fields = append(fields, field(fact.key, fact.label, fact.kind, false, fact.help, value(fact.key)))
			}
			return append(fields,
				field("observations", "Officer observations", "multiline", false, "", a.Observations),
				field("strengths", "Financial strengths", "multiline", false, "", a.Strengths),
				field("risks", "Financial risks", "multiline", false, "", a.Risks),
				field("documents_reviewed", "Documents reviewed", "multiline", false, "", a.DocumentsReviewed),
				field("outcome", "Assessment outcome", "choice", false, "", a.Outcome, assessmentOutcomes...),
				field("status", "Save as", "choice", true, "", "in_progress", assessmentStatuses...),
				field("file", "Supporting evidence (optional)", "file", false, "", ""),
			), nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			a := Assessment{Facts: map[string]string{}}
			if c.record.Assessment != nil {
				a.ID = c.record.Assessment.ID
			}
			var err error
			if a.VisitOn, err = in.date("visit_on", "The visit date", false, true); err != nil {
				return "", err
			}
			for _, fact := range assessmentFacts {
				switch fact.kind {
				case "money":
					amount, err := in.money(fact.key, fact.label, false)
					if err != nil {
						return "", err
					}
					if amount > 0 {
						a.Facts[fact.key] = amount.String()
					}
				case "number":
					if raw := strings.TrimSpace(in.values[fact.key]); raw != "" {
						number, ok := parseInt(strings.ReplaceAll(raw, ",", ""))
						if !ok || number < 0 {
							return "", need(fact.key, fact.label+" must be a whole number.")
						}
						a.Facts[fact.key] = fmt.Sprint(number)
					}
				default:
					text, err := in.text(fact.key, fact.label, false, 2000)
					if err != nil {
						return "", err
					}
					if text != "" {
						a.Facts[fact.key] = text
					}
				}
			}
			for key, target := range map[string]*string{"observations": &a.Observations, "strengths": &a.Strengths,
				"risks": &a.Risks, "documents_reviewed": &a.DocumentsReviewed} {
				if *target, err = in.text(key, "This field", false, 4000); err != nil {
					return "", err
				}
			}
			if raw := strings.TrimSpace(in.values["outcome"]); raw != "" {
				if a.Outcome, err = in.choice("outcome", "an outcome", assessmentOutcomes); err != nil {
					return "", err
				}
			}
			if a.Status, err = in.choice("status", "how to save it", assessmentStatuses); err != nil {
				return "", err
			}
			if a.Status == "submitted" && (a.Outcome == "" || a.VisitOn == nil || a.Facts["fees_collected_per_term"] == "") {
				return "", need("status", "Before submitting, record the visit date, the verified fees collected and an outcome.")
			}
			if len(in.file) > 0 {
				if _, err := l.store.StoreDocument(ctx, c.record.Referral.ID, "assessment", in.fileName, in.file, v.lender.UserID, "lender"); err != nil {
					return "", err
				}
			}
			if err := l.store.SaveAssessment(ctx, c.record.Referral.ID, a, v.lender.UserID, v.lender.Name, "", l.now()); err != nil {
				return "", err
			}
			if _, err := NextStatus(c.record.Referral.Status, ActionStartReview, ActorLender); err == nil {
				if _, err := l.store.Act(ctx, c.record.Referral.ID, lenderActor(v), ActionStartReview, ActDetails{}, l.now()); err != nil {
					return "", err
				}
			}
			return "Assessment saved.", nil
		},
	}
}

// Affordability is the worksheet's result: indicative only; the lender's
// credit decision is its own.
type Affordability struct {
	Collections, Expenses, DebtService, Available, Capacity ledger.Money
	CushionPercent                                          int
	LargestInstallment                                      ledger.Money
	InstallmentShare                                        int // largest installment as % of capacity
}

// Worksheet computes indicative repayment capacity: collections less
// necessary expenses and existing debt service, less a cushion for
// variability. It never assumes all fees are available for the loan.
func Worksheet(collections, expenses, debt ledger.Money, cushionPercent int, schedule []ledger.Installment) Affordability {
	a := Affordability{Collections: collections, Expenses: expenses, DebtService: debt, CushionPercent: cushionPercent}
	a.Available = max(collections-expenses-debt, 0)
	keep := new(big.Int).Mul(big.NewInt(int64(a.Available)), big.NewInt(int64(100-cushionPercent)))
	a.Capacity = ledger.Money(new(big.Int).Quo(keep, big.NewInt(100)).Int64())
	for _, installment := range schedule {
		a.LargestInstallment = max(a.LargestInstallment, installment.Total())
	}
	if a.Capacity > 0 {
		a.InstallmentShare = int(new(big.Int).Quo(new(big.Int).Mul(big.NewInt(int64(a.LargestInstallment)), big.NewInt(100)),
			big.NewInt(int64(a.Capacity))).Int64())
	}
	return a
}

func recommendationAction() caseAction {
	return caseAction{
		key: "recommend", label: "Prepare the credit recommendation", primary: true,
		description: "Your recommended amount and terms, with the affordability worksheet. It goes to the school for agreement, then to a credit approver.",
		allowed: func(c *caseData, v viewer) bool {
			if !(v.has(RoleLoanOfficer) && c.assignedTo(v.lender.UserID)) || c.disbursed() || !open(c) {
				return false
			}
			if a := c.record.Assessment; a == nil || a.Status != "completed" {
				return false
			}
			r := c.record.LatestRecommendation()
			return r == nil || r.Status == "returned" || r.Status == "submitted" && c.stage() == StageAwaitingAgreement
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			facts := c.record.Assessment.Facts
			moneyFact := func(key string) string {
				if raw := facts[key]; raw != "" {
					m, _ := ledger.ParseMoney(raw)
					return fmt.Sprint(int64(m) / 100)
				}
				return ""
			}
			return []*loansv1.ActionField{
				field("amount", "Recommended amount (UGX)", "money", true, fmt.Sprintf("The school asked for %s.", FormatUGX(c.record.Referral.Requested)),
					fmt.Sprint(c.record.Referral.Requested)),
				field("rate", "Interest rate per term (%)", "percent", true, "0 for no interest.", ""),
				field("method", "Interest calculation", "choice", true, "", string(ledger.MethodDeclining), interestMethods...),
				field("fee", "Fee per installment (UGX)", "money", false, "Only charges in your product.", "0"),
				field("due_dates", "Repayment dates", "dates", true, "One date per school term, e.g. 2027-02-15, 2027-06-01.", ""),
				field("collections", "Verified fees collected per term (UGX)", "money", true, "From the assessment.", moneyFact("fees_collected_per_term")),
				field("expenses", "Necessary operating expenses per term (UGX)", "money", true, "", moneyFact("operating_expenses_per_term")),
				field("debt", "Existing debt repayments per term (UGX)", "money", false, "", moneyFact("debt_service_per_term")),
				field("cushion", "Cushion for variability (%)", "number", true, "Your lending policy's assumption.", "20"),
				field("collateral_summary", "Proposed collateral or security", "multiline", false, "", ""),
				field("rationale", "Recommendation rationale", "multiline", true, "", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			amount, err := in.money("amount", "The recommended amount", true)
			if err != nil {
				return "", err
			}
			ratePercent := strings.TrimSpace(strings.TrimSuffix(in.values["rate"], "%"))
			rate, err := ledger.ParseRate(ratePercent)
			if err != nil {
				return "", need("rate", "Write the rate per term as a percentage, such as 2.5.")
			}
			method, err := in.choice("method", "how interest is calculated", interestMethods)
			if err != nil {
				return "", err
			}
			if (method == string(ledger.MethodNone)) != (rate.PPM == 0) {
				return "", need("rate", "Use a rate of 0 with no interest, and a rate above 0 otherwise.")
			}
			fee, err := in.money("fee", "The fee", false)
			if err != nil {
				return "", err
			}
			due, err := in.dates("due_dates", "Repayment dates")
			if err != nil {
				return "", err
			}
			if !due[0].After(c.today) {
				return "", need("due_dates", "The first repayment date must be after today.")
			}
			terms := ledger.Terms{Principal: amount, Rate: rate, Method: ledger.Method(method), FeePerInstallment: fee, DueDates: due}
			schedule, err := ledger.BuildSchedule(terms)
			if err != nil {
				return "", need("due_dates", capitalise(strings.TrimPrefix(err.Error(), "ledger: "))+".")
			}
			collections, err := in.money("collections", "Verified collections", true)
			if err != nil {
				return "", err
			}
			expenses, err := in.money("expenses", "Operating expenses", true)
			if err != nil {
				return "", err
			}
			debt, err := in.money("debt", "Existing debt repayments", false)
			if err != nil {
				return "", err
			}
			cushion, ok := parseInt(in.values["cushion"])
			if !ok || cushion < 0 || cushion > 90 {
				return "", need("cushion", "The cushion is a percentage from 0 to 90.")
			}
			worksheet := Worksheet(collections, expenses, debt, cushion, schedule)
			collateral, err := in.text("collateral_summary", "The collateral", false, 2000)
			if err != nil {
				return "", err
			}
			rationale, err := in.text("rationale", "A rationale", true, 4000)
			if err != nil {
				return "", err
			}
			capacity := worksheet.Capacity
			_, err = l.store.AddRecommendation(ctx, c.record.Referral.ID, Recommendation{Amount: amount, Capacity: &capacity,
				RatePercent: rate.Percent(), Method: method, Fee: fee, DueDates: due, CollateralSummary: collateral, Rationale: rationale,
				Affordability: map[string]string{
					"collections": collections.String(), "expenses": expenses.String(), "debt_service": debt.String(),
					"available": worksheet.Available.String(), "cushion_percent": fmt.Sprint(cushion),
					"capacity": worksheet.Capacity.String(), "largest_installment": worksheet.LargestInstallment.String(),
					"installment_share_percent": fmt.Sprint(worksheet.InstallmentShare),
				},
				Status: "submitted", SubmittedBy: v.lender.UserID, SubmittedByName: v.lender.Name}, l.now())
			if err != nil {
				return "", err
			}
			message := "Recommendation submitted. Send the proposed terms to the school next."
			if worksheet.InstallmentShare > 100 {
				message += fmt.Sprintf(" Note: the largest installment is %d%% of the indicative capacity.", worksheet.InstallmentShare)
			}
			return message, nil
		},
	}
}

// agreementTerms freezes a recommendation as the terms a school sees.
func agreementTerms(c *caseData, r Recommendation, today time.Time) (AgreementTerms, error) {
	terms, err := r.Terms()
	if err != nil {
		return AgreementTerms{}, err
	}
	schedule, err := ledger.BuildSchedule(terms)
	if err != nil {
		return AgreementTerms{}, err
	}
	var interest, fees, total ledger.Money
	out := AgreementTerms{
		Reference: c.record.Referral.Reference, School: c.record.Referral.SchoolName, Lender: c.record.Referral.LenderName,
		Purpose: c.record.Referral.PurposeLabel, Principal: r.Amount.String(), RatePercent: r.RatePercent, Method: r.Method,
		MethodDescription: ledger.MethodLabel(ledger.Method(r.Method)), Collateral: r.CollateralSummary,
		IssuedOn: today.Format("2006-01-02"),
		Conditions: []string{
			c.record.Referral.LenderName + " is the lender. Edify provides the referral and tracking platform and is not the lender.",
			"These are proposed terms. They bind only once the lender approves them and completes its own contracting process.",
			"Payments count towards your balance only once the lender verifies them.",
		},
	}
	for _, i := range schedule {
		interest += i.Interest
		fees += i.Fee
		total += i.Total()
		out.Installments = append(out.Installments, TermInstallment{Number: i.Number, DueDate: i.DueDate.Format("2006-01-02"),
			Principal: i.Principal.String(), Interest: i.Interest.String(), Fee: i.Fee.String(), Total: i.Total().String()})
	}
	out.TotalInterest, out.TotalFees, out.TotalRepayable = interest.String(), fees.String(), total.String()
	return out, nil
}

func agreementAction() caseAction {
	return caseAction{
		key: "issue_agreement", label: "Send the proposed terms to the school", primary: true,
		description: "The school reviews the exact terms and schedule, and accepts, declines or asks for clarification after a one-time code.",
		allowed: func(c *caseData, v viewer) bool {
			if !officerOrAdmin(c, v) || c.stage() != StageAwaitingAgreement {
				return false
			}
			r, a := c.record.LatestRecommendation(), c.record.LatestAgreement()
			return a == nil || a.RecommendationID != r.ID || a.Status != "issued"
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{field("channel", "Send by", "choice", true, "", "sms", channelChoices(c)...)}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			channel, err := in.choice("channel", "how to send it", channelChoices(c))
			if err != nil {
				return "", err
			}
			r := c.record.LatestRecommendation()
			terms, err := agreementTerms(c, *r, c.today)
			if err != nil {
				return "", err
			}
			if _, err := l.store.IssueAgreement(ctx, c.record.Referral.ID, r.ID, terms, v.lender.UserID, v.lender.Name, l.now()); err != nil {
				return "", err
			}
			_, message, err := l.sendSchoolLink(ctx, c, "agreement", channel, lenderSender(v))
			return message, err
		},
	}
}

func collateralAddAction() caseAction {
	return caseAction{
		key: "add_collateral", label: "Add a collateral item",
		description: "Record proposed security. Not every loan needs collateral.",
		allowed:     func(c *caseData, v viewer) bool { return officerOrAdmin(c, v) && open(c) && !c.settled() },
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{
				field("item_type", "Type", "choice", true, "", "", collateralTypes...),
				field("description", "Description", "multiline", true, "", ""),
				field("owner", "Declared owner", "text", false, "", ""),
				field("identification", "Identification or reference", "text", false, "Title number, serial number, logbook number.", ""),
				field("value", "Estimated or verified value (UGX)", "money", false, "", ""),
				field("value_date", "Valuation date", "date", false, "", ""),
				field("value_source", "Valuation source", "text", false, "", ""),
				field("document_type", "Document type", "text", false, "", ""),
				field("custodian", "Custodian", "text", false, "Who holds the original document.", ""),
				field("release_conditions", "Release conditions", "multiline", false, "", "Released on full settlement of the loan."),
				field("file", "Evidence (optional)", "file", false, "", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			itemType, err := in.choice("item_type", "a type", collateralTypes)
			if err != nil {
				return "", err
			}
			item := Collateral{ItemType: itemType}
			if item.Description, err = in.text("description", "A description", true, 2000); err != nil {
				return "", err
			}
			for key, target := range map[string]*string{"owner": &item.DeclaredOwner, "identification": &item.Identification,
				"value_source": &item.ValueSource, "document_type": &item.DocumentType, "custodian": &item.Custodian,
				"release_conditions": &item.ReleaseConditions} {
				if *target, err = in.text(key, "This field", false, 1000); err != nil {
					return "", err
				}
			}
			if value, err := in.money("value", "The value", false); err != nil {
				return "", err
			} else if value > 0 {
				item.EstimatedValue = &value
			}
			if item.ValueDate, err = in.date("value_date", "The valuation date", false, true); err != nil {
				return "", err
			}
			if len(in.file) > 0 {
				if _, err := l.store.StoreDocument(ctx, c.record.Referral.ID, "collateral", in.fileName, in.file, v.lender.UserID, "lender"); err != nil {
					return "", err
				}
			}
			return "Collateral item recorded as proposed.", l.store.AddCollateral(ctx, c.record.Referral.ID, item, v.lender.UserID, v.lender.Name, l.now())
		},
	}
}

// collateralMoves are the allowed status changes, and who may make them.
var collateralMoves = map[string]map[string]func(v viewer) bool{
	"proposed":            {"documents_requested": anyLender, "under_verification": anyLender, "disputed": approverOrAdmin},
	"documents_requested": {"under_verification": anyLender, "disputed": approverOrAdmin},
	"under_verification":  {"verified": approverOrAdmin, "documents_requested": anyLender, "disputed": approverOrAdmin},
	"verified":            {"accepted": approverOrAdmin, "disputed": approverOrAdmin},
	"accepted":            {"release_pending": releaser, "disputed": approverOrAdmin},
	"release_pending":     {"released": releaser},
	"disputed":            {"under_verification": approverOrAdmin},
}

func anyLender(v viewer) bool { return v.isLender() }

func approverOrAdmin(v viewer) bool { return v.has(RoleCreditApprover) || v.has(RoleAdministrator) }

func releaser(v viewer) bool { return v.has(RoleAdministrator) || v.has(RoleFinance) }

var collateralLabels = map[string]string{
	"proposed": "Proposed", "documents_requested": "Documents requested", "under_verification": "Under verification",
	"verified": "Verified", "accepted": "Accepted as security", "release_pending": "Release pending",
	"released": "Released or returned", "disputed": "Disputed",
}

func collateralMovesFor(c *caseData, v viewer) []Option {
	var out []Option
	for _, item := range c.record.Collateral {
		for to, may := range collateralMoves[item.Status] {
			if !may(v) || ((to == "release_pending" || to == "released") && !c.settled()) {
				continue
			}
			out = append(out, Option{item.ID + "|" + to, truncate(item.Description, 40) + " → " + collateralLabels[to]})
		}
	}
	return out
}

func collateralStatusAction() caseAction {
	return caseAction{
		key: "collateral_status", label: "Update a collateral item",
		description: "Only authorised lender staff verify, accept, dispute or release security. Release needs the loan fully settled and evidence.",
		allowed:     func(c *caseData, v viewer) bool { return v.isLender() && len(collateralMovesFor(c, v)) > 0 },
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{
				field("move", "Change", "choice", true, "", "", collateralMovesFor(c, v)...),
				field("note", "Note", "multiline", true, "", ""),
				field("released_on", "Release date", "date", false, "For a release.", ""),
				field("released_to", "Returned to", "text", false, "For a release: who received it.", ""),
				field("acknowledgment", "Recipient's acknowledgment", "text", false, "For a release.", ""),
				field("file", "Evidence", "file", false, "Required to verify or release.", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			move, err := in.choice("move", "a change", collateralMovesFor(c, v))
			if err != nil {
				return "", err
			}
			id, to, _ := strings.Cut(move, "|")
			note, err := in.text("note", "A note", true, 2000)
			if err != nil {
				return "", err
			}
			if (to == "verified" || to == "released") && len(in.file) == 0 {
				return "", need("file", "Attach the evidence for this.")
			}
			var releasedOn *time.Time
			var releasedTo, ack string
			if to == "released" {
				if releasedOn, err = in.date("released_on", "The release date", true, true); err != nil {
					return "", err
				}
				if releasedTo, err = in.text("released_to", "Who received it", true, 200); err != nil {
					return "", err
				}
				if ack, err = in.text("acknowledgment", "The acknowledgment", false, 500); err != nil {
					return "", err
				}
			}
			documentID := ""
			if len(in.file) > 0 {
				kind := "collateral"
				if to == "released" {
					kind = "release"
				}
				if documentID, err = l.store.StoreDocument(ctx, c.record.Referral.ID, kind, in.fileName, in.file, v.lender.UserID, "lender"); err != nil {
					return "", err
				}
			}
			return "Collateral is now " + strings.ToLower(collateralLabels[to]) + ".",
				l.store.SetCollateralStatus(ctx, c.record.Referral.ID, id, to, note, documentID, releasedTo, ack, releasedOn,
					v.lender.UserID, v.lender.Name, l.now())
		},
	}
}

func decisionAction() caseAction {
	decisions := []Option{{"approved", "Approve"}, {"declined", "Decline"}, {"returned", "Return to the officer"}}
	return caseAction{
		key: "decide", label: "Credit decision", primary: true,
		description: "Review the assessment, the school's agreement and any collateral, then decide. The officer who recommended cannot approve.",
		allowed: func(c *caseData, v viewer) bool {
			r := c.record.LatestRecommendation()
			return v.has(RoleCreditApprover) && c.stage() == StageAwaitingCredit && r != nil && r.SubmittedBy != v.lender.UserID
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			a := c.record.LatestAgreement()
			principal, _ := ledger.ParseMoney(a.Terms.Principal)
			return []*loansv1.ActionField{
				field("decision", "Decision", "choice", true, "", "", decisions...),
				field("approved_amount", "Approved amount (UGX)", "money", false,
					"Must be the amount the school agreed to; to change it, return the case for new terms.", fmt.Sprint(int64(principal)/100)),
				field("conditions", "Approval conditions are satisfied", "check", false, "Required to approve.", ""),
				field("rationale", "Decision rationale", "multiline", true, "", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			decision, err := in.choice("decision", "a decision", decisions)
			if err != nil {
				return "", err
			}
			rationale, err := in.text("rationale", "A rationale", true, 4000)
			if err != nil {
				return "", err
			}
			r, a := c.record.LatestRecommendation(), c.record.LatestAgreement()
			d := Decision{RecommendationID: r.ID, Decision: decision, Rationale: rationale, DecidedByName: v.lender.Name}
			if decision == "approved" {
				approved, err := in.money("approved_amount", "The approved amount", true)
				if err != nil {
					return "", err
				}
				agreed, _ := ledger.ParseMoney(a.Terms.Principal)
				if approved != agreed {
					return "", need("approved_amount", "The school agreed to "+ledger.FormatUGX(agreed)+
						". To approve a different amount, return the case so new terms can be agreed.")
				}
				if !in.check("conditions") {
					return "", need("conditions", "Confirm the approval conditions are satisfied.")
				}
				for _, item := range c.record.Collateral {
					if item.Status != "accepted" && item.Status != "released" {
						return "", need("decision", "Collateral item '"+truncate(item.Description, 40)+"' is "+
							strings.ToLower(collateralLabels[item.Status])+"; it must be accepted before approval.")
					}
				}
				d.ApprovedAmount, d.ConditionsConfirmed = &approved, true
			}
			if err := l.store.RecordDecision(ctx, c.record.Referral.ID, d, a.ID, v.lender.UserID, l.now()); err != nil {
				return "", err
			}
			switch decision {
			case "approved":
				months := 0
				if _, err := l.store.Act(ctx, c.record.Referral.ID, lenderActor(v), ActionApprove,
					ActDetails{ApprovedAmount: int64(*d.ApprovedAmount) / 100, TermMonths: months, Note: rationale,
						InterestRate: a.Terms.RatePercent + "% per term, " + a.Terms.MethodDescription}, l.now()); err != nil {
					return "", err
				}
				return "Approved. Edify now refers it in the loan ledger, then your finance officer registers and disburses it.", nil
			case "declined":
				if _, err := l.store.Act(ctx, c.record.Referral.ID, lenderActor(v), ActionDecline, ActDetails{Note: rationale}, l.now()); err != nil {
					return "", err
				}
				return "Declined.", nil
			}
			return "Returned to the officer for revision.", nil
		},
	}
}

var disbursementMethods = []Option{{"bank", "Bank transfer"}, {"mobile_money", "Mobile money"}, {"cheque", "Cheque"}, {"cash", "Cash"}}

func disbursementAction() caseAction {
	return caseAction{
		key: "record_disbursement", label: "Record the disbursement", primary: true,
		description: "Records money your organisation actually paid out, with evidence, in the loan ledger, and posts the repayment schedule. Edify moves no money.",
		allowed: func(c *caseData, v viewer) bool {
			if !v.has(RoleFinance) || !c.hasLoan() || !c.hasAllocation || !c.readyToDisburse() {
				return false
			}
			if c.reportedOnly() {
				// Whoever recorded the existing terms does not also post the money.
				return c.record.Existing != nil && c.record.Existing.RecordedBy != v.lender.UserID
			}
			if c.stage() != StageAwaitingDisbursement {
				return false
			}
			d := c.record.LatestDecision()
			return d != nil && d.Decision == "approved" && d.DecidedBy != v.lender.UserID
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			amount, on := fmt.Sprint(int64(c.loan.Approved)/100), c.today.Format("2006-01-02")
			help := ""
			if r := c.record.Referral; c.reportedOnly() {
				help = "As the loan was paid out; the referral tracking reported it."
				if r.Disbursed != nil {
					amount = fmt.Sprint(*r.Disbursed)
				}
				if r.DisbursementDate != nil {
					on = r.DisbursementDate.Format("2006-01-02")
				}
			}
			return []*loansv1.ActionField{
				field("amount", "Amount actually disbursed (UGX)", "money", true, help, amount),
				field("disbursed_on", "Disbursement date", "date", true, help, on),
				field("method", "Disbursement method", "choice", true, "", "bank", disbursementMethods...),
				field("reference", "Disbursement reference", "text", true, "", ""),
				field("bank_reference", "Bank or provider reference", "text", true, "", ""),
				field("recipient", "Recipient", "text", true, "The account or person paid.", c.record.Referral.SchoolName),
				field("file", "Evidence of disbursement", "file", true, "", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			amount, err := in.money("amount", "The amount", true)
			if err != nil {
				return "", err
			}
			if amount <= 0 || amount > c.loan.Approved {
				return "", need("amount", "The amount must be above UGX 0 and no more than the approved "+ledger.FormatUGX(c.loan.Approved)+".")
			}
			on, err := in.date("disbursed_on", "The disbursement date", true, true)
			if err != nil {
				return "", err
			}
			if on.Before(dayOf(c.record.Referral.SubmittedAt)) {
				return "", need("disbursed_on", "A disbursement cannot be dated before the application was submitted.")
			}
			method, err := in.choice("method", "the method", disbursementMethods)
			if err != nil {
				return "", err
			}
			reference, err := in.text("reference", "The reference", true, 120)
			if err != nil {
				return "", err
			}
			bank, err := in.text("bank_reference", "The bank reference", true, 120)
			if err != nil {
				return "", err
			}
			recipient, err := in.text("recipient", "The recipient", true, 200)
			if err != nil {
				return "", err
			}
			if len(in.file) == 0 {
				return "", need("file", "Attach the evidence of disbursement.")
			}
			// The schedule follows the agreed terms on the principal actually
			// disbursed (the ledger requires the two to match).
			terms, err := c.scheduleTerms(amount)
			if err != nil {
				return "", err
			}
			schedule, err := ledger.BuildSchedule(terms)
			if err != nil {
				return "", err
			}
			documentID, err := l.store.StoreDocument(ctx, c.record.Referral.ID, "disbursement", in.fileName, in.file, v.lender.UserID, "lender")
			if err != nil {
				return "", err
			}
			if _, err := l.ledger.PostDisbursement(ctx, DisbursementPosting{LoanID: c.loan.ID,
				IdempotencyKey: "disbursement:" + c.loan.ID + ":1", Amount: amount, Sequence: 1, DisbursedOn: *on, ValueDate: *on,
				ExternalReference: reference, BankReference: method + ": " + bank + " to " + recipient + " (document " + documentID + ")"}); err != nil {
				return "", err
			}
			if err := l.ledger.PostSchedule(ctx, c.loan.ID, 1, schedule); err != nil {
				l.logger.Error("loans: schedule not posted after a disbursement", slog.String("loan", c.loan.ID),
					slog.String("error", err.Error()))
				return "The disbursement is recorded in the loan ledger, but the repayment schedule was not posted. " +
					"Use \"Finish recording the disbursement\" to post it.", nil
			}
			return "Disbursement recorded in the loan ledger and the repayment schedule posted." + l.mirrorDisbursement(ctx, c, v, *on, reference, amount), nil
		},
	}
}

func prepareDisbursementAction() caseAction {
	return caseAction{
		key: "prepare_disbursement", label: "Record the purpose plan and enrolment baseline", primary: true,
		description: "The loan ledger needs both before the first disbursement: how the approved amount will be used, and how many learners the school has now.",
		allowed: func(c *caseData, v viewer) bool {
			return (officerOrAdmin(c, v) || v.has(RoleFinance)) && !c.readyToDisburse() &&
				(c.stage() == StageAwaitingDisbursement || c.reportedOnly() && c.hasLoan())
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			var fields []*loansv1.ActionField
			if c.purposePlanned != c.loan.Approved {
				purposes, err := l.store.GovernedPurposes(ctx)
				if err != nil {
					return nil, err
				}
				fields = append(fields,
					field("purpose", "Purpose", "choice", true, "The whole approved amount, "+ugx(c.loan.Approved)+", goes to this purpose.", "", purposes...),
					field("intended_output", "Intended output", "text", true, "What the money will produce, e.g. two classrooms.", c.record.Referral.PurposeDetails))
			}
			if !c.hasBaseline {
				learners := fmt.Sprint(c.record.Referral.Total)
				if a := c.record.Assessment; a != nil && a.Facts["enrollment_verified"] != "" {
					learners = a.Facts["enrollment_verified"]
				}
				fields = append(fields,
					field("learners", "Learners enrolled now", "number", true, "", learners),
					field("as_of", "Counted on", "date", true, "On or before the disbursement.", baselineDay(c)),
					field("cohort", "Who was counted", "text", true, "", "All enrolled learners, every class"),
					field("evidence", "Evidence", "text", true, "The register or record you counted from.", ""))
			}
			return fields, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			if c.purposePlanned != c.loan.Approved {
				purposes, err := l.store.GovernedPurposes(ctx)
				if err != nil {
					return "", err
				}
				purpose, err := in.choice("purpose", "a purpose", purposes)
				if err != nil {
					return "", err
				}
				output, err := in.text("intended_output", "The intended output", true, 500)
				if err != nil {
					return "", err
				}
				if err := l.ledger.SetPurposePlan(ctx, c.loan.ID, []PurposeLine{{PurposeID: purpose, IntendedOutput: output,
					Amount: c.loan.Approved}}); err != nil {
					return "", err
				}
			}
			if !c.hasBaseline {
				learners, ok := parseInt(strings.ReplaceAll(in.values["learners"], ",", ""))
				if !ok || learners < 0 {
					return "", need("learners", "Learners enrolled must be a whole number.")
				}
				asOf, err := in.date("as_of", "The count date", true, true)
				if err != nil {
					return "", err
				}
				cohort, err := in.text("cohort", "Who was counted", true, 255)
				if err != nil {
					return "", err
				}
				evidence, err := in.text("evidence", "The evidence", true, 255)
				if err != nil {
					return "", err
				}
				if err := l.ledger.RecordEnrolmentBaseline(ctx, c.loan.ID, learners, *asOf, cohort, evidence); err != nil {
					return "", err
				}
			}
			return "Recorded in the loan ledger. The loan can now be disbursed.", nil
		},
	}
}

// baselineDay is the default count date: today, or for a lender-reported
// loan the reported disbursement day, since the ledger needs the baseline on
// or before the disbursement.
func baselineDay(c *caseData) string {
	if on := c.record.Referral.DisbursementDate; c.reportedOnly() && on != nil {
		return on.Format("2006-01-02")
	}
	return c.today.Format("2006-01-02")
}

// mirrorDisbursement copies a ledger disbursement onto the referral's own
// tracking, which Edify's earlier pages read. The ledger is the record: a
// failure here is logged and reported, never undoes the posting.
func (l *Lending) mirrorDisbursement(ctx context.Context, c *caseData, v viewer, on time.Time, reference string, amount ledger.Money) string {
	if c.record.Referral.Status == StatusDisbursed {
		return ""
	}
	if _, err := l.store.Act(ctx, c.record.Referral.ID, lenderActor(v), ActionDisburse, ActDetails{
		DisbursedAmount: int64(amount) / 100, DisbursementDate: on, DisbursementReference: reference}, l.now()); err != nil {
		l.logger.Error("loans: referral tracking not updated after a disbursement", slog.String("application", c.record.Referral.ID),
			slog.String("error", err.Error()))
		return " Edify's referral tracking could not be updated (" + err.Error() + "); the loan ledger is correct."
	}
	return ""
}

// trackingBehind: the ledger has a disbursement that Edify's referral
// tracking could still record (its date rules allow it) but does not.
func (c *caseData) trackingBehind() bool {
	return c.record.Referral.Status != StatusDisbursed && len(c.book.Disbursements) > 0 &&
		!c.book.Disbursements[0].ValueDate.Before(dayOf(c.record.Referral.SubmittedAt))
}

// finishDisbursementAction completes a disbursement the ledger recorded
// when a later step (the schedule, or Edify's tracking) did not complete.
func finishDisbursementAction() caseAction {
	return caseAction{
		key: "finish_disbursement", label: "Finish recording the disbursement", primary: true,
		description: "The loan ledger has the disbursement but not yet its repayment schedule, or Edify's referral tracking is behind.",
		allowed: func(c *caseData, v viewer) bool {
			return v.has(RoleFinance) && c.disbursed() && c.stage() != StageClosed &&
				(len(c.book.Installments) == 0 || c.trackingBehind())
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return nil, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			if len(c.book.Installments) == 0 {
				terms, err := c.scheduleTerms(c.position.NetDisbursed)
				if err != nil {
					return "", err
				}
				schedule, err := ledger.BuildSchedule(terms)
				if err != nil {
					return "", err
				}
				if err := l.ledger.PostSchedule(ctx, c.loan.ID, 1, schedule); err != nil {
					return "", err
				}
			}
			first := c.book.Disbursements[0]
			note := l.mirrorDisbursement(ctx, c, v, first.ValueDate, first.Reference, c.position.NetDisbursed)
			return "Disbursement records completed." + note, nil
		},
	}
}

func pendingChoices(c *caseData) []Option {
	var out []Option
	for _, e := range c.pendingEvidence() {
		out = append(out, Option{e.ID, fmt.Sprintf("%s on %s, ref %s (by %s)", ledger.FormatUGX(e.Amount),
			e.PaidOn.Format("2 Jan 2006"), e.Reference, e.SubmittedByName)})
	}
	return out
}

func verifyAction() caseAction {
	decisions := []Option{{"verify", "Verified: post it to the ledger"}, {"reject", "Cannot verify: reject it"}}
	return caseAction{
		key: "verify_payment", label: "Verify a payment", primary: true,
		description: "Check the receipt against your own records. Only a verified payment reduces the school's balance. You cannot verify a payment you recorded yourself.",
		allowed: func(c *caseData, v viewer) bool {
			for _, e := range c.pendingEvidence() {
				if v.has(RoleFinance) && e.SubmittedBy != v.lender.UserID {
					return true
				}
			}
			return false
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{
				field("payment", "Payment", "choice", true, "", "", pendingChoices(c)...),
				field("decision", "Decision", "choice", true, "", "", decisions...),
				field("reason", "Reason", "multiline", false, "Required to reject.", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			id, err := in.choice("payment", "a payment", pendingChoices(c))
			if err != nil {
				return "", err
			}
			decision, err := in.choice("decision", "a decision", decisions)
			if err != nil {
				return "", err
			}
			var evidence Evidence
			for _, e := range c.record.Evidence {
				if e.ID == id {
					evidence = e
				}
			}
			if evidence.SubmittedBy == v.lender.UserID {
				return "", need("payment", "Someone else must verify a payment you recorded.")
			}
			if decision == "reject" {
				reason, err := in.text("reason", "A reason", true, 2000)
				if err != nil {
					return "", err
				}
				return "Payment rejected; the balance is unchanged.", l.store.RejectEvidence(ctx, c.record.Referral.ID, id, reason,
					v.lender.UserID, v.lender.Name, l.now())
			}
			far := time.Date(9999, 1, 1, 0, 0, 0, 0, time.UTC)
			allocations, excess := ledger.Allocate(evidence.Amount, c.book.Installments, c.book.AllocatedAsOf(far), ledger.DefaultOrder)
			applied := evidence.Amount - excess
			if applied <= 0 {
				return "", need("payment", "This loan owes nothing more on its schedule. Reject this as an overpayment and arrange a refund with the school.")
			}
			transactionID, err := l.ledger.PostRepayment(ctx, RepaymentPosting{LoanID: c.loan.ID, IdempotencyKey: "evidence:" + id,
				Amount: applied, ExternalReference: evidence.Reference, EvidenceReference: "Receipt document " + evidence.DocumentID,
				ReceivedOn: evidence.PaidOn, ValueDate: evidence.PaidOn, Allocations: allocations})
			if err != nil {
				return "", err
			}
			if transactionID == "" {
				return "", errors.New("loans: the ledger did not return the repayment's id")
			}
			if err := l.store.MarkEvidenceVerified(ctx, c.record.Referral.ID, id, transactionID, applied, excess,
				v.lender.UserID, v.lender.Name, l.now()); err != nil {
				return "", err
			}
			message := "Payment verified and posted: " + ledger.FormatUGX(applied) + "."
			if excess > 0 {
				message += " " + ledger.FormatUGX(excess) + " more than the loan owed is held as an overpayment for you to settle with the school."
			}
			return message, nil
		},
	}
}

func reversibleChoices(c *caseData) []Option {
	reversed := map[string]bool{}
	for _, p := range c.book.Payments {
		if p.Kind == ledger.KindReversal {
			reversed[p.ReversalOf] = true
		}
	}
	var out []Option
	for _, p := range c.book.Payments {
		if p.Kind == ledger.KindPayment && !reversed[p.ID] {
			var applied ledger.Money
			for _, a := range p.Allocations {
				applied += a.Amount
			}
			out = append(out, Option{p.ID, fmt.Sprintf("%s on %s, ref %s", ledger.FormatUGX(applied), p.ValueDate.Format("2 Jan 2006"), p.Reference)})
		}
	}
	return out
}

func reversalAction() caseAction {
	return caseAction{
		key: "reverse_payment", label: "Reverse a posted payment", danger: true,
		description: "Corrects an error: the payment stays in the history and a reversal is posted with its reason and evidence. The ledger allows this to your administrator.",
		allowed: func(c *caseData, v viewer) bool {
			return v.has(RoleFinance) && v.has(RoleAdministrator) && len(reversibleChoices(c)) > 0 && c.stage() != StageClosed
		},
		fields: func(ctx context.Context, l *Lending, c *caseData, v viewer) ([]*loansv1.ActionField, error) {
			return []*loansv1.ActionField{
				field("payment", "Payment", "choice", true, "", "", reversibleChoices(c)...),
				field("reason", "Reason", "multiline", true, "", ""),
				field("reference", "Reversal reference", "text", true, "", ""),
				field("evidence", "Evidence reference", "text", true, "The document or record showing the error.", ""),
			}, nil
		},
		run: func(ctx context.Context, l *Lending, c *caseData, v viewer, in actionInput) (string, error) {
			payment, err := in.choice("payment", "a payment", reversibleChoices(c))
			if err != nil {
				return "", err
			}
			reason, err := in.text("reason", "A reason", true, 2000)
			if err != nil {
				return "", err
			}
			reference, err := in.text("reference", "A reference", true, 120)
			if err != nil {
				return "", err
			}
			evidence, err := in.text("evidence", "The evidence", true, 255)
			if err != nil {
				return "", err
			}
			if _, err := l.ledger.ReverseRepayment(ctx, payment, "reversal:"+payment, reason, reference, evidence); err != nil {
				return "", err
			}
			return "Payment reversed; the original stays in the history.", nil
		},
	}
}
