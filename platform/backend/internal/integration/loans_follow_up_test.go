//go:build integration

package integration

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1/loansv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
)

// Staff loan tracking against a real database: a CCEO sees their own
// schools' loans and no amounts, another CCEO sees nothing of them, a PL sees
// them under their team; notifications share one history and cooldown
// across senders, only an authorised person sends inside it, a school's
// daily limit binds everyone, and a payment the school reports moves no balance.

func followUpClient() loansv1connect.LoanFollowUpServiceClient {
	return loansv1connect.NewLoanFollowUpServiceClient(http.DefaultClient, baseURL)
}

func codeOf(err error) connect.Code {
	var connectErr *connect.Error
	if errors.As(err, &connectErr) {
		return connectErr.Code()
	}
	return connect.CodeUnknown
}

func TestStaffFollowTheirSchoolsLoansAndShareOneReminderHistory(t *testing.T) {
	loanFixtures(t)
	ctx := context.Background()
	submit(t, applicationForm(lenderA, "Follow Up Primary", "0772 000 601", "acacacacacacacacacacacacacacacac"))
	appID, reference := applicationByPhone(t, "+256772000601")
	statementLedger(t, appID)

	// The CCEO with a portfolio, a CCEO without one, their PL, and the BTO.
	var cceo, cceoProfile, school string
	if err := admin.QueryRow(ctx, `
SELECT u.id, sp.id, s.id FROM staff_school_assignment a
JOIN staff_profile sp ON sp.id = a.staff_id JOIN "user" u ON u.id = sp.user_id
JOIN school s ON s.id = a.school_id AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
WHERE u.active_role = 'CCEO' ORDER BY s.id LIMIT 1`).Scan(&cceo, &cceoProfile, &school); err != nil {
		t.Fatalf("the test database needs a CCEO with schools: %v", err)
	}
	if _, err := admin.Exec(ctx, `UPDATE school_loans.application SET school_id = $2, school_match_status = 'matched' WHERE id = $1`,
		appID, school); err != nil {
		t.Fatal(err)
	}
	var otherCCEO, lead string
	_ = admin.QueryRow(ctx, `
SELECT u.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.active_role = 'CCEO' AND NOT EXISTS (SELECT 1 FROM staff_school_assignment a WHERE a.staff_id = sp.id AND a.school_id = $1)
LIMIT 1`, school).Scan(&otherCCEO)
	_ = admin.QueryRow(ctx, `
SELECT u.id FROM staff_supervisor_assignment sa JOIN staff_profile sp ON sp.id = sa.supervisor_id JOIN "user" u ON u.id = sp.user_id
WHERE sa.supervisee_id = $1 AND u.active_role = 'Program Lead' LIMIT 1`, cceoProfile).Scan(&lead)
	bto := accountInRole(t, "BusinessTransformationOfficer")
	client := followUpClient()
	as := func(user, role string) string { return token(t, user, role, time.Hour) }

	// 1. The CCEO sees the loan under their schools, without amounts.
	list, err := client.ListPortfolioLoans(ctx, authed(&loansv1.ListPortfolioLoansRequest{}, as(cceo, "CCEO")))
	if err != nil {
		t.Fatal(err)
	}
	var row *loansv1.PortfolioLoanRow
	for _, r := range list.Msg.GetRows() {
		if r.GetReference() == reference {
			row = r
		}
	}
	if row == nil || row.GetStatusLabel() != loans.ShowActive || row.GetRequested() != "" || list.Msg.GetShowsAmounts() {
		t.Fatalf("the CCEO's row: %+v (amounts %v)", row, list.Msg.GetShowsAmounts())
	}
	for _, counter := range list.Msg.GetCounters() {
		if counter.GetKey() == "disbursed" && counter.GetSchools() < 1 {
			t.Fatal("the disbursed counter does not count the school")
		}
	}

	// 2. Another CCEO cannot open it; the PL sees it under their team only.
	if otherCCEO != "" {
		_, err := client.GetLoanProgress(ctx, authed(&loansv1.GetLoanProgressRequest{ApplicationId: appID}, as(otherCCEO, "CCEO")))
		if codeOf(err) != connect.CodeNotFound {
			t.Fatalf("another CCEO opened the loan: %v", err)
		}
	}
	if lead != "" {
		team, err := client.ListPortfolioLoans(ctx, authed(&loansv1.ListPortfolioLoansRequest{Scope: "team"}, as(lead, "Program Lead")))
		if err != nil || !strings.Contains(team.Msg.String(), reference) {
			t.Fatalf("the PL's team view lacks the loan (%v)", err)
		}
	}

	// 3. The BTO sees it with amounts.
	all, err := client.ListPortfolioLoans(ctx, authed(&loansv1.ListPortfolioLoansRequest{Search: reference}, as(bto, "BusinessTransformationOfficer")))
	if err != nil || len(all.Msg.GetRows()) != 1 || all.Msg.GetRows()[0].GetRequested() == "" {
		t.Fatalf("the BTO's view: %v %v", all, err)
	}

	// 4. The CCEO is offered what the loan's state supports, never the lender's own.
	prepared, err := client.PrepareNotification(ctx, authed(&loansv1.PrepareNotificationRequest{ApplicationId: appID}, as(cceo, "CCEO")))
	if err != nil {
		t.Fatal(err)
	}
	offered := map[string]bool{}
	for _, option := range prepared.Msg.GetOptions() {
		offered[option.GetType()] = true
	}
	if !offered[loans.NoteDisbursed] || offered[loans.NoteVerified] || offered[loans.NoteStatement] || offered[loans.NoteAgreement] {
		t.Fatalf("offered to the CCEO: %v", offered)
	}
	if strings.Contains(prepared.Msg.GetRecipientPhone(), "772000601") {
		t.Fatal("the director's full number is shown")
	}

	// 5. One history and cooldown for everyone.
	send := func(user, role, reason string) error {
		_, err := client.SendNotification(ctx, authed(&loansv1.SendNotificationRequest{ApplicationId: appID,
			Type: loans.NoteDisbursed, ExceptionReason: reason}, as(user, role)))
		return err
	}
	if err := send(cceo, "CCEO", ""); err != nil {
		t.Fatalf("the CCEO could not send: %v", err)
	}
	if err := send(cceo, "CCEO", ""); codeOf(err) != connect.CodeInvalidArgument || !strings.Contains(err.Error(), "next may go after") {
		t.Fatalf("a repeat inside the cooldown was not held back: %v", err)
	}
	if err := send(cceo, "CCEO", "school asked again"); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("a CCEO sent inside the cooldown: %v", err)
	}
	if err := send(bto, "BusinessTransformationOfficer", ""); codeOf(err) != connect.CodeInvalidArgument {
		t.Fatalf("the BTO repeated the CCEO's reminder without a reason: %v", err)
	}
	if err := send(bto, "BusinessTransformationOfficer", "Corrected statement link"); err != nil {
		t.Fatalf("the BTO could not send with a reason: %v", err)
	}
	if err := send(bto, "BusinessTransformationOfficer", "Third today"); codeOf(err) != connect.CodeInvalidArgument ||
		!strings.Contains(err.Error(), "in a day") {
		t.Fatalf("the daily limit did not hold: %v", err)
	}
	var queued int
	var body string
	if err := admin.QueryRow(ctx, `SELECT count(*), max(body) FROM school_loans.notification WHERE application_id = $1`, appID).
		Scan(&queued, &body); err != nil || queued != 2 {
		t.Fatalf("%d notifications stored (%v)", queued, err)
	}
	if !strings.Contains(body, "Integration Lender A") || !strings.Contains(body, "/loan/statement?t=") {
		t.Fatalf("the message does not name the lender or carry the secure link: %q", body)
	}

	// 6. A payment the school reports is a note for the lender, not money.
	store := loans.NewStore(gateway)
	_, before, _, err := store.LedgerBook(ctx, statementLoan)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.RecordStaffFollowUp(ctx, authed(&loansv1.RecordStaffFollowUpRequest{ApplicationId: appID, Method: "phone",
		Reason: "payment_discrepancy", Summary: "Director says they paid at the bank.", PaymentReported: true,
		ReportedAmountUgx: 1_000_000, ReportedPaidOn: time.Now().Format("2006-01-02")}, as(cceo, "CCEO"))); err != nil {
		t.Fatal(err)
	}
	_, after, _, err := store.LedgerBook(ctx, statementLoan)
	if err != nil {
		t.Fatal(err)
	}
	today := time.Now()
	if after.Position(today, 14).TotalOutstanding != before.Position(today, 14).TotalOutstanding {
		t.Fatal("a reported payment changed the balance")
	}
	var events int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM school_loans.application_event WHERE application_id = $1 AND kind = 'payment_reported'`,
		appID).Scan(&events); err != nil || events != 1 {
		t.Fatalf("the lender was not told of the reported payment (%d, %v)", events, err)
	}
	progress, err := client.GetLoanProgress(ctx, authed(&loansv1.GetLoanProgressRequest{ApplicationId: appID}, as(cceo, "CCEO")))
	if err != nil {
		t.Fatal(err)
	}
	if len(progress.Msg.GetNotifications()) != 2 || progress.Msg.GetNotifications()[0].GetStatusLabel() == "Delivered" {
		t.Fatal("the history does not show both notifications honestly")
	}
	if progress.Msg.GetAssignedOfficer() != "" {
		t.Fatal("a CCEO was shown the lender's assigned officer")
	}
	if len(progress.Msg.GetFollowUps()) != 1 || !progress.Msg.GetFollowUps()[0].GetPaymentReported() {
		t.Fatal("the follow-up is missing")
	}
}
