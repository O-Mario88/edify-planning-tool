// The social sign-in gate — the single security decision point.
//
// PURE: it never reads the user store, env, or network. The route resolves the
// registered user (by normalized email) and any existing provider-account link,
// then asks this function whether to allow. That keeps every branch unit-testable
// and impossible to bypass from a UI or callback shortcut.
//
// Order is deny-first and fail-closed: missing email → unverified → unregistered
// → email-mismatch → status → account-link mismatch → MFA → allow.

import { normalizeEmail } from "./email";
import type {
  ExistingLink,
  ProviderClaims,
  RegisteredUser,
  SocialDecision,
} from "./types";

export type DecideInput = {
  claims: ProviderClaims;
  /** normalizeEmail(claims.email) — passed in so the route and gate agree. */
  normalizedEmail: string | null;
  /** findLoginUserByRegisteredEmail(normalizedEmail) — null if not registered. */
  user: RegisteredUser | null;
  /** The stored link for (claims.provider, claims.sub), if any. */
  existingLink: ExistingLink | null;
  /** socialMfaRequired(user, policy). Only consulted once the user is allowed. */
  mfaRequired: boolean;
};

function statusAllows(status: string): { ok: true } | { ok: false; locked: boolean } {
  const s = status.trim().toLowerCase();
  if (s === "active") return { ok: true };
  // Locked is reported distinctly so the audit trail separates a locked account
  // from a merely inactive one. Everything else (invited/suspended/deactivated/
  // deleted/archived/password-reset/unknown) is denied as inactive — fail closed.
  return { ok: false, locked: s === "locked" };
}

export function decideSocialLogin(input: DecideInput): SocialDecision {
  const { claims, normalizedEmail, user, existingLink, mfaRequired } = input;

  // 1. No usable email from the provider at all.
  if (!normalizedEmail) {
    return { decision: "deny", reason: "MISSING_EMAIL", auditEvent: "SOCIAL_LOGIN_DENIED_UNREGISTERED_EMAIL" };
  }

  // 2. The provider must assert the email is verified. Never trust an unverified
  //    provider email — it can be attacker-controlled.
  if (claims.emailVerified !== true) {
    return { decision: "deny", reason: "UNVERIFIED_EMAIL", auditEvent: "SOCIAL_LOGIN_DENIED_UNVERIFIED_EMAIL" };
  }

  // 3. The email must already belong to a registered local user.
  if (!user) {
    return { decision: "deny", reason: "UNREGISTERED_EMAIL", auditEvent: "SOCIAL_LOGIN_DENIED_UNREGISTERED_EMAIL" };
  }

  // 4. Defense-in-depth: the resolved user's canonical email must match the
  //    normalized provider email EXACTLY. Guards against a store that ever does
  //    fuzzy/alias matching — no plus-tag or domain-only slip-through here.
  if (normalizeEmail(user.email) !== normalizedEmail) {
    return { decision: "deny", reason: "UNREGISTERED_EMAIL", auditEvent: "SOCIAL_LOGIN_DENIED_UNREGISTERED_EMAIL" };
  }

  // 5. The account must be allowed to log in.
  const status = statusAllows(String(user.status));
  if (!status.ok) {
    return status.locked
      ? { decision: "deny", reason: "LOCKED_USER", auditEvent: "SOCIAL_LOGIN_DENIED_LOCKED_USER" }
      : { decision: "deny", reason: "INACTIVE_USER", auditEvent: "SOCIAL_LOGIN_DENIED_INACTIVE_USER" };
  }

  // 6. One provider account → exactly one local user. If this provider account
  //    id is already linked to a DIFFERENT user, treat it as a takeover signal.
  if (existingLink && normalizeEmail(existingLink.userEmail) !== normalizedEmail) {
    return { decision: "deny", reason: "ACCOUNT_MISMATCH", auditEvent: "SOCIAL_ACCOUNT_MISMATCH" };
  }

  // 7. Privileged roles must clear MFA before a session is minted.
  if (mfaRequired) {
    return { decision: "mfa_required", user };
  }

  // 8. Registered, verified, active, matched, MFA-clear → allow.
  return { decision: "allow", user };
}
