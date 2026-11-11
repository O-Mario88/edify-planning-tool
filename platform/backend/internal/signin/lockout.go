package signin

import (
	"fmt"
	"time"
)

// Policy is the existing application's sign-in policy. Its defaults are the
// existing settings' defaults (config/settings/base.py); a deployment that
// changes one there must change it here too, or the two doors to one account
// would lock it differently (docs/auth-lockout-policy.md).
type Policy struct {
	MaxFailedLogins        int           // AUTH_MAX_FAILED_LOGINS
	LockoutDuration        time.Duration // AUTH_LOCKOUT_DURATION_MINUTES
	EscalationCount        int           // AUTH_LOCKOUT_ESCALATION_COUNT
	EscalationWindow       time.Duration // AUTH_LOCKOUT_ESCALATION_WINDOW_HOURS
	AdminUnlockAfterEscal  bool          // AUTH_REQUIRE_ADMIN_UNLOCK_AFTER_ESCALATION
	FailedStreakResetAfter time.Duration // AUTH_FAILED_LOGIN_RESET_WINDOW_MINUTES
	AlertThreshold         int           // FAILED_LOGIN_ALERT_THRESHOLD (apps/admin_ops)
	AccessTokenTTL         time.Duration // ACCESS_TOKEN_TTL_MINUTES
	RefreshTokenTTL        time.Duration // REFRESH_TOKEN_TTL_DAYS
	PasswordResetTTL       time.Duration // PASSWORD_RESET_TOKEN_TTL_MINUTES
	// Second factor: everyone, or the holders of these roles, whether or not
	// they enrolled (MFA_REQUIRED_FOR_ALL, MFA_REQUIRED_ROLES).
	MFARequiredForAll bool
	MFARequiredRoles  []string
}

// DefaultPolicy is the existing application's defaults.
func DefaultPolicy() Policy {
	return Policy{
		MaxFailedLogins:        10,
		LockoutDuration:        15 * time.Minute,
		EscalationCount:        3,
		EscalationWindow:       24 * time.Hour,
		AdminUnlockAfterEscal:  true,
		FailedStreakResetAfter: 30 * time.Minute,
		AlertThreshold:         5,
		AccessTokenTTL:         15 * time.Minute,
		RefreshTokenTTL:        7 * 24 * time.Hour,
		PasswordResetTTL:       45 * time.Minute,
	}
}

// Lockout is an account's lockout columns.
type Lockout struct {
	FailedCount     int
	StreakStartedAt *time.Time
	LockedUntil     *time.Time
	LastLockoutAt   *time.Time
	CycleCount      int
	Escalated       bool
}

// Locked reports whether the account may not even try a password now, and
// whether only an administrator can lift it (check_lockout).
func (l Lockout) Locked(now time.Time) (locked, escalated bool) {
	if l.Escalated {
		return true, true
	}
	if l.LockedUntil != nil && l.LockedUntil.After(now) {
		return true, false
	}
	return false, false
}

// FailureOutcome is what one wrong password changed, beyond the counters.
type FailureOutcome struct {
	// LockStarted: a timed lock began. Escalated: the account now waits for
	// an administrator. Reason is the audit reason for whichever happened.
	LockStarted, Escalated bool
	Reason                 string
	// AlertStreak is the streak this failure made, read before a lock resets
	// it; the Admin security alert fires when it equals the threshold.
	AlertStreak int
}

// AfterFailure is record_failed_attempt's arithmetic: the account's columns
// after one more wrong password at now. The caller holds the row lock.
func (p Policy) AfterFailure(l Lockout, now time.Time) (Lockout, FailureOutcome) {
	next := l
	if next.StreakStartedAt != nil && next.StreakStartedAt.Before(now.Add(-p.FailedStreakResetAfter)) {
		next.FailedCount, next.StreakStartedAt = 0, nil
	}
	if next.FailedCount == 0 {
		started := now
		next.StreakStartedAt = &started
	}
	next.FailedCount++
	outcome := FailureOutcome{AlertStreak: next.FailedCount}
	if next.FailedCount < p.MaxFailedLogins {
		return next, outcome
	}

	if next.LastLockoutAt != nil && !next.LastLockoutAt.Before(now.Add(-p.EscalationWindow)) {
		next.CycleCount++
	} else {
		next.CycleCount = 1
	}
	at := now
	next.LastLockoutAt = &at
	next.FailedCount, next.StreakStartedAt = 0, nil

	if next.CycleCount >= p.EscalationCount && p.AdminUnlockAfterEscal {
		next.Escalated, next.LockedUntil = true, nil
		outcome.Escalated = true
		outcome.Reason = fmt.Sprintf("%d lockout cycles within %dh -- admin unlock required.",
			next.CycleCount, int(p.EscalationWindow.Hours()))
		return next, outcome
	}
	until := now.Add(p.LockoutDuration)
	next.LockedUntil = &until
	outcome.LockStarted = true
	outcome.Reason = fmt.Sprintf("%d consecutive failed logins -- locked %d minute(s).",
		p.MaxFailedLogins, int(p.LockoutDuration.Minutes()))
	return next, outcome
}

// RequiresSecondFactor is required_for: enrolled, or required by policy for
// every account or for a role the account holds or is acting in.
func (p Policy) RequiresSecondFactor(enrolled bool, roles []string, activeRole string) bool {
	if enrolled || p.MFARequiredForAll {
		return true
	}
	for _, required := range p.MFARequiredRoles {
		if required == activeRole {
			return true
		}
		for _, held := range roles {
			if held == required {
				return true
			}
		}
	}
	return false
}
