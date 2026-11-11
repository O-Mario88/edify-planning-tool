//go:build integration

package integration

import (
	"bytes"
	"context"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
)

// A school's statement without an account, against a real database: the
// private link opens nothing by itself, the code goes only to the director's
// phone, wrong codes run out, the session shows that school's figures alone
// (computed from the existing ledger's rows), a receipt the school sends
// waits for the lender and moves no balance, and every step is logged.

const statementLoan = "itstatementloan1"

// statementLedger gives an application a disbursed loan in the existing
// ledger's tables: 10M paid out yesterday, two installments of 5M plus
// 300,000 interest. Test database only; removed afterwards.
func statementLedger(t *testing.T, applicationID string) {
	t.Helper()
	ctx := context.Background()
	var school, purpose, mfi string
	if err := admin.QueryRow(ctx, `SELECT id FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1`).Scan(&school); err != nil {
		t.Fatal(err)
	}
	if err := admin.QueryRow(ctx, `SELECT id FROM bt_loan_purpose WHERE active ORDER BY id LIMIT 1`).Scan(&purpose); err != nil {
		t.Fatal(err)
	}
	if err := admin.QueryRow(ctx, `SELECT loan_lender_id FROM partner WHERE id = $1`, lenderA).Scan(&mfi); err != nil {
		t.Fatal(err)
	}
	today := time.Now().In(time.FixedZone("EAT", 3*3600))
	paidOut := today.AddDate(0, 0, -1).Format("2006-01-02")
	first, second := today.AddDate(0, 2, 0).Format("2006-01-02"), today.AddDate(0, 5, 0).Format("2006-01-02")
	cleanup := func() {
		for _, statement := range []string{
			`DELETE FROM bt_loan_repayment_installment WHERE loan_id = '` + statementLoan + `'`,
			`DELETE FROM bt_loan_disbursement WHERE loan_id = '` + statementLoan + `'`,
			`DELETE FROM bt_funding_facility_allocation WHERE loan_id = '` + statementLoan + `'`,
			`DELETE FROM bt_mfi_loan WHERE id = '` + statementLoan + `'`,
			`DELETE FROM bt_funding_facility WHERE id = 'itstatementfac1'`,
			`DELETE FROM bt_case WHERE id = 'itstatementcase1'`,
		} {
			_, _ = admin.Exec(context.Background(), statement)
		}
	}
	cleanup()
	t.Cleanup(cleanup)
	for _, statement := range []struct {
		sql  string
		args []any
	}{
		{`INSERT INTO bt_case (created_at, updated_at, source, environment, id, status, opened_fy, triage_decision,
  triage_reason, closure_reason, school_id)
VALUES (now(), now(), 'test', 'test', 'itstatementcase1', 'active', '2027', '', '', '', $1)`, []any{school}},
		{`INSERT INTO bt_funding_facility (created_at, updated_at, id, external_reference, name, country_code, currency,
  commitment_amount, revolving, starts_on, status, agreement_reference, created_by, mfi_id, facility_type, funding_source,
  geographic_restrictions, interest_structure, permitted_purpose_codes, reporting_conditions, school_eligibility_restrictions)
VALUES (now(), now(), 'itstatementfac1', 'IT-FAC', 'Integration facility', 'UG', 'UGX', 100000000, false, '2026-01-01',
  'draft', '', 'test', $1, '', '', '{}', '{}', '[]', '{}', '{}')`, []any{mfi}},
		{`INSERT INTO bt_mfi_loan (created_at, updated_at, source, environment, id, external_loan_reference,
  assigned_officer_reference, currency, repayment_frequency, status, registered_by, purpose_id, school_id, mfi_id, case_id,
  ia_return_reason, ia_validation_status, impact_status, salesforce_confirmation_note, salesforce_return_note,
  salesforce_return_reason, salesforce_status, default_reason, approved_amount, requested_amount)
VALUES (now(), now(), 'test', 'test', $1, 'IT-LOAN-1', '', 'UGX', 'termly', 'processing', 'test', $2, $3, $4,
  'itstatementcase1', '', 'pending', 'pending', '', '', '', 'pending', '', 10000000, 10000000)`,
			[]any{statementLoan, purpose, school, mfi}},
		{`INSERT INTO bt_funding_facility_allocation (created_at, updated_at, id, amount, status, idempotency_key, reserved_by,
  reserved_at, release_reason, facility_id, loan_id, capital_source)
VALUES (now(), now(), 'itstatementalloc1', 10000000, 'reserved', 'it-statement-alloc', 'test', now(), '',
  'itstatementfac1', $1, 'original')`, []any{statementLoan}},
		{`INSERT INTO bt_loan_disbursement (created_at, updated_at, id, sequence, external_reference, idempotency_key, amount,
  disbursed_on, value_date, bank_reference, confirmed_by, confirmed_at, allocation_id, loan_id, capital_source)
VALUES (now(), now(), 'itstatementdisb1', 1, 'IT-DSB-1', 'it-statement-disb', 10000000, $1, $1, '', 'test', now(),
  'itstatementalloc1', $2, 'original')`, []any{paidOut, statementLoan}},
		{`INSERT INTO bt_loan_repayment_installment (created_at, updated_at, id, schedule_version, installment_number,
  due_date, principal_due, interest_due, fee_due, created_by, loan_id)
VALUES (now(), now(), 'itstatementinst1', 1, 1, $1, 5000000, 300000, 0, 'test', $3),
       (now(), now(), 'itstatementinst2', 1, 2, $2, 5000000, 300000, 0, 'test', $3)`, []any{first, second, statementLoan}},
	} {
		if _, err := admin.Exec(ctx, statement.sql, statement.args...); err != nil {
			t.Fatalf("ledger fixture: %v", err)
		}
	}
	if err := loans.NewStore(gateway).SetLedgerLoan(ctx, applicationID, statementLoan, "integration", "Integration"); err != nil {
		t.Fatal(err)
	}
}

func applicationByPhone(t *testing.T, phone string) (id, reference string) {
	t.Helper()
	if err := admin.QueryRow(context.Background(), `SELECT id::text, reference FROM school_loans.application WHERE director_phone = $1`,
		phone).Scan(&id, &reference); err != nil {
		t.Fatal(err)
	}
	return id, reference
}

// schoolClient keeps cookies and never follows redirects.
func schoolClient(t *testing.T) *http.Client {
	t.Helper()
	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	return &http.Client{Jar: jar, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

func fetch(t *testing.T, client *http.Client, method, path string, form url.Values) (*http.Response, string) {
	t.Helper()
	request, err := http.NewRequest(method, baseURL+path, strings.NewReader(form.Encode()))
	if err != nil {
		t.Fatal(err)
	}
	if form != nil {
		request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	request.Header.Set("X-Forwarded-For", testClient(t))
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(response.Body)
	_ = response.Body.Close()
	return response, string(body)
}

var smsCode = regexp.MustCompile(`code is (\d{6})`)

// latestCodeTo is the newest code texted to phone.
func latestCodeTo(t *testing.T, phone string) string {
	t.Helper()
	entries, err := os.ReadDir(smsbox)
	if err != nil {
		t.Fatal(err)
	}
	code := ""
	for _, entry := range entries { // named by time, so the last match is the newest
		raw, err := os.ReadFile(filepath.Join(smsbox, entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(raw), "To: "+phone) {
			if match := smsCode.FindStringSubmatch(string(raw)); match != nil {
				code = match[1]
			}
		}
	}
	if code == "" {
		t.Fatalf("no code was texted to %s", phone)
	}
	return code
}

func TestASchoolOpensOnlyItsOwnStatementWithACode(t *testing.T) {
	loanFixtures(t)
	ctx := context.Background()
	submit(t, applicationForm(lenderA, "Statement Hill School", "0772 000 301", "cccccccccccccccccccccccccccccccc"))
	submit(t, applicationForm(lenderA, "Other Hill School", "0772 000 302", "dddddddddddddddddddddddddddddddd"))
	appA, referenceA := applicationByPhone(t, "+256772000301")
	_, referenceB := applicationByPhone(t, "+256772000302")
	statementLedger(t, appA)
	store := loans.NewStore(gateway)
	token, err := store.IssueSchoolAccess(ctx, appA, "statement", "sms", "+256772000301", "integration", time.Now())
	if err != nil {
		t.Fatal(err)
	}
	school := schoolClient(t)

	// 1. Nothing opens without the link and a code.
	if response, _ := fetch(t, school, http.MethodGet, "/loan/statement/view", nil); response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("the statement opened without a session: %d", response.StatusCode)
	}
	if response, _ := fetch(t, school, http.MethodGet, "/loan/agreement?t="+token, nil); response.StatusCode != http.StatusNotFound {
		t.Fatalf("a statement link opened the agreement page: %d", response.StatusCode)
	}
	response, page := fetch(t, school, http.MethodGet, "/loan/statement?t="+token, nil)
	if response.StatusCode != http.StatusOK || strings.Contains(page, "772000301") || !strings.Contains(page, "••••••301") {
		t.Fatalf("the gate answered %d, or showed the full number", response.StatusCode)
	}
	if strings.Contains(page, "UGX") || strings.Contains(page, referenceA) {
		t.Fatal("the gate page shows loan details before the code")
	}
	if response.Header.Get("Cache-Control") != "no-store" || response.Header.Get("Referrer-Policy") != "no-referrer" {
		t.Fatal("the gate page may be cached or leak its link")
	}

	// 2. The code goes to the director's phone; five wrong tries use it up.
	if response, _ := fetch(t, school, http.MethodPost, "/loan/statement/code", url.Values{"t": {token}}); response.StatusCode != http.StatusOK {
		t.Fatalf("sending a code answered %d", response.StatusCode)
	}
	used := latestCodeTo(t, "+256772000301")
	for try := 0; try < 5; try++ {
		wrong := "000000"
		if used == wrong {
			wrong = "111111"
		}
		if response, _ := fetch(t, school, http.MethodPost, "/loan/statement/verify", url.Values{"t": {token}, "code": {wrong}}); response.StatusCode != http.StatusUnauthorized {
			t.Fatalf("a wrong code answered %d", response.StatusCode)
		}
	}
	if response, _ := fetch(t, school, http.MethodPost, "/loan/statement/verify", url.Values{"t": {token}, "code": {used}}); response.StatusCode != http.StatusUnauthorized {
		t.Fatal("a code still worked after five wrong tries")
	}

	// 3. A new code opens a short, cookie-only session.
	fetch(t, school, http.MethodPost, "/loan/statement/code", url.Values{"t": {token}})
	fresh := latestCodeTo(t, "+256772000301")
	response, _ = fetch(t, school, http.MethodPost, "/loan/statement/verify", url.Values{"t": {token}, "code": {fresh}})
	if response.StatusCode != http.StatusSeeOther || response.Header.Get("Location") != "/loan/statement/view" {
		t.Fatalf("the right code answered %d to %q", response.StatusCode, response.Header.Get("Location"))
	}
	cookie := response.Header.Get("Set-Cookie")
	for _, part := range []string{"HttpOnly", "SameSite=Strict", "Path=/loan", "Max-Age=1800"} {
		if !strings.Contains(cookie, part) {
			t.Fatalf("the session cookie lacks %s: %s", part, cookie)
		}
	}

	// 4. The statement is this school's alone, from the ledger's rows.
	response, page = fetch(t, school, http.MethodGet, "/loan/statement/view", nil)
	if response.StatusCode != http.StatusOK || !strings.Contains(page, referenceA) || strings.Contains(page, referenceB) {
		t.Fatalf("the statement answered %d or showed another school's loan", response.StatusCode)
	}
	if !strings.Contains(page, "UGX 10,600,000") || !strings.Contains(page, "UGX 10,000,000") {
		t.Fatal("the statement does not show 10,000,000 owed today and 10,600,000 outstanding")
	}
	if response.Header.Get("Cache-Control") != "no-store" {
		t.Fatal("the statement may be cached")
	}
	csrf := regexp.MustCompile(`name="csrf" value="([^"]+)"`).FindStringSubmatch(page)
	if csrf == nil {
		t.Fatal("no form token on the statement")
	}

	// 5. A receipt the school sends waits for the lender and moves nothing.
	sendReceipt := func(amount, reference string) *http.Response {
		var body bytes.Buffer
		form := multipart.NewWriter(&body)
		for key, value := range map[string]string{"csrf": csrf[1], "amount": amount, "paid_on": time.Now().Format("2006-01-02"),
			"method": "mobile_money", "reference": reference} {
			_ = form.WriteField(key, value)
		}
		part, _ := form.CreateFormFile("receipt", "receipt.png")
		_, _ = part.Write([]byte("\x89PNG\r\n\x1a\nintegration receipt"))
		_ = form.Close()
		request, _ := http.NewRequest(http.MethodPost, baseURL+"/loan/statement/payment", &body)
		request.Header.Set("Content-Type", form.FormDataContentType())
		request.Header.Set("X-Forwarded-For", testClient(t))
		response, err := school.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		_ = response.Body.Close()
		return response
	}
	if response := sendReceipt("2,000,000", "MTN-IT-1"); response.StatusCode != http.StatusSeeOther {
		t.Fatalf("sending a receipt answered %d", response.StatusCode)
	}
	_, page = fetch(t, school, http.MethodGet, "/loan/statement/view", nil)
	if !strings.Contains(page, "UGX 10,600,000") || !strings.Contains(page, "UGX 2,000,000 you reported is waiting") {
		t.Fatal("a receipt changed the balance, or its waiting status is not shown")
	}
	var source, status string
	if err := admin.QueryRow(ctx, `SELECT source, status FROM school_loans.payment_evidence WHERE application_id = $1`, appA).
		Scan(&source, &status); err != nil || source != "school" || status != "verification_pending" {
		t.Fatalf("the receipt is stored as %s/%s (%v)", source, status, err)
	}
	if response := sendReceipt("3,000,000", "mtn-it-1"); response.StatusCode != http.StatusUnprocessableEntity {
		t.Fatalf("a second payment with the same reference answered %d", response.StatusCode)
	}

	// 6. Forms need the page's token; other documents stay closed.
	if response, _ := fetch(t, school, http.MethodPost, "/loan/statement/request", url.Values{"kind": {"contact"}, "message": {"hi"}}); response.StatusCode != http.StatusForbidden {
		t.Fatalf("a request without the form token answered %d", response.StatusCode)
	}
	if response, _ := fetch(t, school, http.MethodGet, "/loan/statement/receipt/not-a-document", nil); response.StatusCode != http.StatusNotFound {
		t.Fatalf("an unknown document answered %d", response.StatusCode)
	}

	// 7. An expired link opens nothing; every step was logged.
	if _, err := admin.Exec(ctx, `UPDATE school_loans.school_access SET expires_at = now() - interval '1 minute' WHERE application_id = $1`, appA); err != nil {
		t.Fatal(err)
	}
	if response, _ := fetch(t, schoolClient(t), http.MethodGet, "/loan/statement?t="+token, nil); response.StatusCode != http.StatusNotFound {
		t.Fatalf("an expired link answered %d", response.StatusCode)
	}
	rows, err := admin.Query(ctx, `SELECT DISTINCT action FROM school_loans.school_access_log WHERE application_id = $1`, appA)
	if err != nil {
		t.Fatal(err)
	}
	logged := map[string]bool{}
	for rows.Next() {
		var action string
		_ = rows.Scan(&action)
		logged[action] = true
	}
	rows.Close()
	for _, action := range []string{"code_sent", "code_refused", "verified", "statement_viewed", "payment_reported"} {
		if !logged[action] {
			t.Fatalf("%q was not logged (logged: %v)", action, logged)
		}
	}
	var stored int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM school_loans.school_verification WHERE code_hash = $1 OR code_hash = $2`,
		used, fresh).Scan(&stored); err != nil || stored != 0 {
		t.Fatalf("a code is stored in plain text (%d, %v)", stored, err)
	}
}

// A lender-reported loan's existing terms are recorded once, with the signed
// agreement, and read back exactly; a second record is refused.
func TestExistingLoanTermsAreRecordedOnceAndReadBack(t *testing.T) {
	loanFixtures(t)
	ctx := context.Background()
	submit(t, applicationForm(lenderA, "Existing Loan School", "0772 000 401", "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"))
	app, _ := applicationByPhone(t, "+256772000401")
	store := loans.NewStore(gateway)
	document, err := store.StoreDocument(ctx, app, "agreement", "agreement.pdf", []byte("%PDF-1.4\n"), "lender-admin", "lender")
	if err != nil {
		t.Fatal(err)
	}
	due := []time.Time{time.Date(2027, 2, 15, 0, 0, 0, 0, time.UTC), time.Date(2027, 6, 1, 0, 0, 0, 0, time.UTC)}
	terms := loans.ExistingTerms{ExternalReference: "LN-OLD-9", RatePercent: "1.8", Method: "declining_balance",
		Approved: 4_000_000_000, Fee: 50_000, DueDates: due, ApprovedOn: time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC),
		AgreementDocumentID: document, RecordedBy: "lender-admin", RecordedByName: "Lender Admin"}
	if err := store.RecordExistingTerms(ctx, app, terms); err != nil {
		t.Fatal(err)
	}
	if err := store.RecordExistingTerms(ctx, app, terms); err != loans.ErrConflict {
		t.Fatalf("a second record answered %v", err)
	}
	record, err := store.CaseRecord(ctx, app, lenderA)
	if err != nil {
		t.Fatal(err)
	}
	got := record.Existing
	if got == nil || got.Approved != terms.Approved || got.Fee != terms.Fee || got.RatePercent != "1.8" ||
		len(got.DueDates) != 2 || !got.DueDates[1].Equal(due[1]) || got.AgreementDocumentID != document || got.RecordedBy != "lender-admin" {
		t.Fatalf("read back %+v", got)
	}
}
