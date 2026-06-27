// Server-side per-user credential store.
//
// Replaces the legacy role-mapped demo-password bridge (backend.ts
// ROLE_TO_BACKEND_EMAIL + DEV_PASSWORD). When a user signs in via the login
// route, we record their REAL email + password (the credentials they just
// typed), so loginToBackend() authenticates against the Django backend as the
// actual signed-in user — not a role-mapped demo account with a shared demo
// password.
//
// Keyed by EMAIL so the existing BackendUser { email } (passed to live() by all
// ~92 proxy routes / server components) is sufficient to resolve credentials —
// no call-site signature changes needed.
//
// In-memory on the Node server (Next.js standalone). Production can swap this
// for an encrypted store / refresh-token cookie; the surface
// (recordCredentials / credentialsFor / clearCredentials) stays the same.
import "server-only";

const store = new Map<string, { email: string; password: string; at: number }>();

const MAX_AGE_MS = 1000 * 60 * 60 * 12; // 12h — matches the session cookie maxAge.

function expired(at: number): boolean {
  return Date.now() - at > MAX_AGE_MS;
}

export function recordCredentials(email: string, password: string): void {
  const key = email.toLowerCase();
  store.set(key, { email: key, password, at: Date.now() });
}

export function credentialsFor(email: string | null | undefined): { email: string; password: string } | null {
  if (!email) return null;
  const key = email.toLowerCase();
  const entry = store.get(key);
  if (!entry || expired(entry.at)) {
    if (entry) store.delete(key);
    return null;
  }
  return { email: entry.email, password: entry.password };
}

export function clearCredentials(email: string): void {
  store.delete(email.toLowerCase());
}
