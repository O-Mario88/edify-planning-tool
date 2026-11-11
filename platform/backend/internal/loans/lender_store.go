package loans

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// Lender access lifetimes and limits.
const (
	codeLifetime        = 10 * time.Minute
	maxCodeAttempts     = 5
	maxCodesPerAccess   = 3
	sessionLifetime     = 8 * time.Hour
	confirmLifetime     = 7 * 24 * time.Hour
	lenderListLimit     = 200
	lenderTimelineLimit = 200
)

// ErrCodeRefused: the code is wrong, used up or expired.
var ErrCodeRefused = errors.New("loans: code refused")

type lenderAccess struct {
	ID            string
	PartnerID     string
	ApplicationID string
	Email         string
}

func (s *Store) accessByToken(ctx context.Context, hash string, now time.Time) (lenderAccess, error) {
	var access lenderAccess
	err := s.db.QueryRow(ctx, `
SELECT id, partner_id, COALESCE(application_id::text, ''), email FROM school_loans.lender_access
WHERE token_hash = $1 AND expires_at > $2`, hash, now).
		Scan(&access.ID, &access.PartnerID, &access.ApplicationID, &access.Email)
	if errors.Is(err, pgx.ErrNoRows) {
		return access, ErrNotFound
	}
	return access, err
}

func codeHash(accessID, code string) string { return HashToken(accessID + ":" + code) }

// newCode records a code for access, refusing more than a few in a row.
func (s *Store) newCode(ctx context.Context, access lenderAccess, code string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var recent int
		if err := tx.QueryRow(ctx, `
SELECT count(*) FROM school_loans.lender_verification WHERE access_id = $1 AND created_at > $2`,
			access.ID, now.Add(-codeLifetime)).Scan(&recent); err != nil {
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
INSERT INTO school_loans.lender_verification (id, access_id, code_hash, expires_at, created_at)
VALUES ($1, $2, $3, $4, $5)`, id, access.ID, codeHash(access.ID, code), now.Add(codeLifetime), now)
		return err
	})
}

// checkCode spends one attempt on the newest live code for access, and on
// success opens a lender session, returning its token.
func (s *Store) checkCode(ctx context.Context, access lenderAccess, code string, now time.Time) (sessionToken string, err error) {
	wrong := false
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		var id, hash string
		var attempts int
		err := tx.QueryRow(ctx, `
SELECT id, code_hash, attempts FROM school_loans.lender_verification
WHERE access_id = $1 AND verified_at IS NULL AND expires_at > $2
ORDER BY created_at DESC LIMIT 1 FOR UPDATE`, access.ID, now).Scan(&id, &hash, &attempts)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrCodeRefused
		}
		if err != nil {
			return err
		}
		if attempts >= maxCodeAttempts {
			return ErrCodeRefused
		}
		if hash != codeHash(access.ID, code) {
			// The attempt is counted and committed; the caller is refused.
			_, err := tx.Exec(ctx, `UPDATE school_loans.lender_verification SET attempts = attempts + 1 WHERE id = $1`, id)
			wrong = true
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE school_loans.lender_verification SET verified_at = $2 WHERE id = $1`, id, now); err != nil {
			return err
		}
		token, err := NewToken()
		if err != nil {
			return err
		}
		sessionID, err := NewID()
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.lender_session (id, partner_id, email, token_hash, expires_at, created_at)
VALUES ($1, $2, $3, $4, $5, $6)`, sessionID, access.PartnerID, access.Email, HashToken(token),
			now.Add(sessionLifetime), now); err != nil {
			return err
		}
		sessionToken = token
		return nil
	})
	if err == nil && wrong {
		return "", ErrCodeRefused
	}
	return sessionToken, err
}

type lenderSession struct {
	ID         string
	PartnerID  string
	Email      string
	LenderName string
}

func (s *Store) sessionByToken(ctx context.Context, hash string, now time.Time) (lenderSession, error) {
	var session lenderSession
	err := s.db.QueryRow(ctx, `
SELECT ls.id, ls.partner_id, ls.email, p.name FROM school_loans.lender_session ls
JOIN partner p ON p.id = ls.partner_id
WHERE ls.token_hash = $1 AND ls.expires_at > $2 AND ls.revoked_at IS NULL`, hash, now).
		Scan(&session.ID, &session.PartnerID, &session.Email, &session.LenderName)
	if errors.Is(err, pgx.ErrNoRows) {
		return session, ErrNotFound
	}
	return session, err
}

func (s *Store) revokeSession(ctx context.Context, id string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `UPDATE school_loans.lender_session SET revoked_at = $2 WHERE id = $1`, id, now)
		return err
	})
}

// ReferralSummary is one row of a lender's list.
type ReferralSummary struct {
	ID          string
	Reference   string
	SchoolName  string
	District    string
	Requested   int64
	Status      string
	SubmittedAt time.Time
}

// LenderReferrals are the applications addressed to one lender, newest first.
func (s *Store) LenderReferrals(ctx context.Context, partnerID string) ([]ReferralSummary, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, reference, school_name, district_name, requested_amount_ugx, status, submitted_at
FROM school_loans.application WHERE partner_id = $1 ORDER BY submitted_at DESC LIMIT $2`, partnerID, lenderListLimit)
	if err != nil {
		return nil, fmt.Errorf("loans: reading a lender's referrals: %w", err)
	}
	defer rows.Close()
	var out []ReferralSummary
	for rows.Next() {
		var r ReferralSummary
		if err := rows.Scan(&r.ID, &r.Reference, &r.SchoolName, &r.District, &r.Requested, &r.Status, &r.SubmittedAt); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// Referral is one application as a lender or Edify staff read it. The
// director's religion is never part of it.
type Referral struct {
	ID, Reference, Source                                      string
	SchoolName, DirectorName, DirectorPhone, DirectorEmail     string
	District, SubCounty, Parish, Village                       string
	Boys, Girls, Total                                         int
	FeesCollected                                              int64
	PurposeCode, PurposeLabel, PurposeOther, PurposeDetails    string
	Requested                                                  int64
	PreferredTerm                                              int
	PartnerID, LenderName                                      string
	MatchStatus, SchoolDirectoryID, EdifySchoolID, MatchMethod string
	Status, DeliveryStatus                                     string
	ResponsibleBTOID, ResponsibleBTOName                       string
	NextFollowUp                                               *time.Time
	LastFollowUp, LenderReceivedAt, DecidedAt                  *time.Time
	Approved, Disbursed                                        *int64
	DisbursementDate                                           *time.Time
	AgreedTerm                                                 *int
	InterestRate, DisbursementReference, LinkedMFILoanID       string
	SubmittedAt, UpdatedAt                                     time.Time
	ConsentVersion                                             string
}

const referralColumns = `
a.id, a.reference, a.source, a.school_name, a.director_name, a.director_phone, a.director_email,
a.district_name, a.sub_county_name, a.parish_name, a.village_name, a.boys, a.girls, a.total_enrollment,
a.average_fees_collected_ugx, a.purpose_code, a.purpose_label, a.purpose_other, a.purpose_details,
a.requested_amount_ugx, COALESCE(a.preferred_term_months, 0), a.partner_id, a.lender_name,
a.school_match_status, COALESCE(a.school_id, ''), COALESCE(s.school_id, ''), a.match_method,
a.status, a.delivery_status, a.responsible_bto_id, a.responsible_bto_name, a.next_follow_up_on,
a.last_follow_up_at, a.lender_received_at, a.decided_at, a.approved_amount_ugx, a.disbursed_amount_ugx,
a.disbursement_date, a.agreed_term_months, a.interest_rate_text, a.disbursement_reference,
a.linked_mfi_loan_id, a.submitted_at, a.updated_at, a.consent_version`

func scanReferral(row pgx.Row) (Referral, error) {
	var r Referral
	err := row.Scan(&r.ID, &r.Reference, &r.Source, &r.SchoolName, &r.DirectorName, &r.DirectorPhone,
		&r.DirectorEmail, &r.District, &r.SubCounty, &r.Parish, &r.Village, &r.Boys, &r.Girls, &r.Total,
		&r.FeesCollected, &r.PurposeCode, &r.PurposeLabel, &r.PurposeOther, &r.PurposeDetails, &r.Requested,
		&r.PreferredTerm, &r.PartnerID, &r.LenderName, &r.MatchStatus, &r.SchoolDirectoryID, &r.EdifySchoolID,
		&r.MatchMethod, &r.Status, &r.DeliveryStatus, &r.ResponsibleBTOID, &r.ResponsibleBTOName, &r.NextFollowUp,
		&r.LastFollowUp, &r.LenderReceivedAt, &r.DecidedAt, &r.Approved, &r.Disbursed, &r.DisbursementDate,
		&r.AgreedTerm, &r.InterestRate, &r.DisbursementReference, &r.LinkedMFILoanID, &r.SubmittedAt,
		&r.UpdatedAt, &r.ConsentVersion)
	if errors.Is(err, pgx.ErrNoRows) {
		return r, ErrNotFound
	}
	return r, err
}

// Referral reads one application by id. partnerID, when set, confines the
// read to that lender's applications.
func (s *Store) Referral(ctx context.Context, id, partnerID string) (Referral, error) {
	return scanReferral(s.db.QueryRow(ctx, `
SELECT `+referralColumns+`
FROM school_loans.application a LEFT JOIN school s ON s.id = a.school_id
WHERE a.id = $1 AND ($2 = '' OR a.partner_id = $2)`, id, partnerID))
}

// ReferralByReference is Referral by the reference a lender quotes.
func (s *Store) ReferralByReference(ctx context.Context, reference, partnerID string) (Referral, error) {
	return scanReferral(s.db.QueryRow(ctx, `
SELECT `+referralColumns+`
FROM school_loans.application a LEFT JOIN school s ON s.id = a.school_id
WHERE a.reference = $1 AND a.partner_id = $2`, reference, partnerID))
}

// lenderEventKinds are the timeline entries a lender sees: its own actions,
// the application's arrival and delivery, and status changes. Staff notes,
// follow-ups and school matching are Edify's own.
var lenderEventKinds = []string{
	"submitted", "delivery_sent", "lender_opened", "lender_acknowledged", "status_changed",
	"information_requested", "approved", "declined", "disbursed", "closed", "withdrawn", "lender_message",
}

// Timeline is an application's events, oldest first. lenderView keeps to
// what a lender may see.
func (s *Store) Timeline(ctx context.Context, applicationID string, lenderView bool) ([]Event, error) {
	query := `
SELECT application_id::text, kind, actor_kind, actor_id, actor_name, from_status, to_status, note, evidence, created_at
FROM school_loans.application_event WHERE application_id = $1`
	args := []any{applicationID}
	if lenderView {
		query += ` AND kind = ANY($2)`
		args = append(args, lenderEventKinds)
	}
	query += fmt.Sprintf(` ORDER BY created_at LIMIT %d`, lenderTimelineLimit)
	rows, err := s.db.Query(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("loans: reading a timeline: %w", err)
	}
	defer rows.Close()
	var out []Event
	for rows.Next() {
		var e Event
		if err := rows.Scan(&e.ApplicationID, &e.Kind, &e.ActorKind, &e.ActorID, &e.ActorName, &e.FromStatus,
			&e.ToStatus, &e.Note, &e.Evidence, &e.At); err != nil {
			return nil, err
		}
		if lenderView && e.ActorKind == "staff" {
			// A staff correction is shown without who recorded it.
			e.ActorID, e.ActorName = "", "Edify"
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

// channelToConfirm is a lender receiving address awaiting the lender's
// own confirmation.
type channelToConfirm struct {
	PartnerID, LenderName, Email string
}

func (s *Store) channelByConfirmToken(ctx context.Context, hash string, now time.Time) (channelToConfirm, error) {
	var channel channelToConfirm
	err := s.db.QueryRow(ctx, `
SELECT c.partner_id, p.name, c.delivery_email FROM school_loans.lender_channel c JOIN partner p ON p.id = c.partner_id
WHERE c.confirm_token_hash = $1 AND c.confirm_expires_at > $2`, hash, now).
		Scan(&channel.PartnerID, &channel.LenderName, &channel.Email)
	if errors.Is(err, pgx.ErrNoRows) {
		return channel, ErrNotFound
	}
	return channel, err
}

func (s *Store) confirmChannel(ctx context.Context, hash string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var partnerID, email string
		err := tx.QueryRow(ctx, `
UPDATE school_loans.lender_channel
SET confirmed_email = delivery_email, confirmed_at = $2, confirm_token_hash = NULL, confirm_expires_at = NULL,
  updated_at = $2
WHERE confirm_token_hash = $1 AND confirm_expires_at > $2
RETURNING partner_id, delivery_email`, hash, now).Scan(&partnerID, &email)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		return channelEvent(ctx, tx, partnerID, "address_confirmed", "lender", "",
			"The lender confirmed "+maskEmail(email)+" as its receiving address.")
	})
}

func channelEvent(ctx context.Context, tx pgx.Tx, partnerID, kind, actorID, actorName, note string) error {
	id, err := NewID()
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `
INSERT INTO school_loans.lender_channel_event (id, partner_id, kind, actor_id, actor_name, note)
VALUES ($1, $2, $3, $4, $5, $6)`, id, partnerID, kind, actorID, actorName, note)
	return err
}
