package signin

import (
	"strings"
	"testing"
	"time"
)

// Hashes, ciphertext and codes below were produced by the existing
// application's own code (Django make_password, apps/core/crypto.py,
// apps/accounts/mfa_service.py), so a test fails the moment Go and the
// existing application would disagree about an account.
const (
	djangoBcrypt = "bcrypt$$2b$12$y10bYjwN3fDiiGlimdyijutgna9/mQSvaiv1XoMaDyRlQW4SMNmR6"
	djangoPBKDF2 = "pbkdf2_sha256$1000000$v2rgXd62HHovFCYuNiwkMF$qjJXCc3+a6GfzhRNwG7vS8GJUAPQm2NqhFi/m/mvhDg="
	thePassword  = "Edify#2026"
)

func TestAPasswordTheExistingApplicationStoredIsRecognised(t *testing.T) {
	for _, encoded := range []string{djangoBcrypt, djangoPBKDF2} {
		if !PasswordMatches(encoded, thePassword) {
			t.Errorf("%s… did not match its password", encoded[:14])
		}
		if PasswordMatches(encoded, "edify#2026") {
			t.Errorf("%s… matched the wrong password", encoded[:14])
		}
	}
}

func TestNoUsableOrUnknownPasswordEverMatches(t *testing.T) {
	for _, encoded := range []string{"", "!YOL480z9HqlE1vstkBvuBK8kiRX6RFcGpctsDtkM", "md5$abc$def", "pbkdf2_sha256$x$y$z"} {
		if PasswordMatches(encoded, thePassword) {
			t.Errorf("%q matched", encoded)
		}
	}
	if PasswordMatches(djangoBcrypt, thePassword+strings.Repeat("x", 80)) {
		t.Error("a password past bcrypt's 72 bytes matched")
	}
}

func TestAPasswordGoStoresIsTheExistingFormat(t *testing.T) {
	encoded, err := EncodePassword(thePassword)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(encoded, "bcrypt$$2a$12$") && !strings.HasPrefix(encoded, "bcrypt$$2b$12$") {
		t.Fatalf("stored as %q, not the existing bcrypt$ format at cost 12", encoded[:16])
	}
	if !PasswordMatches(encoded, thePassword) {
		t.Fatal("Go could not read back its own password")
	}
}

func TestThePasswordPolicyIsTheExistingOneWordForWord(t *testing.T) {
	cases := []struct {
		password, email string
		want            []string
	}{
		{"", "", []string{"Password cannot be empty."}},
		{"Edify#2026", "", nil},
		{"short1!", "", []string{"Password must be at least 8 characters long.",
			"Password must include at least one uppercase letter."}},
		{"ALLUPPER1!", "", []string{"Password must include at least one lowercase letter."}},
		{"NoDigits!!", "", []string{"Password must include at least one number."}},
		{"NoSymbol12", "", []string{"Password must include at least one symbol (e.g. !@#$%)."}},
		{"With Space1", "", []string{"Password must include at least one symbol (e.g. !@#$%)."}},
		{"Paul.N@edify1.org", "paul.n@edify1.org", []string{"Password cannot be the same as your email address."}},
	}
	for _, tc := range cases {
		got := PasswordProblems(tc.password, tc.email)
		if strings.Join(got, "|") != strings.Join(tc.want, "|") {
			t.Errorf("%q: got %q, want %q", tc.password, got, tc.want)
		}
	}
}

func at(minutes int) time.Time {
	return time.Date(2026, 11, 11, 8, 0, 0, 0, time.UTC).Add(time.Duration(minutes) * time.Minute)
}

func TestTenWrongPasswordsLockForFifteenMinutesThenItLifts(t *testing.T) {
	policy := DefaultPolicy()
	var state Lockout
	var outcome FailureOutcome
	for i := 0; i < 10; i++ {
		state, outcome = policy.AfterFailure(state, at(0))
		if i == 4 && outcome.AlertStreak != 5 {
			t.Fatalf("the fifth failure's streak is %d, the alert waits for 5", outcome.AlertStreak)
		}
	}
	if !outcome.LockStarted || outcome.Escalated {
		t.Fatalf("the tenth failure: %+v", outcome)
	}
	if outcome.Reason != "10 consecutive failed logins -- locked 15 minute(s)." {
		t.Fatalf("audit reason %q", outcome.Reason)
	}
	if state.FailedCount != 0 || state.CycleCount != 1 {
		t.Fatalf("after the lock: %+v", state)
	}
	if locked, _ := state.Locked(at(14)); !locked {
		t.Fatal("not locked 14 minutes in")
	}
	if locked, _ := state.Locked(at(15)); locked {
		t.Fatal("still locked at 15 minutes")
	}
}

func TestAStreakOlderThanHalfAnHourStartsAgain(t *testing.T) {
	policy := DefaultPolicy()
	state, _ := policy.AfterFailure(Lockout{}, at(0))
	state, _ = policy.AfterFailure(state, at(10))
	state, _ = policy.AfterFailure(state, at(41))
	if state.FailedCount != 1 {
		t.Fatalf("a streak begun 41 minutes ago still counts: %d", state.FailedCount)
	}
}

func TestThreeLockoutsInADayNeedAnAdministrator(t *testing.T) {
	policy := DefaultPolicy()
	var state Lockout
	var outcome FailureOutcome
	for cycle := 0; cycle < 3; cycle++ {
		for i := 0; i < 10; i++ {
			state, outcome = policy.AfterFailure(state, at(cycle*20))
		}
	}
	if !outcome.Escalated || !state.Escalated || state.LockedUntil != nil {
		t.Fatalf("third lockout in a day: %+v %+v", outcome, state)
	}
	if outcome.Reason != "3 lockout cycles within 24h -- admin unlock required." {
		t.Fatalf("audit reason %q", outcome.Reason)
	}
	if locked, escalated := state.Locked(at(60 * 24 * 30)); !locked || !escalated {
		t.Fatal("an escalated account unlocked itself")
	}
}

func TestLockoutsADayApartStartTheCycleCountAgain(t *testing.T) {
	policy := DefaultPolicy()
	var state Lockout
	for _, start := range []int{0, 60 * 25, 60 * 50} {
		for i := 0; i < 10; i++ {
			state, _ = policy.AfterFailure(state, at(start))
		}
	}
	if state.Escalated || state.CycleCount != 1 {
		t.Fatalf("lockouts a day apart escalated: %+v", state)
	}
}

func TestTheSecondFactorIsRequiredByEnrolmentOrPolicy(t *testing.T) {
	policy := DefaultPolicy()
	if policy.RequiresSecondFactor(false, []string{"CCEO"}, "CCEO") {
		t.Fatal("required with no enrolment and no policy")
	}
	if !policy.RequiresSecondFactor(true, []string{"CCEO"}, "CCEO") {
		t.Fatal("not required for an enrolled account")
	}
	policy.MFARequiredRoles = []string{"Accountant"}
	if !policy.RequiresSecondFactor(false, []string{"CCEO", "Accountant"}, "CCEO") {
		t.Fatal("not required for a held role the policy names")
	}
	policy = DefaultPolicy()
	policy.MFARequiredForAll = true
	if !policy.RequiresSecondFactor(false, nil, "CCEO") {
		t.Fatal("not required when required for all")
	}
}

func TestAnAuthenticatorCodeMatchesTheExistingComputation(t *testing.T) {
	when := time.Unix(1762862400, 0)
	code, err := totpCode("JBSWY3DPEHPK3PXP", when, 0)
	if err != nil || code != "173616" {
		t.Fatalf("code %q %v, the existing totp_code says 173616", code, err)
	}
	if !totpMatches("JBSWY3DPEHPK3PXP", "173 616", when.Add(25*time.Second)) {
		t.Fatal("one step of drift was refused")
	}
	if totpMatches("JBSWY3DPEHPK3PXP", "173616", when.Add(95*time.Second)) {
		t.Fatal("a code three steps old was accepted")
	}
}

func TestAnEncryptedAuthenticatorSecretOpensWithTheExistingKey(t *testing.T) {
	key, err := ParseFieldKey(strings.Repeat("11", 32))
	if err != nil {
		t.Fatal(err)
	}
	plain, err := key.Open("v1:ilYwfotYKHDmxJ5w:TtkzFUpLmEXiRNOW3Rh7tg==:ouzX+dYfIFKQDMg8Sl1PcQ==")
	if err != nil || plain != "JBSWY3DPEHPK3PXP" {
		t.Fatalf("opened %q %v", plain, err)
	}
	if _, err := FieldKey(nil).Open("v1:a:b:c"); err == nil {
		t.Fatal("an encrypted value opened without a key")
	}
	if plain, _ := FieldKey(nil).Open("JBSWY3DPEHPK3PXP"); plain != "JBSWY3DPEHPK3PXP" {
		t.Fatal("a plain value was not returned as it is")
	}
	if _, err := ParseFieldKey("too-short"); err == nil {
		t.Fatal("a short key was accepted")
	}
	if _, err := FieldKey(nil).Seal("JBSWY3DPEHPK3PXP"); err == nil {
		t.Fatal("Seal accepted an empty key and would have stored plaintext")
	}
	sealed, err := key.Seal("JBSWY3DPEHPK3PXP")
	if err != nil || !strings.HasPrefix(sealed, "v1:") {
		t.Fatalf("Seal failed: %q %v", sealed, err)
	}
	if roundTrip, err := key.Open(sealed); err != nil || roundTrip != "JBSWY3DPEHPK3PXP" {
		t.Fatalf("Open(Seal) = %q %v", roundTrip, err)
	}
}

func TestWhereACodeWentIsMaskedAsTheExistingHint(t *testing.T) {
	for _, tc := range [][2]string{
		{maskEmail("paul.n@edify.org"), "p•••••@edify.org"},
		{maskEmail("ab@x.org"), "a•••@x.org"},
		{maskPhone("+256 772 123456"), "•••• 3456"},
		{maskPhone("12"), "••••"},
	} {
		if tc[0] != tc[1] {
			t.Errorf("got %q, want %q", tc[0], tc[1])
		}
	}
}

func TestFiguresReadLikeTheWebPage(t *testing.T) {
	for n, want := range map[int64]string{0: "0", 306: "306", 1204: "1,204", 1234567: "1,234,567"} {
		if got := grouped(n); got != want {
			t.Errorf("%d: %q", n, got)
		}
	}
	if fy := operationalFY(time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)); fy != "2027" {
		t.Errorf("1 October 2026 is FY %s", fy)
	}
	if fy := operationalFY(time.Date(2026, 9, 30, 23, 0, 0, 0, time.UTC)); fy != "2026" {
		t.Errorf("30 September 2026 is FY %s", fy)
	}
}

func TestASignInIsRecordedWithTheExistingDeviceLabel(t *testing.T) {
	for agent, want := range map[string]string{
		"":                                    "",
		"Mozilla/5.0 (iPhone; CPU iPhone OS)": "mobile",
		"Mozilla/5.0 (Linux; Android 16; Pixel 9) Mobile": "mobile",
		"Mozilla/5.0 (Linux; Android 16; SM-X710)":        "tablet",
		"Mozilla/5.0 (iPad; CPU OS 18)":                   "tablet",
		"Edify/1.0 okhttp":                                "desktop",
	} {
		if got := deviceCategory(agent); got != want {
			t.Errorf("%q: %q, want %q", agent, got, want)
		}
	}
}

func TestTheAppDeclaresItsFormFactorAndNothingElseIsTaken(t *testing.T) {
	for declared, want := range map[string]string{"mobile": "mobile", "tablet": "tablet", "": "", "desktop": "", "<script>": ""} {
		if got := appDevice(declared); got != want {
			t.Errorf("%q: %q, want %q", declared, got, want)
		}
	}
}
