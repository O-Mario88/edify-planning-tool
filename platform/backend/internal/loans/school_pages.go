package loans

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// The school's pages, with no account: a director opens the private link
// their lender sent, a one-time code goes to the phone or email the link was
// sent to, and the short session that follows shows that one school's
// statement or proposed terms and nothing else. Every opening is logged.

const (
	schoolCookiePrefix = "edify_school_"
	maxReceiptBytes    = 5 << 20
)

// RegisterSchool adds the school's statement and agreement pages to mux.
func (p *Public) RegisterSchool(mux *http.ServeMux, lending *Lending) {
	s := &schoolPages{Public: p, lending: lending}
	for _, purpose := range []string{"statement", "agreement"} {
		mux.HandleFunc("GET /loan/"+purpose, s.open(purpose))
		mux.HandleFunc("POST /loan/"+purpose+"/code", s.sendCode(purpose))
		mux.HandleFunc("POST /loan/"+purpose+"/verify", s.verify(purpose))
		mux.HandleFunc("POST /loan/"+purpose+"/sign-out", s.signOut(purpose))
	}
	mux.HandleFunc("GET /loan/statement/view", s.statement)
	mux.HandleFunc("GET /loan/statement/pdf", s.statementPDF)
	mux.HandleFunc("GET /loan/statement/receipt/{document}", s.receipt)
	mux.HandleFunc("POST /loan/statement/request", s.request)
	mux.HandleFunc("POST /loan/statement/payment", s.reportPayment)
	mux.HandleFunc("GET "+trackPath, s.trackForm)
	mux.HandleFunc("POST "+trackPath+"/code", s.trackCode)
	mux.HandleFunc("POST "+trackPath+"/verify", s.trackVerify)
	mux.HandleFunc("GET "+trackPath+"/view", s.trackView)
	mux.HandleFunc("POST "+trackPath+"/sign-out", s.trackSignOut)
	mux.HandleFunc("GET /loan/agreement/view", s.agreement)
	mux.HandleFunc("POST /loan/agreement/respond", s.respond)
}

type schoolPages struct {
	*Public
	lending *Lending
}

// schoolHeaders: a school's figures are never cached and its link never
// leaks through a referrer.
func schoolHeaders(writer http.ResponseWriter) {
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("Referrer-Policy", "no-referrer")
}

func (s *schoolPages) page(title, heading string) page {
	return page{Title: title, Eyebrow: "Your school loan", Heading: heading, Version: s.version}
}

func (s *schoolPages) expired(writer http.ResponseWriter) {
	s.message(writer, http.StatusNotFound, "This link has expired",
		"This link has expired or is not valid. Ask your lender to send you a new one.")
}

func (s *schoolPages) session(request *http.Request, purpose string) (SchoolSession, bool) {
	cookie, err := request.Cookie(schoolCookiePrefix + purpose)
	if err != nil || cookie.Value == "" {
		return SchoolSession{}, false
	}
	session, err := s.store.schoolSessionByToken(request.Context(), HashToken(cookie.Value), purpose, s.now())
	return session, err == nil
}

func (s *schoolPages) log(request *http.Request, applicationID, sessionID, action string) {
	if err := s.store.LogSchoolAccess(request.Context(), applicationID, sessionID, action, s.clientKey(request)); err != nil {
		s.logger.Error("loans: logging school access", slog.String("error", err.Error()))
	}
}

type schoolGate struct {
	page
	Purpose, Token, Destination, Problem string
	ByPhone, CodeSent                    bool
}

func maskedDestination(access SchoolAccess) string {
	if access.Channel == "email" {
		return maskEmail(access.Destination)
	}
	return maskPhone(access.Destination)
}

func (s *schoolPages) gate(access SchoolAccess, purpose, token string) schoolGate {
	heading := "Open your loan statement"
	if purpose == "agreement" {
		heading = "Review your proposed loan terms"
	}
	return schoolGate{page: s.page(heading, heading), Purpose: purpose, Token: token,
		Destination: maskedDestination(access), ByPhone: access.Channel != "email"}
}

func (s *schoolPages) open(purpose string) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		schoolHeaders(writer)
		if !s.limits.Allow("school:"+s.clientKey(request), pageViewsPerMinute, time.Minute) {
			s.tooMany(writer)
			return
		}
		token := request.URL.Query().Get("t")
		if token == "" {
			if _, ok := s.session(request, purpose); ok {
				http.Redirect(writer, request, "/loan/"+purpose+"/view", http.StatusSeeOther)
				return
			}
			s.message(writer, http.StatusUnauthorized, "Open the link your lender sent",
				"Your statement opens from the private link in the message your lender sent. Your session may have ended: open the link again.")
			return
		}
		access, err := s.store.schoolAccessByToken(request.Context(), HashToken(token), purpose, s.now())
		if err != nil {
			s.expired(writer)
			return
		}
		if session, ok := s.session(request, purpose); ok && session.AccessID == access.ID {
			http.Redirect(writer, request, "/loan/"+purpose+"/view", http.StatusSeeOther)
			return
		}
		s.render(writer, http.StatusOK, "school_gate.html", s.gate(access, purpose, token))
	}
}

// deliverCode sends a code to the destination the link was sent to. The
// code is never stored in plain text, nor kept in the message log.
func (s *schoolPages) deliverCode(ctx context.Context, access SchoolAccess, code string) error {
	body := "Your Edify school loan code is " + code + ". It works for 10 minutes. Do not share it."
	if access.Channel == "email" {
		if s.lending.mailer == nil {
			return ErrNoSMS
		}
		_, err := s.lending.mailer.Send(ctx, Message{To: access.Destination, Subject: "Your school loan code: " + code,
			Text: body + "\n\nIf you did not ask for it, ignore this email.\n\nEdify School Loans\n"})
		return err
	}
	if s.lending.sms == nil {
		return ErrNoSMS
	}
	_, err := s.lending.sms.Send(ctx, access.Destination, body)
	return err
}

func (s *schoolPages) sendCode(purpose string) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		schoolHeaders(writer)
		if !s.limits.Allow("school-code:"+s.clientKey(request), 6, 10*time.Minute) {
			s.tooMany(writer)
			return
		}
		request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
		_ = request.ParseForm()
		token := request.PostForm.Get("t")
		access, err := s.store.schoolAccessByToken(request.Context(), HashToken(token), purpose, s.now())
		if err != nil {
			s.expired(writer)
			return
		}
		gate := s.gate(access, purpose, token)
		code, err := NewCode()
		if err != nil {
			s.unavailable(writer, err)
			return
		}
		switch err := s.store.newSchoolCode(request.Context(), access, code, s.now()); {
		case errors.Is(err, ErrCodeRefused):
			gate.Problem, gate.CodeSent = "Several codes were sent in the last few minutes. Use the newest one, or wait ten minutes.", true
			s.render(writer, http.StatusTooManyRequests, "school_gate.html", gate)
			return
		case err != nil:
			s.unavailable(writer, err)
			return
		}
		if err := s.deliverCode(request.Context(), access, code); err != nil {
			s.logger.Error("loans: sending a school code", slog.String("error", err.Error()))
			gate.Problem = "The code could not be sent just now. Please try again in a few minutes, or ask your lender."
			s.render(writer, http.StatusServiceUnavailable, "school_gate.html", gate)
			return
		}
		s.log(request, access.ApplicationID, "", "code_sent")
		gate.CodeSent = true
		s.render(writer, http.StatusOK, "school_gate.html", gate)
	}
}

func (s *schoolPages) verify(purpose string) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		schoolHeaders(writer)
		if !s.limits.Allow("school-verify:"+s.clientKey(request), 20, 10*time.Minute) {
			s.tooMany(writer)
			return
		}
		request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
		_ = request.ParseForm()
		token := request.PostForm.Get("t")
		access, err := s.store.schoolAccessByToken(request.Context(), HashToken(token), purpose, s.now())
		if err != nil {
			s.expired(writer)
			return
		}
		code := strings.TrimSpace(strings.ReplaceAll(request.PostForm.Get("code"), " ", ""))
		sessionToken, err := s.store.checkSchoolCode(request.Context(), access, code, s.now())
		if err != nil {
			if !errors.Is(err, ErrCodeRefused) {
				s.unavailable(writer, err)
				return
			}
			s.log(request, access.ApplicationID, "", "code_refused")
			gate := s.gate(access, purpose, token)
			gate.CodeSent, gate.Problem = true, "That code is not right, or it has expired. Check the newest message, or send a new code."
			s.render(writer, http.StatusUnauthorized, "school_gate.html", gate)
			return
		}
		http.SetCookie(writer, &http.Cookie{Name: schoolCookiePrefix + purpose, Value: sessionToken, Path: "/loan",
			HttpOnly: true, Secure: request.TLS != nil || strings.HasPrefix(s.cfg.PublicBaseURL, "https://"),
			SameSite: http.SameSiteStrictMode, MaxAge: int(schoolSessionLifetime.Seconds())})
		s.log(request, access.ApplicationID, "", "verified")
		http.Redirect(writer, request, "/loan/"+purpose+"/view", http.StatusSeeOther)
	}
}

func (s *schoolPages) signOut(purpose string) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		schoolHeaders(writer)
		request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
		_ = request.ParseForm()
		if session, ok := s.session(request, purpose); ok && s.keys.ValidCSRF(session.ID, request.PostForm.Get("csrf")) {
			if err := s.store.EndSchoolSession(request.Context(), session.ID, s.now()); err != nil {
				s.logger.Error("loans: ending a school session", slog.String("error", err.Error()))
			}
			s.log(request, session.ApplicationID, session.ID, "signed_out")
		}
		http.SetCookie(writer, &http.Cookie{Name: schoolCookiePrefix + purpose, Value: "", Path: "/loan", HttpOnly: true, MaxAge: -1})
		s.message(writer, http.StatusOK, "You have signed out", "To see it again, open the link your lender sent.")
	}
}

// signedIn is the start of every page behind the code: the session, or the
// way back to the link.
func (s *schoolPages) signedIn(writer http.ResponseWriter, request *http.Request, purpose string) (SchoolSession, bool) {
	schoolHeaders(writer)
	if !s.limits.Allow("school:"+s.clientKey(request), pageViewsPerMinute, time.Minute) {
		s.tooMany(writer)
		return SchoolSession{}, false
	}
	session, ok := s.session(request, purpose)
	if !ok {
		s.message(writer, http.StatusUnauthorized, "Your session has ended",
			"For your school's privacy, sessions end after 30 minutes. Open the link your lender sent to continue.")
	}
	return session, ok
}

func (s *schoolPages) caseFor(writer http.ResponseWriter, request *http.Request, session SchoolSession) (*caseData, bool) {
	c, err := s.lending.load(request.Context(), session.ApplicationID, viewer{})
	if err != nil {
		s.unavailable(writer, err)
		return nil, false
	}
	return c, true
}

// Statement page data, already worded for the school.
type statementStep struct {
	Label, Value string
	Total        bool
}

type statementInstallment struct {
	Number                                                int
	Due, Principal, Interest, Fee, Total, Paid, Remaining string
	Status, Tone                                          string
}

type statementLine struct {
	Date, Description, Reference, Charged, Paid, Balance string
}

type statementPayment struct {
	PaidOn, Amount, Method, Reference, Status, Tone, Note, DocumentID string
}

type statementPage struct {
	page
	CSRF, School, EdifySchoolID, Lender, Reference, AsOf string
	Disbursed                                            bool
	Status, StatusTone, Outstanding, OwedToday           string
	Overdue, NextDue                                     string
	Steps                                                []statementStep
	Installments                                         []statementInstallment
	Lines                                                []statementLine
	Payments                                             []statementPayment
	Pending                                              string
	Requests                                             []SchoolRequest
	Problem, Done, Field                                 string
	Today                                                string
	PaymentMethods                                       []Option
	SessionMinutes                                       int
}

func balanceSteps(p ledger.Position) []statementStep {
	return []statementStep{
		{"Loan amount disbursed to the school", ugx(p.NetDisbursed), false},
		{"Interest in your agreed schedule", "+ " + ugx(p.InterestScheduled), false},
		{"Fees in your agreed schedule", "+ " + ugx(p.FeesScheduled), false},
		{"Total to repay", "= " + ugx(p.TotalObligation), true},
		{"Payments your lender has verified", "− " + ugx(p.TotalVerifiedRepayments), false},
		{"Outstanding balance", "= " + ugx(p.TotalOutstanding), true},
		owedTodayStep(p),
		{"of which is interest and fees not yet due", ugx(p.FutureCharges), false},
	}
}

func owedTodayStep(p ledger.Position) statementStep {
	l := owedTodayLine(p, "of which is owed today", "of which you have paid ahead of the due dates")
	return statementStep{Label: l.Label, Value: l.Value}
}

func (s *schoolPages) statementData(c *caseData, session SchoolSession) statementPage {
	r := c.record.Referral
	data := statementPage{page: s.page("Your loan statement", "Your loan statement"), CSRF: s.keys.CSRFToken(session.ID),
		School: r.SchoolName, EdifySchoolID: r.EdifySchoolID, Lender: r.LenderName, Reference: r.Reference,
		AsOf: longDay(s.now()), Disbursed: c.disbursed(), Requests: c.record.Requests, Today: c.today.Format("2006-01-02"),
		PaymentMethods: paymentMethods, SessionMinutes: int(schoolSessionLifetime.Minutes())}
	if !c.disbursed() {
		return data
	}
	p := c.position
	data.Status, data.StatusTone = ledger.Label(p.Status), servicingTone(p.Status)
	data.Outstanding, data.OwedToday, data.Steps = ugx(p.TotalOutstanding), ugx(max(p.OwedToday, 0)), balanceSteps(p)
	if p.AmountOverdue > 0 {
		data.Overdue = fmt.Sprintf("%s overdue (%d days past due)", ugx(p.AmountOverdue), p.DaysPastDue)
	}
	if p.NextDue != nil {
		data.NextDue = fmt.Sprintf("%s due on %s", ugx(p.NextDue.Remaining), longDay(p.NextDue.DueDate))
	}
	for _, i := range p.Installments {
		data.Installments = append(data.Installments, statementInstallment{Number: i.Number, Due: day(i.DueDate),
			Principal: ugx(i.Principal), Interest: ugx(i.Interest), Fee: ugx(i.Fee), Total: ugx(i.Total()), Paid: ugx(i.Paid),
			Remaining: ugx(i.Remaining), Status: installmentLabels[i.Status], Tone: installmentTones[i.Status]})
	}
	for _, entry := range c.book.Statement(c.today) {
		l := statementLine{Date: day(entry.Date), Description: entry.Description, Reference: entry.Reference, Balance: balanceText(entry.Balance)}
		if entry.Debit > 0 {
			l.Charged = ugx(entry.Debit)
		}
		if entry.Credit > 0 {
			l.Paid = ugx(entry.Credit)
		}
		data.Lines = append(data.Lines, l)
	}
	var pending ledger.Money
	reversed := c.book.ReversedBy(c.today)
	for _, e := range c.record.Evidence {
		payment := statementPayment{PaidOn: day(e.PaidOn), Amount: ugx(e.Amount), Method: labelOf(paymentMethods, e.Method),
			Reference: e.Reference, Status: evidenceStatusLabels[e.Status]}
		switch e.Status {
		case "verification_pending":
			pending += e.Amount
			payment.Tone, payment.Note = "caution", "Not yet in your balance: your lender is checking it."
		case "verified":
			payment.Tone, payment.DocumentID = "good", e.DocumentID
			if reversed[e.LedgerTransactionID] {
				payment.Status, payment.Tone = "Reversed", "alert"
				payment.Note = "Your lender reversed this payment; it no longer counts towards your balance."
				break
			}
			if e.Excess > 0 {
				payment.Note = ugx(e.Excess) + " was more than the loan owed; your lender will settle it with you."
			}
		case "rejected":
			payment.Tone, payment.Note = "alert", "Not verified: "+e.RejectionReason
		}
		data.Payments = append(data.Payments, payment)
	}
	if pending > 0 {
		data.Pending = ugx(pending)
	}
	return data
}

func (s *schoolPages) statement(writer http.ResponseWriter, request *http.Request) {
	session, ok := s.signedIn(writer, request, "statement")
	if !ok {
		return
	}
	c, ok := s.caseFor(writer, request, session)
	if !ok {
		return
	}
	s.log(request, session.ApplicationID, session.ID, "statement_viewed")
	data := s.statementData(c, session)
	data.Done = map[string]string{"request": "Your request was sent to your lender.",
		"payment": "Your payment was sent to your lender to verify. It is not in your balance until they do."}[request.URL.Query().Get("done")]
	s.render(writer, http.StatusOK, "school_statement.html", data)
}

func (s *schoolPages) statementPDF(writer http.ResponseWriter, request *http.Request) {
	session, ok := s.signedIn(writer, request, "statement")
	if !ok {
		return
	}
	c, ok := s.caseFor(writer, request, session)
	if !ok {
		return
	}
	s.log(request, session.ApplicationID, session.ID, "statement_downloaded")
	data := s.statementData(c, session)
	writer.Header().Set("Content-Type", "application/pdf")
	writer.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="statement-%s-%s.pdf"`, data.Reference, c.today.Format("2006-01-02")))
	_, _ = writer.Write(statementPDF(data))
}

func statementPDF(data statementPage) []byte {
	d := &pdfDoc{}
	d.title("School loan statement")
	d.text(data.School + " | Edify School ID " + data.EdifySchoolID)
	d.text("Lender: " + data.Lender + " | Reference " + data.Reference + " | As of " + data.AsOf)
	d.text(data.Lender + " is the lender. Edify provides the referral and tracking platform and is not the lender.")
	if !data.Disbursed {
		d.heading("No disbursement has been recorded yet.")
		return d.bytes("Edify school loans | " + data.Reference)
	}
	d.heading("Summary")
	d.text("Status: " + data.Status + ". Outstanding balance: " + data.Outstanding + ". Owed today: " + data.OwedToday + ".")
	if data.Overdue != "" {
		d.text("Overdue: " + data.Overdue + ".")
	}
	if data.NextDue != "" {
		d.text("Next installment: " + data.NextDue + ".")
	}
	d.heading("How your balance is calculated")
	for _, step := range data.Steps {
		d.mono(columns([]int{58, -30}, step.Label, step.Value))
	}
	d.text("Only payments your lender has verified count towards the balance.")
	d.heading("Repayment schedule (amounts in UGX)")
	widths := []int{2, 11, -11, -10, -9, -11, -11, -11, 15}
	d.mono(columns(widths, "No", "Due", "Principal", "Interest", "Fees", "Total", "Paid", "Remaining", "Status"))
	for _, i := range data.Installments {
		d.mono(columns(widths, fmt.Sprint(i.Number), i.Due, bare(i.Principal), bare(i.Interest), bare(i.Fee), bare(i.Total),
			bare(i.Paid), bare(i.Remaining), i.Status))
	}
	d.heading("Statement (amounts in UGX)")
	widths = []int{11, 28, 17, -11, -11, -21}
	d.mono(columns(widths, "Date", "Description", "Reference", "Charged", "Paid", "Balance"))
	for _, l := range data.Lines {
		d.mono(columns(widths, l.Date, l.Description, l.Reference, bare(l.Charged), bare(l.Paid), bare(l.Balance)))
	}
	if len(data.Payments) > 0 {
		d.heading("Payments reported (amounts in UGX)")
		widths = []int{11, -11, 18, 24, 22}
		d.mono(columns(widths, "Paid on", "Amount", "Reference", "Method", "Status"))
		for _, p := range data.Payments {
			d.mono(columns(widths, p.PaidOn, bare(p.Amount), p.Reference, p.Method, p.Status))
		}
		if data.Pending != "" {
			d.text(data.Pending + " is waiting for your lender's verification and is not yet in the balance.")
		}
	}
	d.heading("Questions about this statement")
	for _, l := range wrap("If a payment is missing or a figure looks wrong, report it from your statement page or contact "+
		data.Lender+" with your reference "+data.Reference+".", 110) {
		d.text(l)
	}
	return d.bytes("Edify school loans | " + data.Reference + " | generated " + data.AsOf)
}

// bare drops the currency from a formatted amount, for tables headed in UGX.
func bare(amount string) string { return strings.TrimPrefix(amount, "UGX ") }

// receipt is a verified payment's receipt, for its own school only.
func (s *schoolPages) receipt(writer http.ResponseWriter, request *http.Request) {
	session, ok := s.signedIn(writer, request, "statement")
	if !ok {
		return
	}
	c, ok := s.caseFor(writer, request, session)
	if !ok {
		return
	}
	id := request.PathValue("document")
	allowed := false
	for _, e := range c.record.Evidence {
		if e.DocumentID == id && e.DocumentID != "" {
			allowed = true
		}
	}
	if !allowed {
		http.NotFound(writer, request)
		return
	}
	meta, content, err := s.store.Document(request.Context(), session.ApplicationID, id)
	if err != nil {
		http.NotFound(writer, request)
		return
	}
	s.log(request, session.ApplicationID, session.ID, "receipt_downloaded")
	writer.Header().Set("Content-Type", meta.ContentType)
	writer.Header().Set("X-Content-Type-Options", "nosniff")
	writer.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, cleanFileName(meta.FileName)))
	_, _ = writer.Write(content)
}

var requestKinds = []Option{{"discrepancy", "A payment is missing or a figure looks wrong"},
	{"statement_update", "Please send an updated statement"}, {"contact", "Please contact me"},
	{"clarification", "I have a question about my loan"}}

func (s *schoolPages) statementProblem(writer http.ResponseWriter, request *http.Request, session SchoolSession, problem, field string) {
	c, ok := s.caseFor(writer, request, session)
	if !ok {
		return
	}
	data := s.statementData(c, session)
	data.Problem, data.Field = problem, field
	s.render(writer, http.StatusUnprocessableEntity, "school_statement.html", data)
}

func (s *schoolPages) request(writer http.ResponseWriter, request *http.Request) {
	session, ok := s.signedIn(writer, request, "statement")
	if !ok {
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	if err := request.ParseForm(); err != nil || !s.keys.ValidCSRF(session.ID, request.PostForm.Get("csrf")) {
		s.message(writer, http.StatusForbidden, "Please try again", "That form had expired. Open your statement again and resend it.")
		return
	}
	in := actionInput{values: map[string]string{"kind": request.PostForm.Get("kind"), "message": request.PostForm.Get("message")}}
	kind, err := in.choice("kind", "what you need", requestKinds)
	if err == nil {
		var message string
		if message, err = in.text("message", "Your message", true, 2000); err == nil {
			err = s.store.AddSchoolRequest(request.Context(), session.ApplicationID, kind, message)
		}
	}
	var field *FieldError
	if errors.As(err, &field) {
		s.statementProblem(writer, request, session, field.Message, field.Field)
		return
	}
	if err != nil {
		s.unavailable(writer, err)
		return
	}
	s.log(request, session.ApplicationID, session.ID, "request_sent")
	http.Redirect(writer, request, "/loan/statement/view?done=request", http.StatusSeeOther)
}

// reportPayment takes a payment the school made, with its receipt. It is
// recorded as awaiting the lender's verification and changes nothing else.
func (s *schoolPages) reportPayment(writer http.ResponseWriter, request *http.Request) {
	session, ok := s.signedIn(writer, request, "statement")
	if !ok {
		return
	}
	if !s.limits.Allow("school-payment:"+s.clientKey(request), 10, time.Hour) {
		s.tooMany(writer)
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxReceiptBytes+maxFormBytes)
	if err := request.ParseMultipartForm(maxReceiptBytes + maxFormBytes); err != nil ||
		!s.keys.ValidCSRF(session.ID, request.PostFormValue("csrf")) {
		s.message(writer, http.StatusForbidden, "Please try again",
			"That form had expired, or the file was larger than 5 MB. Open your statement again and resend it.")
		return
	}
	c, ok := s.caseFor(writer, request, session)
	if !ok {
		return
	}
	if !c.disbursed() || c.stage() == StageClosed {
		s.statementProblem(writer, request, session, "There is no active loan to record a payment against.", "amount")
		return
	}
	values := map[string]string{}
	for _, key := range []string{"amount", "paid_on", "method", "reference"} {
		values[key] = request.PostFormValue(key)
	}
	in := actionInput{values: values, today: c.today}
	file, header, err := request.FormFile("receipt")
	if err == nil {
		defer func() { _ = file.Close() }()
		if in.file, err = io.ReadAll(io.LimitReader(file, maxReceiptBytes+1)); err != nil {
			s.unavailable(writer, err)
			return
		}
		in.fileName = header.Filename
	}
	if err := s.recordSchoolPayment(request.Context(), c, session, in); err != nil {
		var field *FieldError
		if errors.As(err, &field) {
			s.statementProblem(writer, request, session, field.Message, field.Field)
			return
		}
		s.unavailable(writer, err)
		return
	}
	s.log(request, session.ApplicationID, session.ID, "payment_reported")
	http.Redirect(writer, request, "/loan/statement/view?done=payment", http.StatusSeeOther)
}

func (s *schoolPages) recordSchoolPayment(ctx context.Context, c *caseData, session SchoolSession, in actionInput) error {
	amount, err := in.money("amount", "The amount", true)
	if err != nil {
		return err
	}
	if amount <= 0 {
		return need("amount", "The amount must be more than UGX 0.")
	}
	paidOn, err := in.date("paid_on", "The payment date", true, true)
	if err != nil {
		return err
	}
	method, err := in.choice("method", "how you paid", paymentMethods)
	if err != nil {
		return err
	}
	reference, err := in.text("reference", "The transaction reference", true, 120)
	if err != nil {
		return err
	}
	if len(in.file) == 0 {
		return need("receipt", "Attach your receipt or deposit slip (PDF, JPEG or PNG).")
	}
	if len(in.file) > maxReceiptBytes {
		return need("receipt", "The receipt must be 5 MB or smaller.")
	}
	by := "school:" + session.AccessID
	documentID, err := s.store.StoreDocument(ctx, c.record.Referral.ID, "receipt", in.fileName, in.file, by, "school")
	if err != nil {
		return err
	}
	_, _, err = s.store.SubmitEvidence(ctx, c.record.Referral.ID, Evidence{MFILoanID: c.loan.ID, Amount: amount, PaidOn: *paidOn,
		Method: method, Reference: reference, DocumentID: documentID, Source: "school", SubmittedBy: by,
		SubmittedByName: "The school (verified by code)"}, evidenceKey(c.record.Referral.ID, reference, amount, *paidOn), s.now())
	return err
}

type agreementPage struct {
	page
	CSRF, AgreementID, Hash, Status string
	Terms                           AgreementTerms
	AgreementVersion                int
	Problem                         string
	Responded                       bool
}

func (s *schoolPages) agreementData(c *caseData, session SchoolSession) (agreementPage, bool) {
	a := c.record.LatestAgreement()
	if a == nil {
		return agreementPage{}, false
	}
	return agreementPage{page: s.page("Your proposed loan terms", "Your proposed loan terms"), CSRF: s.keys.CSRFToken(session.ID),
		AgreementID: a.ID, Hash: a.Hash, Status: agreementStatusLabel(a.Status), Terms: a.Terms, AgreementVersion: a.Version,
		Responded: a.Status != "issued"}, true
}

func (s *schoolPages) agreement(writer http.ResponseWriter, request *http.Request) {
	session, ok := s.signedIn(writer, request, "agreement")
	if !ok {
		return
	}
	c, ok := s.caseFor(writer, request, session)
	if !ok {
		return
	}
	data, ok := s.agreementData(c, session)
	if !ok {
		s.message(writer, http.StatusNotFound, "No terms to review", "Your lender has not sent proposed terms yet.")
		return
	}
	s.log(request, session.ApplicationID, session.ID, "agreement_viewed")
	s.render(writer, http.StatusOK, "school_agreement.html", data)
}

var agreementResponses = map[string]string{"accepted": "accepted", "declined": "declined", "clarification_requested": "clarification_requested"}

func (s *schoolPages) respond(writer http.ResponseWriter, request *http.Request) {
	session, ok := s.signedIn(writer, request, "agreement")
	if !ok {
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	if err := request.ParseForm(); err != nil || !s.keys.ValidCSRF(session.ID, request.PostForm.Get("csrf")) {
		s.message(writer, http.StatusForbidden, "Please try again", "That form had expired. Open the terms again and answer once more.")
		return
	}
	c, ok := s.caseFor(writer, request, session)
	if !ok {
		return
	}
	response, known := agreementResponses[request.PostForm.Get("response")]
	note := strings.TrimSpace(request.PostForm.Get("note"))
	problem := ""
	switch {
	case !known:
		problem = "Choose whether you accept, decline or need clarification."
	case response == "accepted" && request.PostForm.Get("confirm") != "yes":
		problem = "Tick the box to confirm you have read the terms and are authorised to accept them for the school."
	case response != "accepted" && note == "":
		problem = "Tell your lender why, or what you need clarified."
	case len([]rune(note)) > 2000:
		problem = "Keep your note to 2,000 characters."
	}
	if problem == "" {
		verification := map[string]string{"channel": session.Channel, "session": session.ID, "network": s.clientKey(request),
			"verified_at": s.now().UTC().Format(time.RFC3339)}
		err := s.store.RespondToAgreement(request.Context(), session.ApplicationID, request.PostForm.Get("agreement"),
			request.PostForm.Get("hash"), response, note, verification, s.now())
		var field *FieldError
		switch {
		case errors.As(err, &field):
			problem = field.Message
		case err != nil:
			s.unavailable(writer, err)
			return
		}
	}
	if problem != "" {
		data, ok := s.agreementData(c, session)
		if !ok {
			s.message(writer, http.StatusNotFound, "No terms to review", "Your lender has not sent proposed terms yet.")
			return
		}
		data.Problem = problem
		s.render(writer, http.StatusUnprocessableEntity, "school_agreement.html", data)
		return
	}
	s.log(request, session.ApplicationID, session.ID, "agreement_"+response)
	s.message(writer, http.StatusOK, "Thank you", map[string]string{
		"accepted":                "You accepted the proposed terms. Your lender now makes its credit decision and will contact you.",
		"declined":                "You declined the proposed terms. Your lender has been told.",
		"clarification_requested": "Your question was sent to your lender. They will contact you.",
	}[response])
}
