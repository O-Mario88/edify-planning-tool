// Password policy validation — shared by set-password, reset-password, and
// admin force-reset. Enforces the rules from the auth spec:
//   • minimum 8 characters
//   • at least one uppercase letter
//   • at least one lowercase letter
//   • at least one number
//   • at least one symbol (preferred)
//   • cannot be the same as the email
//   • cannot be empty
//
// Returns a list of human-readable failure reasons (empty = valid). Callers
// surface these as field-level errors on the set/reset form.

export type PasswordRuleViolation = string;

const UPPER = /[A-Z]/;
const LOWER = /[a-z]/;
const DIGIT = /[0-9]/;
// Symbol = anything that's not a letter, digit, or whitespace.
const SYMBOL = /[^A-Za-z0-9\s]/;

export function validatePassword(
  password: string,
  email?: string,
): PasswordRuleViolation[] {
  const violations: PasswordRuleViolation[] = [];

  if (!password || password.length === 0) {
    return ['Password cannot be empty.'];
  }
  if (password.length < 8) {
    violations.push('Password must be at least 8 characters long.');
  }
  if (!UPPER.test(password)) {
    violations.push('Password must include at least one uppercase letter.');
  }
  if (!LOWER.test(password)) {
    violations.push('Password must include at least one lowercase letter.');
  }
  if (!DIGIT.test(password)) {
    violations.push('Password must include at least one number.');
  }
  if (!SYMBOL.test(password)) {
    violations.push('Password must include at least one symbol (e.g. !@#$%).');
  }
  // Must not equal the email (case-insensitive) — a common weak-password pattern.
  if (email && password.toLowerCase() === email.toLowerCase()) {
    violations.push('Password cannot be the same as your email address.');
  }

  return violations;
}

export function isValidPassword(password: string, email?: string): boolean {
  return validatePassword(password, email).length === 0;
}
