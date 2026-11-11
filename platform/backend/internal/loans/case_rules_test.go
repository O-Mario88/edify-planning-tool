package loans

import (
	"bytes"
	"context"
	"errors"
	"regexp"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// The lending rules that need no database: who may take which step when,
// what each step refuses, and how a case's stage follows its records.

var (
	ruleDay     = time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC)
	ruleDueDays = []time.Time{time.Date(2027, 2, 15, 0, 0, 0, 0, time.UTC),
		time.Date(2027, 6, 1, 0, 0, 0, 0, time.UTC), time.Date(2027, 9, 15, 0, 0, 0, 0, time.UTC)}
	ruleAmount = ledger.Shillings(30_000_000)
)

func lenderStaff(id string, roles ...string) viewer {
	identity := &LenderIdentity{UserID: id, Name: id, Roles: map[string]bool{}}
	for _, role := range roles {
		identity.Roles[role] = true
	}
	return viewer{lender: identity}
}

func offered(c *caseData, v viewer) map[string]bool {
	out := map[string]bool{}
	for _, action := range (&Lending{}).actionsFor(c, v) {
		out[action.key] = true
	}
	return out
}

func actionNamed(t *testing.T, key string) caseAction {
	t.Helper()
	for _, action := range caseActions {
		if action.key == key {
			return action
		}
	}
	t.Fatalf("no action %q", key)
	return caseAction{}
}

// newCase is an application assigned to officer "off", recommended by them
// at 30M over three terms at 3% declining, and accepted by the school.
func newCase(t *testing.T) *caseData {
	t.Helper()
	agreed := AgreementTerms{Principal: ruleAmount.String(), RatePercent: "3", MethodDescription: "Declining balance"}
	return &caseData{today: ruleDay, record: CaseRecord{
		Referral:   Referral{ID: "app", Status: StatusUnderReview, Requested: 30_000_000, SubmittedAt: ruleDay.AddDate(0, 0, -30)},
		Assignment: &Assignment{OfficerUserID: "off", OfficerName: "Officer"},
		Contacts:   []Contact{{Outcome: "reached"}},
		Assessment: &Assessment{Status: "completed", Facts: map[string]string{}},
		Recommendations: []Recommendation{{ID: "rec", Amount: ruleAmount, RatePercent: "3", Method: string(ledger.MethodDeclining),
			DueDates: ruleDueDays, Status: "submitted", SubmittedBy: "off"}},
		Agreements: []Agreement{{ID: "agr", RecommendationID: "rec", Status: "accepted", Terms: agreed}},
	}}
}

func approve(c *caseData, by string) {
	amount := ruleAmount
	c.record.Decisions = append(c.record.Decisions, Decision{RecommendationID: "rec", Decision: "approved", DecidedBy: by,
		ApprovedAmount: &amount})
	c.record.Referral.Status = StatusApproved
}

func register(c *caseData) {
	c.loan = &LedgerLoan{ID: "loan", Approved: ruleAmount, Requested: ruleAmount}
	c.hasAllocation, c.purposePlanned, c.hasBaseline = true, ruleAmount, true
}

// disburse posts the full amount and the agreed schedule to the case's book.
func disburse(t *testing.T, c *caseData) {
	t.Helper()
	terms, err := c.record.Recommendations[0].Terms()
	if err != nil {
		t.Fatal(err)
	}
	schedule, err := ledger.BuildSchedule(terms)
	if err != nil {
		t.Fatal(err)
	}
	for index := range schedule {
		schedule[index].ID = "inst" + strconv.Itoa(index+1)
	}
	c.book = ledger.Book{Disbursements: []ledger.Disbursement{{ID: "d1", Amount: ruleAmount, ValueDate: ruleDay, Reference: "DSB"}},
		Installments: schedule, ScheduleVersion: 1}
	c.record.Referral.Status = StatusDisbursed
	c.position = c.book.Position(c.today, dueWindowDays)
}

// pay posts a verified payment allocated in the default order.
func pay(c *caseData, id string, amount ledger.Money) ledger.Money {
	far := time.Date(9999, 1, 1, 0, 0, 0, 0, time.UTC)
	allocations, excess := ledger.Allocate(amount, c.book.Installments, c.book.AllocatedAsOf(far), ledger.DefaultOrder)
	c.book.Payments = append(c.book.Payments, ledger.Payment{ID: id, Kind: ledger.KindPayment, Amount: amount - excess,
		ValueDate: c.today, Reference: id, Allocations: allocations})
	c.position = c.book.Position(c.today, dueWindowDays)
	return excess
}

func TestStageFollowsTheCaseRecords(t *testing.T) {
	steps := []struct {
		name  string
		setUp func(c *caseData)
		want  string
	}{
		{"nobody assigned", func(c *caseData) {
			c.record = CaseRecord{Referral: c.record.Referral}
		}, StageUnassigned},
		{"assigned, not yet reached", func(c *caseData) {
			c.record = CaseRecord{Referral: c.record.Referral, Assignment: c.record.Assignment}
		}, StageContactPending},
		{"reached, assessing", func(c *caseData) {
			c.record.Recommendations, c.record.Agreements = nil, nil
		}, StageAssessment},
		{"terms sent, not accepted", func(c *caseData) { c.record.Agreements[0].Status = "issued" }, StageAwaitingAgreement},
		{"terms accepted", func(c *caseData) {}, StageAwaitingCredit},
		{"approved, not in the ledger", func(c *caseData) { approve(c, "appr") }, StageApproved},
		{"registered in the ledger", func(c *caseData) { approve(c, "appr"); register(c) }, StageAwaitingDisbursement},
		{"declined", func(c *caseData) {
			c.record.Decisions = []Decision{{Decision: "declined"}}
		}, StageDeclined},
		{"closed", func(c *caseData) { c.record.ClosureStatus = "closed" }, StageClosed},
		{"tracked as disbursed before this workflow", func(c *caseData) {
			c.record = CaseRecord{Referral: c.record.Referral}
			c.record.Referral.Status = StatusDisbursed
		}, StageActive},
	}
	for _, step := range steps {
		t.Run(step.name, func(t *testing.T) {
			c := newCase(t)
			step.setUp(c)
			if got := c.stage(); got != step.want {
				t.Fatalf("stage %q, want %q", got, step.want)
			}
		})
	}
}

func TestStageAfterMoneyFollowsTheLedger(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	disburse(t, c)
	if c.stage() != StageActive {
		t.Fatalf("after disbursement: %q", c.stage())
	}
	c.record.Collateral = []Collateral{{ID: "col", Status: "accepted", Description: "Land title"}}
	pay(c, "p1", c.position.TotalOutstanding)
	if c.stage() != StageSettledPending {
		t.Fatalf("settled with security still held: %q, want %q", c.stage(), StageSettledPending)
	}
	c.record.Collateral[0].Status = "released"
	if c.stage() != StageActive || !c.settled() {
		t.Fatalf("settled with security returned: stage %q settled %v", c.stage(), c.settled())
	}
}

func TestTheRecommendingOfficerCannotApprove(t *testing.T) {
	c := newCase(t)
	if offered(c, lenderStaff("off", RoleLoanOfficer, RoleCreditApprover))["decide"] {
		t.Fatal("the officer who recommended the loan was offered the credit decision")
	}
	if !offered(c, lenderStaff("appr", RoleCreditApprover))["decide"] {
		t.Fatal("another credit approver was not offered the decision")
	}
	if offered(c, lenderStaff("other", RoleLoanOfficer))["decide"] {
		t.Fatal("a loan officer without the approver role was offered the decision")
	}
}

func TestTheApproverCannotDisburse(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	if offered(c, lenderStaff("appr", RoleCreditApprover, RoleFinance))["record_disbursement"] {
		t.Fatal("the approver was offered the disbursement")
	}
	if !offered(c, lenderStaff("fin", RoleFinance))["record_disbursement"] {
		t.Fatal("a finance officer was not offered the disbursement")
	}
	c.hasBaseline = false
	got := offered(c, lenderStaff("fin", RoleFinance))
	if got["record_disbursement"] || !got["prepare_disbursement"] {
		t.Fatalf("without the ledger's enrolment baseline: %v", got)
	}
	c.hasBaseline, c.hasAllocation = true, false
	if offered(c, lenderStaff("fin", RoleFinance))["record_disbursement"] {
		t.Fatal("the disbursement was offered before the facility reservation")
	}
}

func TestDisbursementRefusesItsOwnMistakesBeforeTheLedger(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	run := actionNamed(t, "record_disbursement").run
	fin := lenderStaff("fin", RoleFinance)
	cases := map[string]map[string]string{
		"more than approved":      {"amount": "30,000,001", "disbursed_on": "2026-11-10"},
		"before the application":  {"amount": "30,000,000", "disbursed_on": "2026-10-01"},
		"in the future":           {"amount": "30,000,000", "disbursed_on": "2026-11-12"},
		"no evidence of transfer": {"amount": "30,000,000", "disbursed_on": "2026-11-10", "method": "bank", "reference": "r", "bank_reference": "b", "recipient": "s"},
	}
	for name, values := range cases {
		t.Run(name, func(t *testing.T) {
			// A nil ledger and store: any posting attempt would panic.
			_, err := run(context.Background(), &Lending{}, c, fin, actionInput{values: values, today: c.today})
			var field *FieldError
			if !errors.As(err, &field) {
				t.Fatalf("got %v, want a refusal", err)
			}
		})
	}
}

func TestApprovalNeedsTheAgreedAmountAndAcceptedSecurity(t *testing.T) {
	approver := lenderStaff("appr", RoleCreditApprover)
	run := actionNamed(t, "decide").run
	tries := []struct {
		name   string
		values map[string]string
		setUp  func(c *caseData)
	}{
		{"a different amount", map[string]string{"decision": "approved", "approved_amount": "25,000,000", "conditions": "true", "rationale": "r"}, nil},
		{"conditions not confirmed", map[string]string{"decision": "approved", "approved_amount": "30,000,000", "rationale": "r"}, nil},
		{"security not yet accepted", map[string]string{"decision": "approved", "approved_amount": "30,000,000", "conditions": "true", "rationale": "r"},
			func(c *caseData) {
				c.record.Collateral = []Collateral{{Description: "Land title", Status: "under_verification"}}
			}},
	}
	for _, try := range tries {
		t.Run(try.name, func(t *testing.T) {
			c := newCase(t)
			if try.setUp != nil {
				try.setUp(c)
			}
			_, err := run(context.Background(), &Lending{}, c, approver, actionInput{values: try.values, today: c.today})
			var field *FieldError
			if !errors.As(err, &field) {
				t.Fatalf("got %v, want a refusal", err)
			}
		})
	}
}

func TestNobodyVerifiesAPaymentTheyRecorded(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	disburse(t, c)
	c.record.Evidence = []Evidence{{ID: "ev", Status: "verification_pending", SubmittedBy: "fin", Amount: ledger.Shillings(1_000_000)}}
	if offered(c, lenderStaff("fin", RoleFinance))["verify_payment"] {
		t.Fatal("the person who recorded the payment was offered its verification")
	}
	if !offered(c, lenderStaff("fin2", RoleFinance))["verify_payment"] {
		t.Fatal("another finance officer was not offered the verification")
	}
	if offered(c, lenderStaff("col", RoleCollections))["verify_payment"] {
		t.Fatal("a collections officer was offered verification")
	}
	_, err := actionNamed(t, "verify_payment").run(context.Background(), &Lending{}, c, lenderStaff("fin", RoleFinance),
		actionInput{values: map[string]string{"payment": "ev", "decision": "verify"}, today: c.today})
	var field *FieldError
	if !errors.As(err, &field) {
		t.Fatalf("self-verification ran: %v", err)
	}
}

func TestPendingReceiptsNeverMoveTheBalance(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	disburse(t, c)
	before := c.position
	c.record.Evidence = []Evidence{{ID: "ev", Status: "verification_pending", Amount: ledger.Shillings(5_000_000)},
		{ID: "ev2", Status: "rejected", Amount: ledger.Shillings(2_000_000)}}
	after := c.book.Position(c.today, dueWindowDays)
	if after.TotalOutstanding != before.TotalOutstanding || after.TotalVerifiedRepayments != 0 {
		t.Fatalf("receipts moved the balance: %s -> %s", before.TotalOutstanding, after.TotalOutstanding)
	}
	pay(c, "p1", ledger.Shillings(5_000_000))
	if c.position.TotalOutstanding != before.TotalOutstanding-ledger.Shillings(5_000_000) {
		t.Fatalf("a verified payment did not reduce the balance: %s", c.position.TotalOutstanding)
	}
}

func TestOnlyAnAdministratorWithFinanceReverses(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	disburse(t, c)
	pay(c, "p1", ledger.Shillings(5_000_000))
	if offered(c, lenderStaff("fin", RoleFinance))["reverse_payment"] {
		t.Fatal("a finance officer who is not the administrator was offered a reversal")
	}
	if !offered(c, lenderStaff("adm", RoleFinance, RoleAdministrator))["reverse_payment"] {
		t.Fatal("the administrator with finance duties was not offered the reversal")
	}
	c.book.Payments = append(c.book.Payments, ledger.Payment{ID: "r1", Kind: ledger.KindReversal, ReversalOf: "p1", ValueDate: c.today})
	if len(reversibleChoices(c)) != 0 {
		t.Fatal("a reversed payment was offered for reversal again")
	}
}

func TestClosingNeedsSettlementReleasedSecurityAndASettledOverpayment(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	disburse(t, c)
	run := actionNamed(t, "close_loan").run
	admin := lenderStaff("adm", RoleAdministrator)
	refused := func(why string, values map[string]string) {
		t.Helper()
		_, err := run(context.Background(), &Lending{}, c, admin, actionInput{values: values, today: c.today})
		var field *FieldError
		if !errors.As(err, &field) {
			t.Fatalf("%s: closing was not refused (%v)", why, err)
		}
	}
	note := map[string]string{"note": "done"}
	refused("money outstanding", note)
	excess := pay(c, "p1", c.position.TotalOutstanding+ledger.Shillings(200_000))
	if excess != ledger.Shillings(200_000) {
		t.Fatalf("overpayment %s, want UGX 200,000 kept aside", excess)
	}
	c.record.Evidence = []Evidence{{ID: "ev", Status: "verified", Excess: excess}, {ID: "ev2", Status: "verification_pending"}}
	refused("a payment awaiting verification", map[string]string{"note": "done", "overpayment_settled": "true"})
	c.record.Evidence = c.record.Evidence[:1]
	c.record.Collateral = []Collateral{{Description: "Land title", Status: "release_pending"}}
	refused("security still held", map[string]string{"note": "done", "overpayment_settled": "true"})
	c.record.Collateral[0].Status = "released"
	refused("the overpayment not confirmed as settled", note)
}

func TestSecurityIsReleasedOnlyAfterSettlement(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	disburse(t, c)
	c.record.Collateral = []Collateral{{ID: "col", Status: "accepted", Description: "Land title"}}
	fin := lenderStaff("fin", RoleFinance)
	for _, move := range collateralMovesFor(c, fin) {
		if strings.HasSuffix(move.Value, "|release_pending") {
			t.Fatal("release was offered while money is outstanding")
		}
	}
	pay(c, "p1", c.position.TotalOutstanding)
	found := false
	for _, move := range collateralMovesFor(c, fin) {
		found = found || move.Value == "col|release_pending"
	}
	if !found {
		t.Fatal("release was not offered once settled")
	}
	for _, move := range collateralMovesFor(c, lenderStaff("off", RoleLoanOfficer)) {
		if strings.Contains(move.Value, "release") {
			t.Fatal("a loan officer was offered the release")
		}
	}
}

func TestAffordabilityKeepsACushionAndNeverAssumesAllFees(t *testing.T) {
	terms := ledger.Terms{Principal: ruleAmount, Rate: ledger.Rate{PPM: 30_000}, Method: ledger.MethodDeclining, DueDates: ruleDueDays}
	schedule, err := ledger.BuildSchedule(terms)
	if err != nil {
		t.Fatal(err)
	}
	w := Worksheet(ledger.Shillings(42_000_000), ledger.Shillings(30_000_000), 0, 20, schedule)
	if w.Available != ledger.Shillings(12_000_000) || w.Capacity != ledger.Shillings(9_600_000) {
		t.Fatalf("available %s capacity %s", w.Available, w.Capacity)
	}
	if w.LargestInstallment != ledger.Shillings(10_900_000) || w.InstallmentShare != 113 {
		t.Fatalf("largest %s share %d", w.LargestInstallment, w.InstallmentShare)
	}
	if w := Worksheet(ledger.Shillings(10_000_000), ledger.Shillings(12_000_000), 0, 20, schedule); w.Capacity != 0 {
		t.Fatalf("expenses above collections left capacity %s", w.Capacity)
	}
}

func TestPaidAheadIsNeverANegativeDebt(t *testing.T) {
	c := newCase(t)
	approve(c, "appr")
	register(c)
	disburse(t, c)
	pay(c, "p1", c.position.TotalOutstanding)
	if c.position.OwedToday >= 0 {
		t.Fatalf("settling early should leave interest paid ahead, owed today %s", c.position.OwedToday)
	}
	line := owedTodayLine(c.position, "owed", "ahead")
	if line.Label != "ahead" || strings.Contains(line.Value, "-") {
		t.Fatalf("got %q %q", line.Label, line.Value)
	}
	if text := balanceText(ledger.Shillings(-1_800_000)); text != "UGX 1,800,000 paid ahead" {
		t.Fatalf("balance text %q", text)
	}
}

func TestTheStatementPDFIsWellFormed(t *testing.T) {
	data := statementPage{School: "Kasawo (Primary) \\ School", Lender: "Lender", Reference: "EDL-1", AsOf: "11 November 2026",
		Disbursed: true, Status: "Active", Outstanding: "UGX 1", OwedToday: "UGX 1",
		Steps: balanceSteps(ledger.Position{})}
	for i := 0; i < 120; i++ {
		data.Lines = append(data.Lines, statementLine{Date: "1 Jan 2027", Description: "Payment received (verified)", Balance: "UGX 1"})
	}
	pdf := statementPDF(data)
	if !bytes.HasPrefix(pdf, []byte("%PDF-1.4\n")) || !bytes.HasSuffix(pdf, []byte("%%EOF\n")) {
		t.Fatal("not a PDF")
	}
	start := regexp.MustCompile(`startxref\n(\d+)\n`).FindSubmatch(pdf)
	if start == nil {
		t.Fatal("no startxref")
	}
	offset, _ := strconv.Atoi(string(start[1]))
	if !bytes.HasPrefix(pdf[offset:], []byte("xref\n")) {
		t.Fatal("startxref does not point at the cross-reference table")
	}
	entries := regexp.MustCompile(`(\d{10}) 00000 n `).FindAllSubmatch(pdf, -1)
	for index, entry := range entries {
		at, _ := strconv.Atoi(string(entry[1]))
		if !bytes.HasPrefix(pdf[at:], []byte(strconv.Itoa(index+1)+" 0 obj")) {
			t.Fatalf("object %d is not where the table says", index+1)
		}
	}
	if !bytes.Contains(pdf, []byte(`Kasawo \(Primary\) \\ School`)) {
		t.Fatal("brackets and backslashes are not escaped")
	}
	if pages := bytes.Count(pdf, []byte("/Type /Page ")); pages < 2 {
		t.Fatalf("a long statement fit on %d page", pages)
	}
}
