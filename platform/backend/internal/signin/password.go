// Package signin is Edify's sign-in, owned by Go (owner brief "Final backend
// responsibility and language boundaries", 2026-11-11: "Authentication,
// login, logout and session management. Password security and account
// recovery. Multi-factor authentication where supported.").
//
// It works on the existing application's own records — the "user",
// refresh_token, mfa_challenge and user_invitation tables and the audit
// chain — with the existing rules ported one for one, so an account signs in
// the same way whichever system it reaches and a session one system issues
// the other honours. The existing web pages keep their own sign-in until the
// web moves too; both apply the same lockout to the same columns under the
// same row locks.
package signin

import (
	"crypto/pbkdf2"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"fmt"
	"strconv"
	"strings"
	"unicode"

	"golang.org/x/crypto/bcrypt"
)

const (
	// bcryptCost is the existing BCryptPasswordHasher's (rounds = 12).
	bcryptCost = 12
	// bcryptMaxBytes is where bcrypt stops reading a password.
	bcryptMaxBytes = 72
	bcryptPrefix   = "bcrypt$"
	pbkdf2Prefix   = "pbkdf2_sha256$"
)

// timingHash is checked against when there is no account or no usable
// password, so a rejection costs about what a wrong password costs.
var timingHash = mustTimingHash()

func mustTimingHash() []byte {
	hash, err := bcrypt.GenerateFromPassword([]byte("no account has this password"), bcryptCost)
	if err != nil {
		panic(err)
	}
	return hash
}

// PasswordMatches checks raw against a password as the existing application
// stores it: bcrypt (its preferred hasher) or PBKDF2-SHA256 (its fallback).
// Anything else — empty, unusable ("!…"), an unknown hasher — never matches,
// after the same amount of work.
func PasswordMatches(encoded, raw string) bool {
	switch {
	case strings.HasPrefix(encoded, bcryptPrefix):
		if len(raw) > bcryptMaxBytes {
			BurnPasswordCheck(raw)
			return false
		}
		return bcrypt.CompareHashAndPassword([]byte(strings.TrimPrefix(encoded, bcryptPrefix)), []byte(raw)) == nil
	case strings.HasPrefix(encoded, pbkdf2Prefix):
		return pbkdf2Matches(encoded, raw)
	}
	BurnPasswordCheck(raw)
	return false
}

// BurnPasswordCheck spends a password check's time and decides nothing.
func BurnPasswordCheck(raw string) {
	if len(raw) > bcryptMaxBytes {
		raw = raw[:bcryptMaxBytes]
	}
	_ = bcrypt.CompareHashAndPassword(timingHash, []byte(raw))
}

// pbkdf2Matches reads Django's "pbkdf2_sha256$<iterations>$<salt>$<hash>".
func pbkdf2Matches(encoded, raw string) bool {
	parts := strings.Split(encoded, "$")
	iterations := 0
	var want []byte
	if len(parts) == 4 {
		iterations, _ = strconv.Atoi(parts[1])
		want, _ = base64.StdEncoding.DecodeString(parts[3])
	}
	if iterations < 1 || iterations > 10_000_000 || len(want) == 0 {
		BurnPasswordCheck(raw)
		return false
	}
	got, err := pbkdf2.Key(sha256.New, raw, []byte(parts[2]), iterations, len(want))
	if err != nil {
		return false
	}
	return subtle.ConstantTimeCompare(got, want) == 1
}

// EncodePassword stores a new password the way the existing application
// does by default, so either system can check it afterwards.
func EncodePassword(raw string) (string, error) {
	if len(raw) > bcryptMaxBytes {
		return "", fmt.Errorf("signin: a password longer than %d bytes cannot be stored", bcryptMaxBytes)
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(raw), bcryptCost)
	if err != nil {
		return "", fmt.Errorf("signin: hashing a password: %w", err)
	}
	return bcryptPrefix + string(hash), nil
}

// PasswordProblems is the existing password policy (apps/core/security.py
// validate_password), word for word: an empty list means the password is
// acceptable. The byte limit is bcrypt's, which the existing hasher shares.
func PasswordProblems(password, email string) []string {
	if password == "" {
		return []string{"Password cannot be empty."}
	}
	var problems []string
	if len([]rune(password)) < 8 {
		problems = append(problems, "Password must be at least 8 characters long.")
	}
	if !strings.ContainsFunc(password, inRange('A', 'Z')) {
		problems = append(problems, "Password must include at least one uppercase letter.")
	}
	if !strings.ContainsFunc(password, inRange('a', 'z')) {
		problems = append(problems, "Password must include at least one lowercase letter.")
	}
	if !strings.ContainsFunc(password, inRange('0', '9')) {
		problems = append(problems, "Password must include at least one number.")
	}
	if !strings.ContainsFunc(password, isSymbol) {
		problems = append(problems, "Password must include at least one symbol (e.g. !@#$%).")
	}
	if email != "" && strings.EqualFold(password, email) {
		problems = append(problems, "Password cannot be the same as your email address.")
	}
	if len(password) > bcryptMaxBytes {
		problems = append(problems, fmt.Sprintf("Password must be at most %d bytes long.", bcryptMaxBytes))
	}
	return problems
}

func inRange(low, high rune) func(rune) bool {
	return func(r rune) bool { return r >= low && r <= high }
}

// isSymbol is the existing [^A-Za-z0-9\s].
func isSymbol(r rune) bool {
	return !inRange('A', 'Z')(r) && !inRange('a', 'z')(r) && !inRange('0', '9')(r) && !unicode.IsSpace(r)
}
