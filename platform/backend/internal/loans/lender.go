package loans

import (
	"errors"
	"log/slog"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// The lender pages: how a lending partner without an Edify account opens
// the referrals sent to it. An emailed link names the lender but opens
// nothing by itself; a one-time code sent to the lender's confirmed address
// must be entered first, and the short session that follows reaches only
// that lender's applications. (Lender staff who sign in to Edify use the
// app instead.)

const lenderCookie = "edify_lender"

// RegisterLender adds the lender routes to mux. mailer may be nil.
func (p *Public) RegisterLender(mux *http.ServeMux, mailer Mailer) {
	lender := &lenderPages{Public: p, mailer: mailer}
	mux.HandleFunc("GET /lender/referrals", lender.open)
	mux.HandleFunc("POST /lender/code", lender.sendCode)
	mux.HandleFunc("POST /lender/verify", lender.verify)
	mux.HandleFunc("GET /lender/referrals/{reference}", lender.detail)
	mux.HandleFunc("POST /lender/referrals/{reference}", lender.act)
	mux.HandleFunc("POST /lender/sign-out", lender.signOut)
	mux.HandleFunc("GET /lender/confirm-address", lender.confirmAddressPage)
	mux.HandleFunc("POST /lender/confirm-address", lender.confirmAddress)
}

type lenderPages struct {
	*Public
	mailer Mailer
}

func (l *lenderPages) page(title, heading string) page {
	return page{Title: title, Eyebrow: "Edify lending partners", Heading: heading, Version: l.version, Script: false}
}

func (l *lenderPages) session(request *http.Request) (lenderSession, bool) {
	cookie, err := request.Cookie(lenderCookie)
	if err != nil || cookie.Value == "" {
		return lenderSession{}, false
	}
	session, err := l.store.sessionByToken(request.Context(), HashToken(cookie.Value), l.now())
	return session, err == nil
}

func (l *lenderPages) secureCookies(request *http.Request) bool {
	return request.TLS != nil || strings.HasPrefix(l.cfg.PublicBaseURL, "https://")
}

type lenderGate struct {
	page
	Token, MaskedEmail, Problem string
	CodeSent                    bool
}

// open is where an emailed link lands: the referral list for a signed-in
// lender, or the step that sends a code.
func (l *lenderPages) open(writer http.ResponseWriter, request *http.Request) {
	if !l.limits.Allow("lender:"+l.clientKey(request), pageViewsPerMinute, time.Minute) {
		l.tooMany(writer)
		return
	}
	token := request.URL.Query().Get("t")
	if session, ok := l.session(request); ok && token == "" {
		l.list(writer, request, session)
		return
	}
	if token == "" {
		l.message(writer, http.StatusUnauthorized, "Open the link from your email",
			"Lending partners open referrals from the link in Edify's email. Your session may have ended: open the link again.")
		return
	}
	access, err := l.store.accessByToken(request.Context(), HashToken(token), l.now())
	if err != nil {
		l.message(writer, http.StatusNotFound, "This link has expired",
			"This link has expired or is not valid. Ask Edify to send the referral again.")
		return
	}
	if session, ok := l.session(request); ok && session.PartnerID == access.PartnerID {
		l.toReferral(writer, request, access)
		return
	}
	l.render(writer, http.StatusOK, "lender_gate.html", lenderGate{
		page:  l.page("Open a referral", "Open your school loan referral"),
		Token: token, MaskedEmail: maskEmail(access.Email),
	})
}

func (l *lenderPages) toReferral(writer http.ResponseWriter, request *http.Request, access lenderAccess) {
	target := "/lender/referrals"
	if access.ApplicationID != "" {
		if referral, err := l.store.Referral(request.Context(), access.ApplicationID, access.PartnerID); err == nil {
			target = "/lender/referrals/" + url.PathEscape(referral.Reference)
		}
	}
	http.Redirect(writer, request, target, http.StatusSeeOther)
}

func (l *lenderPages) sendCode(writer http.ResponseWriter, request *http.Request) {
	if !l.limits.Allow("lender-code:"+l.clientKey(request), 6, 10*time.Minute) {
		l.tooMany(writer)
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	_ = request.ParseForm()
	token := request.PostForm.Get("t")
	access, err := l.store.accessByToken(request.Context(), HashToken(token), l.now())
	if err != nil {
		l.message(writer, http.StatusNotFound, "This link has expired",
			"This link has expired or is not valid. Ask Edify to send the referral again.")
		return
	}
	gate := lenderGate{page: l.page("Enter your code", "Enter your code"), Token: token, MaskedEmail: maskEmail(access.Email)}
	if l.mailer == nil {
		gate.Problem = "Edify cannot send codes at the moment. Please try again later."
		l.render(writer, http.StatusServiceUnavailable, "lender_gate.html", gate)
		return
	}
	code, err := NewCode()
	if err != nil {
		l.unavailable(writer, err)
		return
	}
	switch err := l.store.newCode(request.Context(), access, code, l.now()); {
	case errors.Is(err, ErrCodeRefused):
		gate.Problem = "Several codes were sent in the last few minutes. Use the newest one, or wait ten minutes."
		gate.CodeSent = true
		l.render(writer, http.StatusTooManyRequests, "lender_gate.html", gate)
		return
	case err != nil:
		l.unavailable(writer, err)
		return
	}
	if _, err := l.mailer.Send(request.Context(), Message{
		To:      access.Email,
		Subject: "Your Edify code: " + code,
		Text: "Your code to open Edify school loan referrals is " + code + ".\n\n" +
			"It works for 10 minutes. If you did not ask for it, ignore this email.\n\nEdify School Loans\n",
	}); err != nil {
		l.logger.Error("loans: sending a lender code", slog.String("error", err.Error()))
		gate.Problem = "The code could not be sent just now. Please try again in a few minutes."
		l.render(writer, http.StatusServiceUnavailable, "lender_gate.html", gate)
		return
	}
	gate.CodeSent = true
	l.render(writer, http.StatusOK, "lender_gate.html", gate)
}

func (l *lenderPages) verify(writer http.ResponseWriter, request *http.Request) {
	if !l.limits.Allow("lender-verify:"+l.clientKey(request), 20, 10*time.Minute) {
		l.tooMany(writer)
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	_ = request.ParseForm()
	token := request.PostForm.Get("t")
	access, err := l.store.accessByToken(request.Context(), HashToken(token), l.now())
	if err != nil {
		l.message(writer, http.StatusNotFound, "This link has expired",
			"This link has expired or is not valid. Ask Edify to send the referral again.")
		return
	}
	code := strings.TrimSpace(strings.ReplaceAll(request.PostForm.Get("code"), " ", ""))
	sessionToken, err := l.store.checkCode(request.Context(), access, code, l.now())
	if err != nil {
		gate := lenderGate{page: l.page("Enter your code", "Enter your code"), Token: token,
			MaskedEmail: maskEmail(access.Email), CodeSent: true,
			Problem: "That code is not right, or it has expired. Check the newest email, or send a new code."}
		if !errors.Is(err, ErrCodeRefused) {
			l.unavailable(writer, err)
			return
		}
		l.render(writer, http.StatusUnauthorized, "lender_gate.html", gate)
		return
	}
	http.SetCookie(writer, &http.Cookie{
		Name: lenderCookie, Value: sessionToken, Path: "/lender", HttpOnly: true,
		Secure: l.secureCookies(request), SameSite: http.SameSiteLaxMode, MaxAge: int(sessionLifetime.Seconds()),
	})
	l.toReferral(writer, request, access)
}

type lenderListPage struct {
	page
	Lender    string
	Referrals []ReferralSummary
	CSRF      string
}

func (l *lenderPages) list(writer http.ResponseWriter, request *http.Request, session lenderSession) {
	referrals, err := l.store.LenderReferrals(request.Context(), session.PartnerID)
	if err != nil {
		l.unavailable(writer, err)
		return
	}
	l.render(writer, http.StatusOK, "lender_list.html", lenderListPage{
		page:   l.page("Referrals", "School loan referrals for "+session.LenderName),
		Lender: session.LenderName, Referrals: referrals, CSRF: l.keys.CSRFToken(session.ID),
	})
}

type lenderDetailPage struct {
	page
	Referral Referral
	Timeline []Event
	CSRF     string
	Problem  string
	Field    string
	Done     string
	Actions  []string
	Today    string
}

func (l *lenderPages) detail(writer http.ResponseWriter, request *http.Request) {
	session, ok := l.session(request)
	if !ok {
		l.message(writer, http.StatusUnauthorized, "Your session has ended",
			"Open the link from Edify's email again to continue.")
		return
	}
	referral, err := l.store.ReferralByReference(request.Context(), request.PathValue("reference"), session.PartnerID)
	if err != nil {
		l.message(writer, http.StatusNotFound, "Referral not found", "This referral is not addressed to your organisation.")
		return
	}
	actor := Actor{Kind: ActorLender, ID: session.Email, Name: session.LenderName, PartnerID: session.PartnerID}
	if err := l.store.MarkOpened(request.Context(), referral.ID, actor, l.now()); err != nil {
		l.logger.Error("loans: recording a lender opened a referral", slog.String("error", err.Error()))
	}
	l.showDetail(writer, request, session, referral.Reference, "", "", request.URL.Query().Get("done"), http.StatusOK)
}

func (l *lenderPages) showDetail(writer http.ResponseWriter, request *http.Request, session lenderSession, reference, problem, field, done string, status int) {
	referral, err := l.store.ReferralByReference(request.Context(), reference, session.PartnerID)
	if err != nil {
		l.message(writer, http.StatusNotFound, "Referral not found", "This referral is not addressed to your organisation.")
		return
	}
	timeline, err := l.store.Timeline(request.Context(), referral.ID, true)
	if err != nil {
		l.unavailable(writer, err)
		return
	}
	l.render(writer, status, "lender_detail.html", lenderDetailPage{
		page:     l.page(referral.Reference, referral.SchoolName),
		Referral: referral, Timeline: timeline, CSRF: l.keys.CSRFToken(session.ID),
		Problem: problem, Field: field, Done: done, Actions: lenderActionsFor(referral.Status),
		Today: time.Now().In(kampala).Format("2006-01-02"),
	})
}

// lenderActionsFor are the actions a lender may take from status.
func lenderActionsFor(status string) []string {
	var actions []string
	for _, action := range []string{ActionAcknowledge, ActionStartReview, ActionRequestInformation,
		ActionApprove, ActionDecline, ActionDisburse, ActionClose} {
		if _, err := NextStatus(status, action, ActorLender); err == nil {
			actions = append(actions, action)
		}
	}
	return actions
}

func (l *lenderPages) act(writer http.ResponseWriter, request *http.Request) {
	session, ok := l.session(request)
	if !ok {
		l.message(writer, http.StatusUnauthorized, "Your session has ended",
			"Open the link from Edify's email again to continue. Nothing was recorded.")
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	if err := request.ParseForm(); err != nil || !l.keys.ValidCSRF(session.ID, request.PostForm.Get("csrf")) {
		l.message(writer, http.StatusForbidden, "Please try again",
			"This form has expired. Go back, reload the page and try again. Nothing was recorded.")
		return
	}
	reference := request.PathValue("reference")
	referral, err := l.store.ReferralByReference(request.Context(), reference, session.PartnerID)
	if err != nil {
		l.message(writer, http.StatusNotFound, "Referral not found", "This referral is not addressed to your organisation.")
		return
	}
	form := request.PostForm
	actor := Actor{Kind: ActorLender, ID: session.Email, Name: session.LenderName, PartnerID: session.PartnerID}
	action := form.Get("action")
	var done string
	if action == "message" {
		err = l.store.LenderMessage(request.Context(), referral.ID, actor, form.Get("note"))
		done = "Your message was sent to Edify."
	} else {
		details, problem := detailsFromForm(form)
		if problem != nil {
			l.showDetail(writer, request, session, reference, problem.Message, problem.Field, "", http.StatusUnprocessableEntity)
			return
		}
		var to string
		to, err = l.store.Act(request.Context(), referral.ID, actor, action, details, l.now())
		done = "Recorded: " + StatusLabel(to) + "."
	}
	var field *FieldError
	switch {
	case errors.As(err, &field):
		l.showDetail(writer, request, session, reference, field.Message, field.Field, "", http.StatusUnprocessableEntity)
		return
	case err != nil:
		l.unavailable(writer, err)
		return
	}
	http.Redirect(writer, request, "/lender/referrals/"+url.PathEscape(reference)+"?done="+url.QueryEscape(done),
		http.StatusSeeOther)
}

// detailsFromForm reads an action's details as typed by a person.
func detailsFromForm(form url.Values) (ActDetails, *FieldError) {
	details := ActDetails{
		Note:                  strings.TrimSpace(form.Get("note")),
		Evidence:              strings.TrimSpace(form.Get("evidence")),
		DisbursementReference: strings.TrimSpace(form.Get("disbursement_reference")),
		InterestRate:          strings.TrimSpace(form.Get("interest_rate")),
	}
	amount := func(field string) (int64, *FieldError) {
		raw := strings.TrimSpace(form.Get(field))
		if raw == "" {
			return 0, nil
		}
		value, err := ParseUGX(raw)
		if err != nil {
			return 0, &FieldError{Field: field, Message: err.Error()}
		}
		return value, nil
	}
	var problem *FieldError
	if details.ApprovedAmount, problem = amount("approved_amount"); problem != nil {
		return details, problem
	}
	if details.DisbursedAmount, problem = amount("disbursed_amount"); problem != nil {
		return details, problem
	}
	if raw := strings.TrimSpace(form.Get("disbursement_date")); raw != "" {
		day, err := time.ParseInLocation("2006-01-02", raw, kampala)
		if err != nil {
			return details, &FieldError{Field: "disbursement_date", Message: "Enter the date as shown, such as 2026-11-11."}
		}
		details.DisbursementDate = day
	}
	if raw := strings.TrimSpace(form.Get("term_months")); raw != "" {
		months, err := strconv.Atoi(raw)
		if err != nil || months < 1 || months > 240 {
			return details, &FieldError{Field: "term_months", Message: "Enter a term from 1 to 240 months."}
		}
		details.TermMonths = months
	}
	return details, nil
}

func (l *lenderPages) signOut(writer http.ResponseWriter, request *http.Request) {
	if session, ok := l.session(request); ok {
		_ = request.ParseForm()
		if l.keys.ValidCSRF(session.ID, request.PostForm.Get("csrf")) {
			if err := l.store.revokeSession(request.Context(), session.ID, l.now()); err != nil {
				l.unavailable(writer, err)
				return
			}
		}
	}
	http.SetCookie(writer, &http.Cookie{Name: lenderCookie, Value: "", Path: "/lender", MaxAge: -1, HttpOnly: true,
		Secure: l.secureCookies(request), SameSite: http.SameSiteLaxMode})
	l.message(writer, http.StatusOK, "Signed out", "You have signed out of Edify's referral pages.")
}

type confirmPage struct {
	page
	Token, Lender, MaskedEmail string
	Confirmed                  bool
}

// confirmAddressPage asks the lender to confirm its receiving address with a
// button press: a link scanner that opens the email's link confirms nothing.
func (l *lenderPages) confirmAddressPage(writer http.ResponseWriter, request *http.Request) {
	token := request.URL.Query().Get("t")
	channel, err := l.store.channelByConfirmToken(request.Context(), HashToken(token), l.now())
	if err != nil {
		l.message(writer, http.StatusNotFound, "This link has expired",
			"This confirmation link has expired or was already used. Ask Edify's Country Director to send a new one.")
		return
	}
	l.render(writer, http.StatusOK, "lender_confirm.html", confirmPage{
		page:  l.page("Confirm your address", "Confirm your receiving address"),
		Token: token, Lender: channel.LenderName, MaskedEmail: channel.Email,
	})
}

func (l *lenderPages) confirmAddress(writer http.ResponseWriter, request *http.Request) {
	if !l.limits.Allow("lender-confirm:"+l.clientKey(request), 20, 10*time.Minute) {
		l.tooMany(writer)
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	_ = request.ParseForm()
	token := request.PostForm.Get("t")
	channel, err := l.store.channelByConfirmToken(request.Context(), HashToken(token), l.now())
	if err == nil {
		err = l.store.confirmChannel(request.Context(), HashToken(token), l.now())
	}
	if err != nil {
		l.message(writer, http.StatusNotFound, "This link has expired",
			"This confirmation link has expired or was already used. Ask Edify's Country Director to send a new one.")
		return
	}
	l.render(writer, http.StatusOK, "lender_confirm.html", confirmPage{
		page:   l.page("Address confirmed", "Address confirmed"),
		Lender: channel.LenderName, MaskedEmail: channel.Email, Confirmed: true,
	})
}
