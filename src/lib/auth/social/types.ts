// Shared types for social sign-in. Kept free of server-only / node imports so
// the pure decision logic can be unit-tested in the node test env and imported
// from edge + node code paths alike.

import type { EdifyRole } from "@/lib/auth-public";

export type SocialProvider = "google" | "microsoft";

// The set of statuses the gate understands. The current in-memory user store
// uses Active | Invited | Suspended; the wider set is handled defensively so a
// future DB-backed store (DEACTIVATED / LOCKED / DELETED …) is denied correctly
// without a code change. Anything unrecognised is denied (fail closed).
export type UserStatus =
  | "Active"
  | "Invited"
  | "Suspended"
  | "Deactivated"
  | "Locked"
  | "PasswordResetRequired"
  | "Deleted"
  | "Archived";

// The minimal shape the decision needs from a registered user. The route maps
// the store's StoredUser onto this; the decision never reads the store itself.
export type RegisteredUser = {
  email: string; // canonical, already-normalized local email
  name: string;
  role: EdifyRole;
  status: UserStatus | string;
  mfaEnrolled?: boolean;
};

// Verified claims extracted from a provider ID token AFTER the token endpoint
// exchange + claim validation (iss/aud/exp/nonce). `email` is the raw provider
// email; the decision normalizes + matches it.
export type ProviderClaims = {
  provider: SocialProvider;
  sub: string; // stable provider account id
  email: string | null;
  emailVerified: boolean;
};

// A previously-stored link for (provider, sub) — used to enforce that one
// provider account maps to exactly one local user.
export type ExistingLink = {
  provider: SocialProvider;
  providerAccountId: string;
  userEmail: string; // normalized local email this provider account is bound to
};

export type DenyReason =
  | "MISSING_EMAIL"
  | "UNVERIFIED_EMAIL"
  | "UNREGISTERED_EMAIL"
  | "INACTIVE_USER"
  | "LOCKED_USER"
  | "ACCOUNT_MISMATCH";

// Audit event names — exactly the vocabulary the spec requires.
export type SocialAuditEvent =
  | "SOCIAL_LOGIN_STARTED"
  | "SOCIAL_LOGIN_SUCCESS"
  | "SOCIAL_LOGIN_DENIED_UNREGISTERED_EMAIL"
  | "SOCIAL_LOGIN_DENIED_UNVERIFIED_EMAIL"
  | "SOCIAL_LOGIN_DENIED_INACTIVE_USER"
  | "SOCIAL_LOGIN_DENIED_LOCKED_USER"
  | "SOCIAL_ACCOUNT_LINKED"
  | "SOCIAL_ACCOUNT_MISMATCH"
  | "MFA_REQUIRED_AFTER_SOCIAL"
  | "MFA_COMPLETED_AFTER_SOCIAL"
  | "SESSION_CREATED";

export type SocialDecision =
  | { decision: "allow"; user: RegisteredUser }
  | { decision: "mfa_required"; user: RegisteredUser }
  | { decision: "deny"; reason: DenyReason; auditEvent: SocialAuditEvent };
