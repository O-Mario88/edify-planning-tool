package signin

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha1" // #nosec G505 -- RFC 6238 TOTP is defined over HMAC-SHA1; authenticator apps use it.
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base32"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"math/big"
	"regexp"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// The access token is the existing one: HS256, {sub, activeRole, iat, exp}.
// Either system verifies the other's, so one session works on both.
func issueAccessToken(secret []byte, userID, activeRole string, now time.Time, ttl time.Duration) (string, error) {
	claims := jwt.MapClaims{
		"sub":        userID,
		"activeRole": activeRole,
		"iat":        now.Unix(),
		"exp":        now.Add(ttl).Unix(),
	}
	signed, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(secret)
	if err != nil {
		return "", fmt.Errorf("signin: signing the access token: %w", err)
	}
	return signed, nil
}

// newRawToken is generate_token: 32 random bytes as hex. Only its hash is
// stored; the raw value leaves this process once.
func newRawToken() (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("signin: reading randomness: %w", err)
	}
	return hex.EncodeToString(raw), nil
}

// newClientToken is the second-factor API token (secrets.token_urlsafe(32)).
func newClientToken() (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("signin: reading randomness: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}

// hashToken is hash_token, and the second factor's _hash: sha256 as hex.
func hashToken(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

const (
	codeDigits      = 6
	totpStepSeconds = 30
	totpDriftSteps  = 1
)

// newCode is a six-digit sign-in code from crypto/rand.
func newCode() (string, error) {
	n, err := rand.Int(rand.Reader, big.NewInt(1_000_000))
	if err != nil {
		return "", fmt.Errorf("signin: reading randomness: %w", err)
	}
	return fmt.Sprintf("%0*d", codeDigits, n.Int64()), nil
}

func digitsOf(s string) string {
	return strings.Map(func(r rune) rune {
		if r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, s)
}

// totpCode is the existing totp_code: RFC 6238, SHA-1, 30-second steps.
func totpCode(secret string, at time.Time, stepOffset int64) (string, error) {
	padded := strings.ToUpper(secret)
	if rem := len(padded) % 8; rem != 0 {
		padded += strings.Repeat("=", 8-rem)
	}
	key, err := base32.StdEncoding.DecodeString(padded)
	if err != nil {
		return "", fmt.Errorf("signin: the authenticator secret is not base32: %w", err)
	}
	counter := at.Unix()/totpStepSeconds + stepOffset
	var message [8]byte
	binary.BigEndian.PutUint64(message[:], uint64(counter)) // #nosec G115 -- a Unix time step is positive.
	mac := hmac.New(sha1.New, key)
	mac.Write(message[:])
	digest := mac.Sum(nil)
	offset := digest[len(digest)-1] & 0x0f
	number := binary.BigEndian.Uint32(digest[offset:offset+4]) & 0x7fffffff
	return fmt.Sprintf("%0*d", codeDigits, number%1_000_000), nil
}

// totpMatches is verify_totp: six digits, one step of drift either way.
func totpMatches(secret, submitted string, now time.Time) bool {
	digits := digitsOf(submitted)
	if len(digits) != codeDigits {
		return false
	}
	matched := false
	for offset := int64(-totpDriftSteps); offset <= totpDriftSteps; offset++ {
		code, err := totpCode(secret, now, offset)
		if err != nil {
			return false
		}
		if subtle.ConstantTimeCompare([]byte(code), []byte(digits)) == 1 {
			matched = true
		}
	}
	return matched
}

// FieldKey decrypts the existing application's restricted fields
// (apps/core/crypto.py): "v1:<iv>:<tag>:<ciphertext>", AES-256-GCM.
type FieldKey []byte

var hex64 = regexp.MustCompile(`^[0-9a-fA-F]{64}$`)

// ParseFieldKey reads FIELD_ENCRYPTION_KEY's format: 64 hex characters or
// base64 of 32 bytes. Empty means no key, which is not an error.
func ParseFieldKey(raw string) (FieldKey, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, nil
	}
	var key []byte
	var err error
	if hex64.MatchString(raw) {
		key, err = hex.DecodeString(raw)
	} else {
		key, err = base64.StdEncoding.DecodeString(raw)
	}
	if err != nil || len(key) != 32 {
		return nil, errors.New("signin: the field encryption key must be 32 bytes (64 hex characters or base64)")
	}
	return key, nil
}

// errNoFieldKey: the value is encrypted and this process has no key.
var errNoFieldKey = errors.New("signin: no field encryption key is configured")

// VerifyTOTP checks a 6-digit RFC 6238 authenticator code against a base32
// secret with ±1 step drift.
func VerifyTOTP(secret, submitted string, now time.Time) bool {
	return totpMatches(secret, submitted, now)
}

// Seal encrypts plain in the same "v1:<iv>:<tag>:<ciphertext>" AES-256-GCM
// format Open decrypts. Refuses to write plaintext when no FieldKey is set.
func (k FieldKey) Seal(plain string) (string, error) {
	if len(k) == 0 {
		return "", errNoFieldKey
	}
	block, err := aes.NewCipher(k)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return "", err
	}
	sealed := gcm.Seal(nil, nonce, []byte(plain), nil)
	tagStart := len(sealed) - gcm.Overhead()
	ct := sealed[:tagStart]
	tag := sealed[tagStart:]
	return fmt.Sprintf("v1:%s:%s:%s",
		base64.StdEncoding.EncodeToString(nonce),
		base64.StdEncoding.EncodeToString(tag),
		base64.StdEncoding.EncodeToString(ct),
	), nil
}

// Open returns the plain value of a stored restricted field. A value that
// is not encrypted is returned as it is, as the existing code tolerates.
func (k FieldKey) Open(stored string) (string, error) {
	if !strings.HasPrefix(stored, "v1:") {
		return stored, nil
	}
	if len(k) == 0 {
		return "", errNoFieldKey
	}
	parts := strings.Split(stored, ":")
	if len(parts) != 4 {
		return "", errors.New("signin: an encrypted field is malformed")
	}
	var decoded [3][]byte
	for i, part := range parts[1:] {
		value, err := base64.StdEncoding.DecodeString(part)
		if err != nil {
			return "", errors.New("signin: an encrypted field is malformed")
		}
		decoded[i] = value
	}
	block, err := aes.NewCipher(k)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCMWithNonceSize(block, len(decoded[0]))
	if err != nil {
		return "", err
	}
	plain, err := gcm.Open(nil, decoded[0], append(decoded[2], decoded[1]...), nil)
	if err != nil {
		return "", errors.New("signin: an encrypted field could not be opened")
	}
	return string(plain), nil
}

// maskEmail and maskPhone are the existing _mask_email and _mask_phone.
func maskEmail(address string) string {
	name, domain, found := strings.Cut(address, "@")
	if !found || domain == "" {
		return "•••"
	}
	head := ""
	runes := []rune(name)
	if len(runes) > 0 {
		head = string(runes[0])
	}
	return head + strings.Repeat("•", max(3, len(runes)-1)) + "@" + domain
}

func maskPhone(number string) string {
	digits := digitsOf(number)
	if len(digits) < 4 {
		return "••••"
	}
	return "•••• " + digits[len(digits)-4:]
}

// HashToken is how every single-use token is stored (hash_token).
func HashToken(raw string) string { return hashToken(raw) }

// NewToken is a fresh single-use token (generate_token).
func NewToken() (string, error) { return newRawToken() }

// IssueAccessToken signs the existing access token for userID in role.
func IssueAccessToken(secret []byte, userID, role string, now time.Time, ttl time.Duration) (string, error) {
	return issueAccessToken(secret, userID, role, now, ttl)
}
