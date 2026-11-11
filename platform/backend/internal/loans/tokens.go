package loans

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"math/big"
	"strconv"
	"strings"
	"time"
)

// Keys are the portal's secrets, each derived from the gateway's signing
// secret for one purpose so no two uses share a key.
type Keys struct {
	receipt []byte
	csrf    []byte
	network []byte
}

// DeriveKeys derives the portal's keys from secret.
func DeriveKeys(secret string) Keys {
	derive := func(purpose string) []byte {
		mac := hmac.New(sha256.New, []byte(secret))
		mac.Write([]byte("edify-school-loans/v1/" + purpose))
		return mac.Sum(nil)
	}
	return Keys{receipt: derive("receipt"), csrf: derive("csrf"), network: derive("network")}
}

// NewToken is a fresh unguessable token (256 bits), safe in a URL.
func NewToken() (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("loans: reading randomness: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}

// NewIdempotencyKey is the hidden key one rendering of the form carries, so
// a repeated submit of the same form never makes a second application.
func NewIdempotencyKey() (string, error) {
	raw := make([]byte, 16)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("loans: reading randomness: %w", err)
	}
	return hex.EncodeToString(raw), nil
}

// HashToken is what is stored for a token: never the token itself.
func HashToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// ReceiptToken is the applicant's receipt link token. It is derived, not
// stored, so the same submission (same idempotency key) always leads back to
// the same receipt, and only its hash is kept.
func (k Keys) ReceiptToken(applicationID, idempotencyKey string) string {
	mac := hmac.New(sha256.New, k.receipt)
	mac.Write([]byte(applicationID + ":" + idempotencyKey))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

// CSRFToken binds a lender page's forms to its session.
func (k Keys) CSRFToken(sessionID string) string {
	mac := hmac.New(sha256.New, k.csrf)
	mac.Write([]byte(sessionID))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

// ValidCSRF compares in constant time.
func (k Keys) ValidCSRF(sessionID, token string) bool {
	return hmac.Equal([]byte(k.CSRFToken(sessionID)), []byte(token))
}

// NetworkKey is a keyed hash of a client address, for rate limits and
// abuse review without keeping the address itself.
func (k Keys) NetworkKey(address string) string {
	mac := hmac.New(sha256.New, k.network)
	mac.Write([]byte(address))
	return hex.EncodeToString(mac.Sum(nil))[:24]
}

// The reference alphabet leaves out I, L, O and U, so a reference read
// aloud or copied by hand is not mistaken.
const referenceAlphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

// NewReference is an application reference such as EDL-7K3Q-X9MZ. It is
// random, not sequential, so references cannot be counted through; it opens
// nothing on its own.
func NewReference() (string, error) {
	var out strings.Builder
	out.WriteString("EDL-")
	for index := 0; index < 8; index++ {
		if index == 4 {
			out.WriteByte('-')
		}
		pick, err := rand.Int(rand.Reader, big.NewInt(int64(len(referenceAlphabet))))
		if err != nil {
			return "", fmt.Errorf("loans: reading randomness: %w", err)
		}
		out.WriteByte(referenceAlphabet[pick.Int64()])
	}
	return out.String(), nil
}

// NewCode is a six-digit one-time code.
func NewCode() (string, error) {
	pick, err := rand.Int(rand.Reader, big.NewInt(1_000_000))
	if err != nil {
		return "", fmt.Errorf("loans: reading randomness: %w", err)
	}
	return fmt.Sprintf("%06d", pick.Int64()), nil
}

// NewID is a random UUID (version 4) for the portal's rows.
func NewID() (string, error) {
	raw := make([]byte, 16)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("loans: reading randomness: %w", err)
	}
	raw[6] = (raw[6] & 0x0f) | 0x40
	raw[8] = (raw[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", raw[0:4], raw[4:6], raw[6:8], raw[8:10], raw[10:16]), nil
}

// FormStamp is a signed record of when a form was shown. A submission sent
// sooner than a person could fill the form in is refused (a light bot check
// that costs a real applicant nothing).
func (k Keys) FormStamp(shown time.Time) string {
	seconds := strconv.FormatInt(shown.Unix(), 10)
	mac := hmac.New(sha256.New, k.csrf)
	mac.Write([]byte("stamp:" + seconds))
	return seconds + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

// StampAge is how long ago a valid stamp was issued; ok is false for a
// forged or malformed stamp.
func (k Keys) StampAge(stamp string, now time.Time) (age time.Duration, ok bool) {
	seconds, signature, found := strings.Cut(stamp, ".")
	if !found {
		return 0, false
	}
	shown, err := strconv.ParseInt(seconds, 10, 64)
	if err != nil {
		return 0, false
	}
	mac := hmac.New(sha256.New, k.csrf)
	mac.Write([]byte("stamp:" + seconds))
	if !hmac.Equal([]byte(base64.RawURLEncoding.EncodeToString(mac.Sum(nil))), []byte(signature)) {
		return 0, false
	}
	return now.Sub(time.Unix(shown, 0)), true
}
