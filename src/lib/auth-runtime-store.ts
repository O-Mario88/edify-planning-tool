// Runtime user + reset-token store.
//
// Lives in-memory on the Node server (Next.js standalone instance). In
// production this swaps for a real DB. The shape is intentionally
// hash-ready: passwords are kept as `passwordHash` strings, with a clear
// placeholder hash function isolated below so the swap to bcrypt/argon2
// is a one-file change.
//
// What lives here:
//   • Newly signed-up users (the static DEMO_USERS are read-only at
//     /lib/auth-public.ts; this store accepts new accounts).
//   • Password reset tokens, keyed by email, with a 30-min expiry.

import "server-only";

import bcrypt from "bcryptjs";
import { DEMO_USERS, SUPER_ADMIN_EMAIL, type ClientDemoUser } from "@/lib/auth-public";

export type StoredUser = {
  email: string;
  name: string;
  role: ClientDemoUser["role"];
  passwordHash: string;
  createdAt: string;
  status: "Active" | "Invited" | "Suspended";
};

export type ResetToken = {
  email: string;
  token: string;
  createdAt: string;
  expiresAt: string;
  used: boolean;
};

// Plain-Node module-scope state. Reset on dev-server restart, but stable
// across requests within one server instance. Production replaces this
// with a real DB + a real session store.
const userStore = new Map<string, StoredUser>();
const resetTokens = new Map<string, ResetToken>();

// ──────────────────────────── Password hashing ────────────────────────
//
// bcrypt with a cost of 12. 12 rounds takes ~250 ms on modern Node —
// slow enough to defeat brute-force on a single leaked hash, fast
// enough that a real login still feels instant. Move to argon2id when
// the deploy target supports it natively.
//
// We accept either a real bcrypt hash ($2a$/$2b$/$2y$ prefix) OR the
// legacy `placeholder$…` strings produced by earlier builds — those
// auto-upgrade to bcrypt on first successful verify. This means
// existing accounts don't lock out when the hashing function changes.

const BCRYPT_ROUNDS = 12;
const LEGACY_PREFIX = "placeholder$";

export function hashPassword(password: string): string {
  return bcrypt.hashSync(password, BCRYPT_ROUNDS);
}

export function verifyPassword(password: string, hash: string): boolean {
  if (hash.startsWith(LEGACY_PREFIX)) {
    // Constant-time comparison for the legacy path to keep timing
    // attacks symmetric with the bcrypt path.
    const expected = `${LEGACY_PREFIX}${password}`;
    if (hash.length !== expected.length) return false;
    let diff = 0;
    for (let i = 0; i < hash.length; i++) {
      diff |= hash.charCodeAt(i) ^ expected.charCodeAt(i);
    }
    return diff === 0;
  }
  try {
    return bcrypt.compareSync(password, hash);
  } catch {
    return false;
  }
}

// Seed the store with the static DEMO_USERS so login still works for
// anyone who hasn't signed up fresh. Hashed with real bcrypt at module
// init — cost is ~250ms × number of demo users, paid once per server
// boot, never on a request hot path.
//
// HOSTING-SECURITY (P0-2): the demo password is env-overridable so a hosted
// test runs on a per-event secret instead of the public "edify". Set
// DEMO_LOGIN_PASSWORD in the deploy env (MUST match the bridge + backend seed —
// they read the same var). The privileged admin account is disabled unless
// ENABLE_DEMO_ADMIN=true (always available in dev so local testing is unaffected).
const DEMO_PASSWORD = process.env.DEMO_LOGIN_PASSWORD || "edify";
// The named onboarding super-admin (auth-public.SUPER_ADMIN_EMAIL) gets its OWN
// credential — read ONLY from the environment, never hardcoded, so no real
// secret ever lands in source or git history. In dev (no secret configured) it
// falls back to the shared demo password so local sign-in works; in production,
// if SUPER_ADMIN_PASSWORD is unset the account is simply NOT seeded (unusable)
// until the secret is set on the host — a blank/guessable credential can never
// be used.
const SUPER_ADMIN_PASSWORD =
  process.env.SUPER_ADMIN_PASSWORD ||
  (process.env.NODE_ENV !== "production" ? DEMO_PASSWORD : "");
const ADMIN_ENABLED =
  process.env.ENABLE_DEMO_ADMIN === "true" || process.env.NODE_ENV !== "production";
for (const u of Object.values(DEMO_USERS)) {
  const email = u.email.toLowerCase();
  // The generic demo admin is gated in production; the named super-admin is not.
  if (email === "admin@edify.org" && !ADMIN_ENABLED) continue;
  const isSuperAdmin = email === SUPER_ADMIN_EMAIL;
  // Super-admin with no configured secret (production, env unset) → don't seed.
  if (isSuperAdmin && !SUPER_ADMIN_PASSWORD) continue;
  userStore.set(email, {
    email,
    name: u.name,
    role: u.role,
    passwordHash: hashPassword(isSuperAdmin ? SUPER_ADMIN_PASSWORD : DEMO_PASSWORD),
    createdAt: "2025-01-01T00:00:00.000Z",
    status: "Active",
  });
}

// ──────────────────────────── User store API ──────────────────────────

export function findUser(email: string): StoredUser | null {
  return userStore.get(email.toLowerCase()) ?? null;
}

export type SignupInput = {
  email: string;
  name: string;
  password: string;
  role?: ClientDemoUser["role"];
};

export type SignupResult =
  | { ok: true; user: StoredUser }
  | { ok: false; reason: "EMAIL_EXISTS" | "WEAK_PASSWORD" | "INVALID_EMAIL" | "INVALID_NAME" };

export function createUser(input: SignupInput): SignupResult {
  const email = input.email.trim().toLowerCase();
  if (!email.includes("@") || email.length < 5) return { ok: false, reason: "INVALID_EMAIL" };
  if (!input.name || input.name.trim().length < 2) return { ok: false, reason: "INVALID_NAME" };
  if (!input.password || input.password.length < 6) return { ok: false, reason: "WEAK_PASSWORD" };
  if (userStore.has(email)) return { ok: false, reason: "EMAIL_EXISTS" };

  const user: StoredUser = {
    email,
    name: input.name.trim(),
    role: input.role ?? "CCEO",
    passwordHash: hashPassword(input.password),
    createdAt: new Date().toISOString(),
    status: "Active",
  };
  userStore.set(email, user);
  return { ok: true, user };
}

// ──────────────────────────── Reset-token API ─────────────────────────

export function createResetToken(email: string): ResetToken | null {
  const key = email.trim().toLowerCase();
  if (!userStore.has(key)) return null;
  const token = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  const now = new Date();
  const expires = new Date(now.getTime() + 30 * 60 * 1000); // 30 min
  const record: ResetToken = {
    email: key,
    token,
    createdAt: now.toISOString(),
    expiresAt: expires.toISOString(),
    used: false,
  };
  resetTokens.set(token, record);
  return record;
}

export function consumeResetToken(token: string, newPassword: string):
  | { ok: true; user: StoredUser }
  | { ok: false; reason: "INVALID_TOKEN" | "EXPIRED" | "USED" | "WEAK_PASSWORD" } {
  const record = resetTokens.get(token);
  if (!record) return { ok: false, reason: "INVALID_TOKEN" };
  if (record.used) return { ok: false, reason: "USED" };
  if (new Date(record.expiresAt).getTime() < Date.now()) return { ok: false, reason: "EXPIRED" };
  if (!newPassword || newPassword.length < 6) return { ok: false, reason: "WEAK_PASSWORD" };

  const user = userStore.get(record.email);
  if (!user) return { ok: false, reason: "INVALID_TOKEN" };
  user.passwordHash = hashPassword(newPassword);
  record.used = true;
  return { ok: true, user };
}

// Hook for the /api/auth/login route to verify against the runtime store
// (which may include freshly signed-up users) before falling back to the
// static DEMO_USERS. Transparently upgrades any legacy `placeholder$…`
// hash to bcrypt on first successful verify.
export function authenticateRuntime(email: string, password: string): StoredUser | null {
  const user = findUser(email);
  if (!user) return null;
  if (!verifyPassword(password, user.passwordHash)) return null;
  if (user.passwordHash.startsWith(LEGACY_PREFIX)) {
    user.passwordHash = hashPassword(password);
  }
  return user;
}
