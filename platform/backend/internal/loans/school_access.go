package loans

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
)

// How long a school's access lasts.
const (
	agreementLinkLifetime = 14 * 24 * time.Hour
	statementLinkLifetime = 30 * 24 * time.Hour
	schoolSessionLifetime = 30 * time.Minute
)

// SchoolAccess is a live private link sent to a school's director.
type SchoolAccess struct {
	ID, ApplicationID, Purpose, Channel, Destination string
}

// IssueSchoolAccess records a private link for one application and purpose,
// to be opened with a code sent to destination, and returns its token.
func (s *Store) IssueSchoolAccess(ctx context.Context, applicationID, purpose, channel, destination, byID string, now time.Time) (string, error) {
	token, err := NewToken()
	if err != nil {
		return "", err
	}
	id, err := NewID()
	if err != nil {
		return "", err
	}
	lifetime := statementLinkLifetime
	if purpose == "agreement" {
		lifetime = agreementLinkLifetime
	}
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
INSERT INTO school_loans.school_access (id, application_id, purpose, token_hash, channel, destination, expires_at,
  created_by, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`, id, applicationID, purpose, HashToken(token), channel, destination,
			now.Add(lifetime), byID, now)
		return err
	})
	return token, err
}

func (s *Store) schoolAccessByToken(ctx context.Context, hash, purpose string, now time.Time) (SchoolAccess, error) {
	var a SchoolAccess
	err := s.db.QueryRow(ctx, `
SELECT id, application_id::text, purpose, channel, destination FROM school_loans.school_access
WHERE token_hash = $1 AND purpose = $2 AND expires_at > $3 AND revoked_at IS NULL`, hash, purpose, now).
		Scan(&a.ID, &a.ApplicationID, &a.Purpose, &a.Channel, &a.Destination)
	if errors.Is(err, pgx.ErrNoRows) {
		return a, ErrNotFound
	}
	return a, err
}

func schoolCodeHash(accessID, code string) string {
	return HashToken("school:" + accessID + ":" + code)
}

// newSchoolCode records a code for access, refusing more than a few in a row.
func (s *Store) newSchoolCode(ctx context.Context, access SchoolAccess, code string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var recent int
		if err := tx.QueryRow(ctx, `
SELECT count(*) FROM school_loans.school_verification WHERE access_id = $1 AND created_at > $2`,
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
INSERT INTO school_loans.school_verification (id, access_id, code_hash, expires_at, created_at)
VALUES ($1, $2, $3, $4, $5)`, id, access.ID, schoolCodeHash(access.ID, code), now.Add(codeLifetime), now)
		return err
	})
}

// checkSchoolCode spends one attempt on the newest live code and, when it is
// right, opens a short session for the access's application and purpose.
func (s *Store) checkSchoolCode(ctx context.Context, access SchoolAccess, code string, now time.Time) (string, error) {
	var token string
	wrong := false
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		var id, hash string
		var attempts int
		err := tx.QueryRow(ctx, `
SELECT id, code_hash, attempts FROM school_loans.school_verification
WHERE access_id = $1 AND verified_at IS NULL AND expires_at > $2 ORDER BY created_at DESC LIMIT 1 FOR UPDATE`,
			access.ID, now).Scan(&id, &hash, &attempts)
		if errors.Is(err, pgx.ErrNoRows) || (err == nil && attempts >= maxCodeAttempts) {
			wrong = true
			return nil
		}
		if err != nil {
			return err
		}
		if hash != schoolCodeHash(access.ID, code) {
			wrong = true
			_, err := tx.Exec(ctx, `UPDATE school_loans.school_verification SET attempts = attempts + 1 WHERE id = $1`, id)
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE school_loans.school_verification SET verified_at = $2 WHERE id = $1`, id, now); err != nil {
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
INSERT INTO school_loans.school_session (id, access_id, application_id, purpose, token_hash, expires_at, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7)`, sessionID, access.ID, access.ApplicationID, access.Purpose, HashToken(token),
			now.Add(schoolSessionLifetime), now)
		return err
	})
	if err == nil && wrong {
		return "", ErrCodeRefused
	}
	return token, err
}

// SchoolSession is a verified school's short session.
type SchoolSession struct {
	ID, AccessID, ApplicationID, Purpose, Channel, Destination string
}

func (s *Store) schoolSessionByToken(ctx context.Context, hash, purpose string, now time.Time) (SchoolSession, error) {
	var session SchoolSession
	err := s.db.QueryRow(ctx, `
SELECT ss.id, ss.access_id::text, ss.application_id::text, ss.purpose, a.channel, a.destination
FROM school_loans.school_session ss JOIN school_loans.school_access a ON a.id = ss.access_id
WHERE ss.token_hash = $1 AND ss.purpose = $2 AND ss.expires_at > $3 AND ss.revoked_at IS NULL AND a.revoked_at IS NULL`,
		hash, purpose, now).Scan(&session.ID, &session.AccessID, &session.ApplicationID, &session.Purpose,
		&session.Channel, &session.Destination)
	if errors.Is(err, pgx.ErrNoRows) {
		return session, ErrNotFound
	}
	return session, err
}

// LogSchoolAccess records what a school did with its access.
func (s *Store) LogSchoolAccess(ctx context.Context, applicationID, sessionID, action, networkKey string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		id, err := NewID()
		if err != nil {
			return err
		}
		var session *string
		if sessionID != "" {
			session = &sessionID
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.school_access_log (id, application_id, session_id, action, network_key)
VALUES ($1, $2, $3, $4, $5)`, id, applicationID, session, action, networkKey)
		return err
	})
}

// AddSchoolRequest records a school's request from its statement.
func (s *Store) AddSchoolRequest(ctx context.Context, applicationID, kind, message string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		id, err := NewID()
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.school_request (id, application_id, kind, message) VALUES ($1, $2, $3, $4)`,
			id, applicationID, kind, message); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "school_request", ActorKind: "applicant",
			ActorName: "The school (verified)", Note: map[string]string{
				"discrepancy": "Reported a payment discrepancy.", "statement_update": "Asked for an updated statement.",
				"contact": "Asked the lender to get in touch.", "clarification": "Asked for clarification.",
			}[kind]})
	})
}

// EndSchoolSession ends a school's session when it signs out.
func (s *Store) EndSchoolSession(ctx context.Context, sessionID string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `UPDATE school_loans.school_session SET revoked_at = $2 WHERE id = $1 AND revoked_at IS NULL`, sessionID, now)
		return err
	})
}
