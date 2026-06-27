import "server-only";

// Server-side bridge from edify-web → edify-api (Django + DRF).
//
// The browser talks to edify-web's same-origin /api/* routes (CSRF-protected).
// Those proxy routes resolve the signed-in user's REAL session, authenticate
// against the Django backend with the user's OWN credentials (no shared demo
// password, no role-mapped account), cache the resulting JWT briefly, and proxy
// scoped requests with the Bearer token. Server-only — tokens never reach the
// browser.
//
// Enable per-surface via EDIFY_USE_BACKEND=true; the API base is EDIFY_API_URL.

import { credentialsFor } from "./session-credentials";

const API = process.env.EDIFY_API_URL ?? "http://localhost:4000/api";

export function isBackendEnabled(): boolean {
  return (process.env.EDIFY_USE_BACKEND ?? "").toLowerCase() === "true";
}

function apiBaseMisconfigured(): string | null {
  const base = process.env.EDIFY_API_URL ?? "http://localhost:4000/api";
  if (!base.endsWith("/api")) {
    return `EDIFY_API_URL must end with /api (got "${base}")`;
  }
  return null;
}

// Kept for callers that still pass a BackendUser (most proxy routes) — the role
// is no longer used to MAP to a backend account; it's informational only. The
// real backend identity comes from the per-session credentials.
export type BackendUser = { email?: string; role: string };

type CacheEntry = { token: string; exp: number };
const tokenCache = new Map<string, CacheEntry>();

// Distinguish the three login failure modes so the caller surfaces an
// actionable error instead of one opaque "auth unavailable" message.
type LoginOutcome =
  | { ok: true; token: string }
  | { ok: false; reason: "unreachable"; detail: string }   // network/DNS — API not found
  | { ok: false; reason: "rejected"; detail: string }      // 401 — bad credentials
  | { ok: false; reason: "config" | "no-session"; detail: string };

// Authenticate against the Django backend as the REAL signed-in user, using the
// per-user credentials recorded at login (their actual email + password). The
// token is cached per email for 10 minutes.
async function loginToBackend(user: BackendUser): Promise<LoginOutcome> {
  const creds = credentialsFor(user.email);
  if (!creds) {
    return {
      ok: false, reason: "no-session",
      detail: "No backend session. Sign in again — your credentials are used to authenticate against the data backend.",
    };
  }
  const cached = tokenCache.get(creds.email);
  if (cached && cached.exp > Date.now()) return { ok: true, token: cached.token };
  try {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: creds.email, password: creds.password }),
      cache: "no-store",
    });
    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        return {
          ok: false, reason: "rejected",
          detail: `Backend rejected the login (HTTP ${res.status}). Your password does not match the account in the backend — sign in again, or ask an admin to reset it.`,
        };
      }
      let body = "";
      try { body = ` — ${((await res.json()) as { message?: string }).message ?? res.statusText}`; } catch { body = ` — ${res.statusText}`; }
      return {
        ok: false, reason: "config",
        detail: `Backend login returned HTTP ${res.status}${body}. Check EDIFY_API_URL="${API}" ends with /api and points at edify-api.`,
      };
    }
    const data = (await res.json()) as { accessToken?: string };
    if (!data.accessToken) {
      return { ok: false, reason: "config", detail: "Backend returned 200 but no accessToken in the response body." };
    }
    tokenCache.set(creds.email, { token: data.accessToken, exp: Date.now() + 10 * 60 * 1000 });
    return { ok: true, token: data.accessToken };
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Network error";
    return {
      ok: false, reason: "unreachable",
      detail: `Cannot reach edify-api at ${API} (${msg}). The API is down, or EDIFY_API_URL points at the wrong host/port.`,
    };
  }
}

export type BackendResult<T> =
  | { ok: true; data: T }
  | { ok: false, error: string };

/** The backend API base — used by the SSE proxy route to stream realtime events. */
export function backendApiBase(): string {
  return API;
}

/** Resolve the backend bearer token for the current user (for the SSE proxy,
 *  which can't use backendFetch because it streams an open connection). */
export async function backendTokenFor(user: BackendUser): Promise<string | null> {
  const r = await loginToBackend(user);
  return r.ok ? r.token : null;
}

/** Fetch a scoped backend endpoint as the current signed-in user. The user's
 *  email resolves their real backend credentials (no role-mapping). */
export async function backendFetch<T>(path: string, user: BackendUser, init?: RequestInit): Promise<BackendResult<T>> {
  const misconfigured = apiBaseMisconfigured();
  if (misconfigured) return { ok: false, error: misconfigured };

  const login = await loginToBackend(user);
  if (!login.ok) {
    return { ok: false, error: login.detail };
  }
  try {
    const res = await fetch(`${API}${path}`, {
      ...init,
      headers: { ...(init?.headers ?? {}), Authorization: `Bearer ${login.token}`, "Content-Type": "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = "";
      try {
        const body = (await res.json()) as { message?: string | string[] };
        if (body.message) detail = `: ${Array.isArray(body.message) ? body.message.join(", ") : body.message}`;
      } catch {
        /* non-json error body */
      }
      return { ok: false, error: `Backend ${res.status}${detail}` };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Network error";
    return { ok: false, error: `Cannot reach edify-api (${msg}). Check EDIFY_API_URL=${API}.` };
  }
}
