package signin

import (
	"context"
	"crypto/subtle"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// The existing second factor's limits (apps/accounts/mfa_service.py).
const (
	codeTTL                = 10 * time.Minute
	maxCodeAttempts        = 5
	maxChallengesPerWindow = 10
	challengeWindow        = time.Hour

	channelEmail = "email"
	channelSMS   = "sms"
	channelApp   = "app"
	appHint      = "your authenticator app"
)

// Verification outcomes, the existing reason strings.
const (
	codeIncorrect   = "code_incorrect"
	codeExpired     = "code_expired"
	tooManyAttempts = "too_many_attempts"
	alreadyUsed     = "already_used"
)

var errChallengeLimit = errors.New("signin: too many sign-in codes issued lately")

// Challenge is an issued sign-in code, as the caller is told about it.
type Challenge struct {
	ClientToken string
	Channel     string
	Hint        string
	ExpiresIn   time.Duration
	// code and destination are for delivery only; never returned.
	code, destination string
}

// channelFor is resolve_channel: the enrolled channel when it can reach the
// person now, otherwise email.
func channelFor(a account, smsAvailable bool) string {
	switch {
	case a.MFAChannel == channelApp && a.MFASecret != "":
		return channelApp
	case a.MFAChannel == channelSMS && a.Phone != "" && smsAvailable:
		return channelSMS
	}
	return channelEmail
}

// startChallenge is start_api_challenge: any open challenge of the account
// expires, and a new one is issued with its code and client token hashed.
func (s *Store) startChallenge(ctx context.Context, a account, smsAvailable bool, now time.Time) (Challenge, error) {
	var recent int
	if err := s.db.QueryRow(ctx,
		`SELECT count(*) FROM mfa_challenge WHERE user_id = $1 AND created_at >= $2`,
		a.ID, now.Add(-challengeWindow)).Scan(&recent); err != nil {
		return Challenge{}, fmt.Errorf("signin: counting sign-in codes: %w", err)
	}
	if recent >= maxChallengesPerWindow {
		return Challenge{}, errChallengeLimit
	}
	channel := channelFor(a, smsAvailable)
	challenge := Challenge{Channel: channel, ExpiresIn: codeTTL}
	switch channel {
	case channelApp:
		challenge.Hint = appHint
	case channelSMS:
		challenge.destination, challenge.Hint = a.Phone, maskPhone(a.Phone)
	default:
		challenge.destination, challenge.Hint = a.Email, maskEmail(a.Email)
	}
	code, err := newCode()
	if err != nil {
		return Challenge{}, err
	}
	token, err := newClientToken()
	if err != nil {
		return Challenge{}, err
	}
	challenge.code, challenge.ClientToken = code, token

	err = s.write(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE mfa_challenge SET expires_at = $2, updated_at = $2
WHERE user_id = $1 AND consumed_at IS NULL AND expires_at > $2`, a.ID, now); err != nil {
			return fmt.Errorf("signin: closing open sign-in codes: %w", err)
		}
		_, err := tx.Exec(ctx, `
INSERT INTO mfa_challenge (id, user_id, channel, destination_hint, code_hash, client_token_hash,
                           expires_at, attempts, deliveries, last_sent_at, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, 0, 1, $8, $8, $8)`,
			cuid.New(), a.ID, channel, challenge.Hint, hashToken(code), hashToken(token), now.Add(codeTTL), now)
		if err != nil {
			return fmt.Errorf("signin: issuing a sign-in code: %w", err)
		}
		return nil
	})
	return challenge, err
}

// checked is one answer to a challenge.
type checked struct {
	OK      bool
	Reason  string
	UserID  string
	Channel string
}

// errNoChallenge: no open challenge has this client token.
var errNoChallenge = errors.New("signin: no open sign-in code")

// checkChallenge is verify(): the answer is compared under the challenge's
// row lock, a right one spends it, a wrong one counts against it. secretOf
// returns the account's authenticator secret, opened.
func (s *Store) checkChallenge(ctx context.Context, clientToken, submitted string, now time.Time,
	secretOf func(stored string) (string, error)) (checked, error) {
	var result checked
	err := s.write(ctx, func(tx pgx.Tx) error {
		var (
			id, codeHash, storedSecret string
			expires                    time.Time
			consumed                   bool
			attempts                   int
		)
		err := tx.QueryRow(ctx, `
SELECT c.id, c.user_id, c.channel, c.code_hash, c.expires_at, c.consumed_at IS NOT NULL, c.attempts,
       COALESCE(u.mfa_secret, '')
FROM mfa_challenge c JOIN "user" u ON u.id = c.user_id
WHERE c.client_token_hash = $1 AND c.consumed_at IS NULL
FOR UPDATE OF c`, hashToken(clientToken)).Scan(&id, &result.UserID, &result.Channel, &codeHash, &expires,
			&consumed, &attempts, &storedSecret)
		if errors.Is(err, pgx.ErrNoRows) {
			return errNoChallenge
		}
		if err != nil {
			return fmt.Errorf("signin: reading the sign-in code: %w", err)
		}
		switch {
		case consumed:
			result.Reason = alreadyUsed
			return nil
		case !expires.After(now):
			result.Reason = codeExpired
			return nil
		case attempts >= maxCodeAttempts:
			result.Reason = tooManyAttempts
			return nil
		}

		digits := digitsOf(submitted)
		right := false
		if result.Channel == channelApp {
			if secret, err := secretOf(storedSecret); err == nil && secret != "" {
				right = totpMatches(secret, digits, now)
			}
		} else {
			right = digits != "" && subtle.ConstantTimeCompare([]byte(hashToken(digits)), []byte(codeHash)) == 1
		}
		if right {
			result.OK = true
			_, err := tx.Exec(ctx, `UPDATE mfa_challenge SET consumed_at = $2, updated_at = $2 WHERE id = $1`, id, now)
			return err
		}
		attempts++
		if _, err := tx.Exec(ctx, `UPDATE mfa_challenge SET attempts = $2, updated_at = $3 WHERE id = $1`,
			id, attempts, now); err != nil {
			return err
		}
		result.Reason = codeIncorrect
		if attempts >= maxCodeAttempts {
			result.Reason = tooManyAttempts
		}
		return nil
	})
	return result, err
}
