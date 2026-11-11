//go:build integration

package integration

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1/loansv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
)

// The School Loan Application Portal against a real database: the public
// form without an account, one application per submit however often it is
// tapped, delivery from the outbox, a failed delivery that keeps the
// application, lenders kept to their own applications, and the gateway's
// role unable to write any existing table.

const (
	lenderA = "itloanpartnera" // the seed's lender with a data-sharing agreement, eligible
	lenderB = "itloanpartnerb" // a second eligible lender
	lenderC = "itloanpartnerc" // a Loan Partner with no receiving address
	mfiB    = "itloanmfib"
)

func loansClient() loansv1connect.LoanReferralServiceClient {
	return loansv1connect.NewLoanReferralServiceClient(http.DefaultClient, baseURL)
}

// loanFixtures adds three Loan Partners to the test database, two of them
// able to receive referrals, and removes them and every portal record
// afterwards (test database only).
func loanFixtures(t *testing.T) {
	t.Helper()
	ctx := context.Background()
	var seedMFI string
	if err := admin.QueryRow(ctx, `SELECT id FROM bt_mfi_organization WHERE data_sharing_agreement_active AND active ORDER BY id LIMIT 1`).
		Scan(&seedMFI); err != nil {
		t.Fatalf("the test database needs an active lender with a data-sharing agreement (demo seed): %v", err)
	}
	statements := []string{
		`INSERT INTO bt_mfi_organization (id, code, name, contact_name, contact_email, contact_phone, active,
  data_sharing_agreement_active, country_code, source, environment, created_at, updated_at)
VALUES ('` + mfiB + `', 'IT-LOAN-B', 'Integration Lender B', '', '', '', true, true, 'UG', 'test', 'test', now(), now())`,
	}
	for _, partner := range []struct{ id, name, mfi string }{
		{lenderA, "Integration Lender A", seedMFI}, {lenderB, "Integration Lender B", mfiB}, {lenderC, "Integration Lender C", ""},
	} {
		mfi := "NULL"
		if partner.mfi != "" {
			mfi = "'" + partner.mfi + "'"
		}
		statements = append(statements, `INSERT INTO partner (id, name, partner_role, loan_lender_id, active_status,
  trains_on, coverage_districts, is_certified, expertise_areas, activity_codes, ssa_interventions, region_names,
  user_setup_status, source, environment, created_at, updated_at)
VALUES ('`+partner.id+`', '`+partner.name+`', 'loan', `+mfi+`, true, '{}', '{}', false, '{}', '{}', '{}', '{}',
  'pending', 'test', 'test', now(), now())`)
	}
	for _, channel := range []struct{ partner, email string }{{lenderA, "loans@lender-a.test"}, {lenderB, "loans@lender-b.test"}} {
		statements = append(statements, `INSERT INTO school_loans.lender_channel (partner_id, referrals_enabled,
  delivery_email, confirmed_email, confirmed_at, description, updated_by)
VALUES ('`+channel.partner+`', true, '`+channel.email+`', '`+channel.email+`', now(), 'Integration lender', 'test')`)
	}
	cleanup := func() {
		ctx := context.Background()
		// Origination and servicing records, newest tables first.
		for _, table := range []string{"tracking_session", "tracking_verification", "share_event", "sms_preference", "sms_message", "school_request", "school_access_log", "school_session",
			"school_verification", "school_access", "payment_evidence_event", "payment_evidence", "document", "collateral_event",
			"collateral", "approval_decision", "agreement_version", "recommendation", "assessment_event", "assessment",
			"contact_log", "assignment", "lender_member_event", "lender_member"} {
			_, _ = admin.Exec(ctx, `DELETE FROM school_loans.`+table)
		}
		for _, table := range []string{"application_event", "follow_up", "delivery_task", "lender_verification"} {
			_, _ = admin.Exec(ctx, `DELETE FROM school_loans.`+table)
		}
		for _, table := range []string{"lender_access", "lender_session", "application", "invitation", "share_link", "share_template",
			"lender_channel_event", "lender_channel"} {
			_, _ = admin.Exec(ctx, `DELETE FROM school_loans.`+table)
		}
		_, _ = admin.Exec(ctx, `DELETE FROM partner WHERE id IN ($1, $2, $3)`, lenderA, lenderB, lenderC)
		_, _ = admin.Exec(ctx, `DELETE FROM bt_mfi_organization WHERE id = $1`, mfiB)
	}
	cleanup()
	t.Cleanup(cleanup)
	for _, statement := range statements {
		if _, err := admin.Exec(ctx, statement); err != nil {
			t.Fatalf("fixture: %v", err)
		}
	}
}

func noRedirects() *http.Client {
	return &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

func applicationForm(partner, school, phone, key string) url.Values {
	return url.Values{
		"school_name": {school}, "director_name": {"Integration Director"}, "director_phone": {phone},
		"district": {"Mukono"}, "sub_county": {"Goma Division"}, "parish": {"Seeta"}, "village": {"Namilyango"},
		"boys": {"120"}, "girls": {"130"}, "fees_collected": {"UGX 9,000,000"}, "purpose": {"school_furniture"},
		"requested": {"12,500,000"}, "partner": {partner}, "consent": {"yes"}, "idempotency_key": {key},
		"religion": {"prefer_not_to_say"},
		"stamp":    {loans.DeriveKeys(signingSecret).FormStamp(time.Now().Add(-30 * time.Second))},
	}
}

func submit(t *testing.T, form url.Values) *http.Response {
	t.Helper()
	request, err := http.NewRequest(http.MethodPost, baseURL+"/loans/apply", strings.NewReader(form.Encode()))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.Header.Set("X-Forwarded-For", testClient(t))
	response, err := noRedirects().Do(request)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = response.Body.Close() })
	return response
}

func countApplications(t *testing.T) int {
	t.Helper()
	var count int
	if err := admin.QueryRow(context.Background(), `SELECT count(*) FROM school_loans.application`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	return count
}

func worker() *loans.Worker {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return loans.NewWorker(loans.NewStore(gateway), loans.NewMailer(config.Loans{DevMailboxDir: mailbox, MailFrom: "loans@edify.test"}),
		publicBaseURL, logger, time.Now)
}

func TestTheLoanPortalFromApplicationToLender(t *testing.T) {
	loanFixtures(t)
	ctx := context.Background()

	// 1. Anyone opens the form: no sign-in, no redirect, only eligible lenders.
	page, err := noRedirects().Get(baseURL + "/loans/apply")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(page.Body)
	_ = page.Body.Close()
	html := string(body)
	if page.StatusCode != http.StatusOK {
		t.Fatalf("the public form answered %d", page.StatusCode)
	}
	if !strings.Contains(html, `value="`+lenderA+`"`) || !strings.Contains(html, `value="`+lenderB+`"`) {
		t.Fatal("the eligible lenders are not offered")
	}
	if strings.Contains(html, `value="`+lenderC+`"`) || strings.Contains(html, "Integration Lender C") {
		t.Fatal("a lender without a receiving address is offered")
	}

	// 2. A double tap is one application, and both answers lead to its receipt.
	form := applicationForm(lenderA, "Integration Hill School", "0772 000 111", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
	first, second := submit(t, form), submit(t, form)
	if first.StatusCode != http.StatusSeeOther || second.StatusCode != http.StatusSeeOther {
		t.Fatalf("submits answered %d and %d", first.StatusCode, second.StatusCode)
	}
	if first.Header.Get("Location") != second.Header.Get("Location") {
		t.Fatal("a repeated submit led to a different receipt")
	}
	if got := countApplications(t); got != 1 {
		t.Fatalf("a double tap stored %d applications", got)
	}

	// 3. The same school, phone and lender with a fresh form is the same
	// application, said so, and not stored again.
	again := submit(t, applicationForm(lenderA, "Integration Hill School", "+256772000111", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
	againBody, _ := io.ReadAll(again.Body)
	if again.StatusCode != http.StatusOK || !strings.Contains(string(againBody), "We already received this application") {
		t.Fatalf("a duplicate answered %d without saying so", again.StatusCode)
	}
	if got := countApplications(t); got != 1 {
		t.Fatalf("a duplicate was stored (%d applications)", got)
	}

	// 4. The stored values are exactly what was typed, with the total computed.
	var total int
	var fees, requested int64
	var approved, disbursed *int64
	var status, delivery string
	if err := admin.QueryRow(ctx, `
SELECT total_enrollment, average_fees_collected_ugx, requested_amount_ugx, approved_amount_ugx,
  disbursed_amount_ugx, status, delivery_status
FROM school_loans.application`).Scan(&total, &fees, &requested, &approved, &disbursed, &status, &delivery); err != nil {
		t.Fatal(err)
	}
	if total != 250 || fees != 9_000_000 || requested != 12_500_000 || approved != nil || disbursed != nil {
		t.Fatalf("stored total %d fees %d requested %d approved %v disbursed %v", total, fees, requested, approved, disbursed)
	}
	if status != loans.StatusSubmitted || delivery != loans.DeliveryQueued {
		t.Fatalf("a new application is %s / %s", status, delivery)
	}

	// 5. The receipt shows the honest state, and a reference opens nothing.
	receipt, err := http.Get(baseURL + first.Header.Get("Location"))
	if err != nil {
		t.Fatal(err)
	}
	receiptBody, _ := io.ReadAll(receipt.Body)
	_ = receipt.Body.Close()
	if !strings.Contains(string(receiptBody), "Waiting to be sent") {
		t.Fatal("the receipt does not say the application is waiting to be sent")
	}
	var reference string
	_ = admin.QueryRow(ctx, `SELECT reference FROM school_loans.application`).Scan(&reference)
	for _, guess := range []string{reference, "not-a-token", ""} {
		response, err := http.Get(baseURL + "/loans/apply/receipt/" + url.PathEscape(guess))
		if err != nil {
			t.Fatal(err)
		}
		_ = response.Body.Close()
		if response.StatusCode != http.StatusNotFound {
			t.Fatalf("receipt token %q answered %d", guess, response.StatusCode)
		}
	}

	// 6. The worker sends the lender a link, never the school's details.
	if _, err := worker().RunOnce(ctx); err != nil {
		t.Fatal(err)
	}
	_ = admin.QueryRow(ctx, `SELECT status, delivery_status FROM school_loans.application`).Scan(&status, &delivery)
	if status != loans.StatusAwaitingReceipt || delivery != loans.DeliverySent {
		t.Fatalf("after sending the application is %s / %s", status, delivery)
	}
	sent := mailTo(t, "loans@lender-a.test")
	if !strings.Contains(sent, reference) || !strings.Contains(sent, "/lender/referrals?t=TOKEN") {
		t.Fatal("the lender's email lacks the reference or the link")
	}
	for _, private := range []string{"Integration Director", "772000111", "9,000,000", "12,500,000"} {
		if strings.Contains(sent, private) {
			t.Fatalf("the lender's email carries %q", private)
		}
	}

	// 7. Lender B never reaches lender A's application.
	var applicationID string
	_ = admin.QueryRow(ctx, `SELECT id FROM school_loans.application`).Scan(&applicationID)
	store := loans.NewStore(gateway)
	_, err = store.Act(ctx, applicationID, loans.Actor{Kind: loans.ActorLender, PartnerID: lenderB}, loans.ActionAcknowledge,
		loans.ActDetails{}, time.Now())
	if !errors.Is(err, loans.ErrNotFound) {
		t.Fatalf("another lender acted on the application: %v", err)
	}
	if _, err := store.ReferralByReference(ctx, reference, lenderB); !errors.Is(err, loans.ErrNotFound) {
		t.Fatalf("another lender read the application: %v", err)
	}

	// 8. A delivery that cannot happen keeps the application and alerts staff.
	submit(t, applicationForm(lenderB, "Integration Valley School", "0772 000 222", "cccccccccccccccccccccccccccccccc"))
	if _, err := admin.Exec(ctx, `UPDATE school_loans.lender_channel SET referrals_enabled = false WHERE partner_id = $1`, lenderB); err != nil {
		t.Fatal(err)
	}
	if _, err := worker().RunOnce(ctx); err != nil {
		t.Fatal(err)
	}
	var failedStatus string
	_ = admin.QueryRow(ctx, `SELECT delivery_status FROM school_loans.application WHERE partner_id = $1`, lenderB).Scan(&failedStatus)
	if failedStatus != loans.DeliveryFailed {
		t.Fatalf("an undeliverable application is %q, not failed", failedStatus)
	}
	var alerts int
	_ = admin.QueryRow(ctx, `SELECT count(*) FROM school_loans.delivery_task WHERE kind = 'staff_alert'`).Scan(&alerts)
	if alerts == 0 {
		t.Fatal("no staff were alerted to the failed delivery")
	}
	if got := countApplications(t); got != 2 {
		t.Fatalf("the undeliverable application was lost (%d applications)", got)
	}

	// 9. The lender's credit decision keeps its own amounts.
	if _, err := store.Act(ctx, applicationID, loans.Actor{Kind: loans.ActorLender, PartnerID: lenderA}, loans.ActionApprove,
		loans.ActDetails{ApprovedAmount: 11_000_000}, time.Now()); err != nil {
		t.Fatal(err)
	}
	_ = admin.QueryRow(ctx, `SELECT approved_amount_ugx, disbursed_amount_ugx, requested_amount_ugx FROM school_loans.application WHERE id = $1`,
		applicationID).Scan(&approved, &disbursed, &requested)
	if approved == nil || *approved != 11_000_000 || disbursed != nil || requested != 12_500_000 {
		t.Fatalf("approved %v disbursed %v requested %d", approved, disbursed, requested)
	}

	// 10. Staff see by role: the RVP without contact details, Admin not at all.
	rvp := accountInRole(t, "RegionalVicePresident")
	list, err := loansClient().ListLoanApplications(ctx, authed(&loansv1.ListLoanApplicationsRequest{}, token(t, rvp, "RegionalVicePresident", time.Hour)))
	if err != nil {
		t.Fatal(err)
	}
	if !list.Msg.GetContactDetailsHidden() || len(list.Msg.GetRows()) != 2 || list.Msg.GetRows()[0].GetDirectorPhone() != "" {
		t.Fatalf("the RVP saw contact details or the wrong rows: %+v", list.Msg)
	}
	adminUser := accountInRole(t, "Admin")
	_, err = loansClient().ListLoanApplications(ctx, authed(&loansv1.ListLoanApplicationsRequest{}, token(t, adminUser, "Admin", time.Hour)))
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Fatalf("Admin reached loan records: %v", err)
	}
}

func TestTheGatewayRoleCannotWriteTheExistingLoanRecords(t *testing.T) {
	ctx := context.Background()
	for _, statement := range []string{
		`UPDATE partner SET name = name WHERE false`,
		`UPDATE bt_mfi_organization SET name = name WHERE false`,
		`INSERT INTO bt_loan_application (id) VALUES ('x')`,
		`UPDATE school SET name = name WHERE false`,
	} {
		tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
		if err != nil {
			t.Fatal(err)
		}
		_, err = tx.Exec(ctx, statement)
		_ = tx.Rollback(ctx)
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "42501" {
			t.Errorf("%q was not refused for lack of privilege: %v", statement, err)
		}
	}
}

var linkToken = regexp.MustCompile(`t=[A-Za-z0-9_-]+`)

// mailTo is the newest message to address in this run's mailbox, with its
// link token replaced by TOKEN.
func mailTo(t *testing.T, address string) string {
	t.Helper()
	entries, err := os.ReadDir(mailbox)
	if err != nil {
		t.Fatal(err)
	}
	newest := ""
	for _, entry := range entries {
		raw, err := os.ReadFile(filepath.Join(mailbox, entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(raw), "To: "+address+"\r\n") {
			newest = string(raw)
		}
	}
	if newest == "" {
		t.Fatalf("no message to %s", address)
	}
	return linkToken.ReplaceAllString(newest, "t=TOKEN")
}

func accountInRole(t *testing.T, role string) string {
	t.Helper()
	var id string
	if err := admin.QueryRow(context.Background(), `
SELECT id FROM "user" WHERE active_role = $1 AND is_active AND deleted_at IS NULL ORDER BY id LIMIT 1`, role).Scan(&id); err != nil {
		t.Fatalf("the test database needs an active %s account (demo seed): %v", role, err)
	}
	return id
}
