package loans

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Account-free application tracking. The reference and the director's
// phone ask for a code; the code goes only to the phone on the application,
// and the answer is the same whether or not they matched, so references
// cannot be tried one after another. A right code opens a 30-minute
// session showing the application's progress, never a loan statement
// (statements have their own links and codes).

const trackCookie = "edify_track"

// trackingTarget is the application with this reference and phone, if any.
func (s *Store) trackingTarget(ctx context.Context, reference, phone string) (id, email string, err error) {
	err = s.db.QueryRow(ctx, `
SELECT id::text, COALESCE(director_email, '') FROM school_loans.application
WHERE reference = $1 AND director_phone = $2`, reference, phone).Scan(&id, &email)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", "", ErrNotFound
	}
	return id, email, err
}

// newTrackingCode records a code, refusing more than a few in a row.
func (s *Store) newTrackingCode(ctx context.Context, applicationID, code string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var recent int
		if err := tx.QueryRow(ctx, `
SELECT count(*) FROM school_loans.tracking_verification WHERE application_id = $1 AND created_at > $2`,
			applicationID, now.Add(-codeLifetime)).Scan(&recent); err != nil {
			return err
		}
		if recent >= maxCodesPerAccess {
			return ErrCodeRefused
		}
		id, err := NewID()
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.tracking_verification (id, application_id, code_hash, expires_at, created_at)
VALUES ($1, $2, $3, $4, $5)`, id, applicationID, HashToken("track:"+applicationID+":"+code), now.Add(codeLifetime), now)
		return err
	})
}

// checkTrackingCode spends one try on the newest live code for the
// reference and, when right, opens a session. Any failure is ErrCodeRefused.
func (s *Store) checkTrackingCode(ctx context.Context, reference, code string, now time.Time) (string, string, error) {
	var token, applicationID string
	wrong := false
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		var id, hash string
		var attempts int
		err := tx.QueryRow(ctx, `
SELECT v.id, v.code_hash, v.attempts, a.id::text
FROM school_loans.tracking_verification v JOIN school_loans.application a ON a.id = v.application_id
WHERE a.reference = $1 AND v.verified_at IS NULL AND v.expires_at > $2
ORDER BY v.created_at DESC LIMIT 1 FOR UPDATE OF v`, reference, now).Scan(&id, &hash, &attempts, &applicationID)
		if errors.Is(err, pgx.ErrNoRows) || (err == nil && attempts >= maxCodeAttempts) {
			wrong = true
			return nil
		}
		if err != nil {
			return err
		}
		if hash != HashToken("track:"+applicationID+":"+code) {
			wrong = true
			_, err := tx.Exec(ctx, `UPDATE school_loans.tracking_verification SET attempts = attempts + 1 WHERE id = $1`, id)
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE school_loans.tracking_verification SET verified_at = $2 WHERE id = $1`, id, now); err != nil {
			return err
		}
		if token, err = NewToken(); err != nil {
			return err
		}
		sessionID, err := NewID()
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.tracking_session (id, application_id, token_hash, expires_at, created_at)
VALUES ($1, $2, $3, $4, $5)`, sessionID, applicationID, HashToken(token), now.Add(schoolSessionLifetime), now)
		return err
	})
	if err == nil && wrong {
		return "", "", ErrCodeRefused
	}
	return token, applicationID, err
}

func (s *Store) trackingSession(ctx context.Context, hash string, now time.Time) (string, string, error) {
	var id, applicationID string
	err := s.db.QueryRow(ctx, `
SELECT id::text, application_id::text FROM school_loans.tracking_session
WHERE token_hash = $1 AND expires_at > $2 AND revoked_at IS NULL`, hash, now).Scan(&id, &applicationID)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", "", ErrNotFound
	}
	return id, applicationID, err
}

func (s *Store) endTrackingSession(ctx context.Context, id string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `UPDATE school_loans.tracking_session SET revoked_at = $2 WHERE id = $1 AND revoked_at IS NULL`, id, now)
		return err
	})
}

// schoolEventLabels are the steps a school sees, worded for the school.
// Lender staff names, notes and Edify's own follow-ups are left out.
var schoolEventLabels = map[string]string{
	"submitted":                         "Application submitted",
	"delivery_sent":                     "Sent to your chosen lender",
	"lender_opened":                     "Opened by the lender",
	"lender_acknowledged":               "Received by the lender",
	"assigned":                          "A loan officer was assigned",
	"status_changed":                    "Under review by the lender",
	"information_requested":             "The lender asked for more information",
	"agreement_issued":                  "Proposed terms sent to you",
	"agreement_accepted":                "You accepted the proposed terms",
	"agreement_declined":                "You declined the proposed terms",
	"agreement_clarification_requested": "You asked the lender for clarification",
	"approved":                          "Approved by the lender",
	"declined":                          "Declined by the lender",
	"disbursed":                         "Disbursement recorded by the lender",
	"closed":                            "Closed",
	"withdrawn":                         "Withdrawn",
}

// TrackingStep is one dated step of an application, as the school sees it.
type TrackingStep struct {
	Label string
	At    time.Time
}

// SchoolTimeline is an application's steps a school may see, oldest first.
func (s *Store) SchoolTimeline(ctx context.Context, applicationID string) ([]TrackingStep, error) {
	kinds := make([]string, 0, len(schoolEventLabels))
	for kind := range schoolEventLabels {
		kinds = append(kinds, kind)
	}
	rows, err := s.db.Query(ctx, `
SELECT kind, created_at FROM school_loans.application_event
WHERE application_id = $1 AND kind = ANY($2) ORDER BY created_at LIMIT 100`, applicationID, kinds)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []TrackingStep
	for rows.Next() {
		var kind string
		var step TrackingStep
		if err := rows.Scan(&kind, &step.At); err != nil {
			return nil, err
		}
		step.Label = schoolEventLabels[kind]
		out = append(out, step)
	}
	return out, rows.Err()
}

// The pages.

type trackPage struct {
	page
	Reference, Problem, Sent string
	CodeStep                 bool
}

type trackViewPage struct {
	page
	Receipt                  Receipt
	SubmittedOn, StatusLabel string
	DeliveryLabel, Progress  string
	Steps                    []TrackingStep
	CSRF                     string
	SessionMinutes           int
}

func (s *schoolPages) trackPageData(reference, problem string, codeStep bool) trackPage {
	return trackPage{page: page{Title: "Track your loan application", Eyebrow: "Edify school loans",
		Heading: "Track your loan application", Version: s.version}, Reference: reference, Problem: problem, CodeStep: codeStep}
}

func (s *schoolPages) trackForm(writer http.ResponseWriter, request *http.Request) {
	schoolHeaders(writer)
	if !s.limits.Allow("track:"+s.clientKey(request), pageViewsPerMinute, time.Minute) {
		s.tooMany(writer)
		return
	}
	s.render(writer, http.StatusOK, "track.html", s.trackPageData("", "", false))
}

// sentWording is said whatever the reference and phone were, so nobody
// learns from it whether an application exists.
const sentWording = "If the reference and phone number match an application, we have sent a six-digit code to that phone. It works for 10 minutes."

func (s *schoolPages) trackCode(writer http.ResponseWriter, request *http.Request) {
	schoolHeaders(writer)
	if !s.limits.Allow("track-code:"+s.clientKey(request), 5, 10*time.Minute) {
		s.tooMany(writer)
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	_ = request.ParseForm()
	reference := strings.ToUpper(strings.TrimSpace(request.PostForm.Get("reference")))
	phone, phoneErr := NormalizePhone(request.PostForm.Get("phone"))
	if reference == "" || phoneErr != nil {
		s.render(writer, http.StatusUnprocessableEntity, "track.html",
			s.trackPageData(reference, "Enter your application reference and the director's phone number.", false))
		return
	}
	data := s.trackPageData(reference, "", true)
	data.Sent = sentWording
	id, email, err := s.store.trackingTarget(request.Context(), reference, phone)
	if errors.Is(err, ErrNotFound) {
		s.render(writer, http.StatusOK, "track.html", data)
		return
	}
	if err != nil {
		s.unavailable(writer, err)
		return
	}
	code, err := NewCode()
	if err != nil {
		s.unavailable(writer, err)
		return
	}
	if err := s.store.newTrackingCode(request.Context(), id, code, s.now()); err != nil {
		if !errors.Is(err, ErrCodeRefused) {
			s.unavailable(writer, err)
			return
		}
		s.render(writer, http.StatusOK, "track.html", data) // the same answer; the newest code still works
		return
	}
	body := "Your Edify loan tracking code is " + code + ". It works for 10 minutes. Do not share it."
	switch {
	case s.lending.sms != nil:
		_, err = s.lending.sms.Send(request.Context(), phone, body)
	case s.lending.mailer != nil && email != "":
		_, err = s.lending.mailer.Send(request.Context(), Message{To: email, Subject: "Your Edify loan tracking code", Text: body + "\n"})
	default:
		err = ErrNoSMS
	}
	if err != nil {
		s.logger.Error("loans: sending a tracking code", slog.String("error", err.Error()))
	}
	s.log(request, id, "", "tracking_code_sent")
	s.render(writer, http.StatusOK, "track.html", data)
}

func (s *schoolPages) trackVerify(writer http.ResponseWriter, request *http.Request) {
	schoolHeaders(writer)
	if !s.limits.Allow("track-verify:"+s.clientKey(request), 20, 10*time.Minute) {
		s.tooMany(writer)
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	_ = request.ParseForm()
	reference := strings.ToUpper(strings.TrimSpace(request.PostForm.Get("reference")))
	code := strings.TrimSpace(strings.ReplaceAll(request.PostForm.Get("code"), " ", ""))
	token, applicationID, err := s.store.checkTrackingCode(request.Context(), reference, code, s.now())
	if err != nil {
		if !errors.Is(err, ErrCodeRefused) {
			s.unavailable(writer, err)
			return
		}
		data := s.trackPageData(reference, "That code is not right, or it has expired. Ask for a new code.", true)
		s.render(writer, http.StatusUnauthorized, "track.html", data)
		return
	}
	http.SetCookie(writer, &http.Cookie{Name: trackCookie, Value: token, Path: trackPath, HttpOnly: true,
		Secure: request.TLS != nil || strings.HasPrefix(s.cfg.PublicBaseURL, "https://"), SameSite: http.SameSiteStrictMode,
		MaxAge: int(schoolSessionLifetime.Seconds())})
	s.log(request, applicationID, "", "tracking_verified")
	http.Redirect(writer, request, trackPath+"/view", http.StatusSeeOther)
}

func (s *schoolPages) trackSession(writer http.ResponseWriter, request *http.Request) (string, string, bool) {
	schoolHeaders(writer)
	cookie, err := request.Cookie(trackCookie)
	if err == nil && cookie.Value != "" {
		if id, applicationID, err := s.store.trackingSession(request.Context(), HashToken(cookie.Value), s.now()); err == nil {
			return id, applicationID, true
		}
	}
	s.message(writer, http.StatusUnauthorized, "Your session has ended",
		"For your school's privacy, tracking closes after 30 minutes. Open "+trackPath+" and ask for a new code.")
	return "", "", false
}

func (s *schoolPages) trackView(writer http.ResponseWriter, request *http.Request) {
	sessionID, applicationID, ok := s.trackSession(writer, request)
	if !ok {
		return
	}
	receipt, err := s.store.ReceiptOf(request.Context(), applicationID)
	if err != nil {
		s.unavailable(writer, err)
		return
	}
	steps, err := s.store.SchoolTimeline(request.Context(), applicationID)
	if err != nil {
		s.unavailable(writer, err)
		return
	}
	s.log(request, applicationID, "", "tracking_viewed")
	s.render(writer, http.StatusOK, "track_view.html", trackViewPage{
		page:    page{Title: "Your loan application", Eyebrow: "Edify school loans", Heading: "Your loan application", Version: s.version},
		Receipt: receipt, SubmittedOn: longMoment(receipt.SubmittedAt), StatusLabel: StatusLabel(receipt.Status),
		DeliveryLabel: DeliveryLabel(receipt.DeliveryStatus), Progress: progressOf(receipt), Steps: steps,
		CSRF: s.keys.CSRFToken(sessionID), SessionMinutes: int(schoolSessionLifetime.Minutes()),
	})
}

func (s *schoolPages) trackSignOut(writer http.ResponseWriter, request *http.Request) {
	schoolHeaders(writer)
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	_ = request.ParseForm()
	if cookie, err := request.Cookie(trackCookie); err == nil {
		if id, _, err := s.store.trackingSession(request.Context(), HashToken(cookie.Value), s.now()); err == nil &&
			s.keys.ValidCSRF(id, request.PostForm.Get("csrf")) {
			if err := s.store.endTrackingSession(request.Context(), id, s.now()); err != nil {
				s.logger.Error("loans: ending a tracking session", slog.String("error", err.Error()))
			}
		}
	}
	http.SetCookie(writer, &http.Cookie{Name: trackCookie, Value: "", Path: trackPath, HttpOnly: true, MaxAge: -1})
	s.message(writer, http.StatusOK, "You have signed out", "To check again, open "+trackPath+" and ask for a new code.")
}
