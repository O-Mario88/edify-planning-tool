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

// IMPORTANT: pin the store to globalThis.
//
// In a Next.js production build, this module is bundled SEPARATELY into the
// route-handler graph (/api/* — including /api/auth/login) and the RSC/server-
// component graph (the pages). A plain module-level `new Map()` therefore yields
// TWO independent instances: login records credentials in the route-handler copy,
// but server components read an empty RSC copy → every page-level backendFetch
// fails with "No backend session" and falls back to empty data, even though the
// /api/* proxies work. Anchoring the Map on globalThis gives all bundles ONE
// shared instance. (In dev the module graph is shared, so this is a no-op there.)
type CredEntry = { email: string; password: string; at: number };
const globalForCreds = globalThis as unknown as {
  __edifySessionCredentials?: Map<string, CredEntry>;
};
const store: Map<string, CredEntry> =
  globalForCreds.__edifySessionCredentials ?? new Map<string, CredEntry>();
globalForCreds.__edifySessionCredentials = store;

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
