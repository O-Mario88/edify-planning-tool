import "server-only";

// Server-side bridge from edify-web → edify-api (NestJS).
//
// The two apps have separate auth: edify-web has a demo cookie session, the
// backend has JWT. This client maps the signed-in edify-web user to a backend
// demo account (by role), logs in once (token cached), and proxies scoped
// requests with the Bearer token. Server-only — tokens never reach the browser.
//
// Enable per-surface via EDIFY_USE_BACKEND=true; the API base is EDIFY_API_URL.

const API = process.env.EDIFY_API_URL ?? "http://localhost:4000/api";
// Bridge → backend login password. Reads the SAME env var as the FE login store
// and the backend seed (DEMO_LOGIN_PASSWORD) so a rotated demo secret keeps all
// three in lockstep; defaults to "edify" for local dev.
const DEV_PASSWORD = process.env.DEMO_LOGIN_PASSWORD || "edify";

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

// edify-web role → backend demo account with the matching scope. The backend
// resolves the real role/scope from its own user record, so role-string
// differences (RVP vs RegionalVicePresident) don't matter here.
const ROLE_TO_BACKEND_EMAIL: Record<string, string> = {
  CCEO: "cceo@edify.org",
  CountryProgramLead: "pl1@edify.org",
  CountryDirector: "cd@edify.org",
  RVP: "rvp@edify.org",
  RegionalVicePresident: "rvp@edify.org",
  ImpactAssessment: "ia@edify.org",
  ProgramAccountant: "accountant@edify.org",
  HumanResource: "hr@edify.org",
  HumanResources: "hr@edify.org",
  // Project Coordinator maps to its OWN seeded backend account, NOT the CD's —
  // otherwise a PC would authenticate with full Country-Director permissions
  // (role escalation). coordinator@edify.org has the narrow ProjectCoordinator
  // scope (assigned projects + their schools only).
  ProjectCoordinator: "coordinator@edify.org",
  Admin: "admin@edify.org",
  // Partner field officer authenticates as the partner user linked (Partner.userId)
  // to a Partner org — their session is scoped to that org's assigned activities.
  PartnerAdmin: "partner@edify.org",
  PartnerFieldOfficer: "partner@edify.org",
  // Read-only partner viewer also maps to the partner org account — never the CD.
  PartnerViewer: "partner@edify.org",
};

export type BackendUser = { email?: string; role: string };
function backendEmailFor(user: BackendUser): string {
  // Fail least-privilege, NOT to the CD account: an unmapped/unknown role must
  // never silently inherit Country-Director powers. The partner account is the
  // most restricted seeded principal.
  return ROLE_TO_BACKEND_EMAIL[user.role] ?? "partner@edify.org";
}

type CacheEntry = { token: string; exp: number };
const tokenCache = new Map<string, CacheEntry>();

// Distinguish the three login failure modes so the caller surfaces an
// actionable error instead of one opaque "auth unavailable" message.
type LoginOutcome =
  | { ok: true; token: string }
  | { ok: false; reason: "unreachable"; detail: string }   // network/DNS — API not found
  | { ok: false; reason: "rejected"; detail: string }      // 401 — bad password / user mismatch
  | { ok: false; reason: "config"; detail: string };       // 4xx other — misconfigured base URL

async function loginToBackend(email: string): Promise<LoginOutcome> {
  const cached = tokenCache.get(email);
  if (cached && cached.exp > Date.now()) return { ok: true, token: cached.token };
  try {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password: DEV_PASSWORD }),
      cache: "no-store",
    });
    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        return {
          ok: false, reason: "rejected",
          detail: `Backend rejected the demo login (HTTP ${res.status}). The web DEMO_LOGIN_PASSWORD ("${DEV_PASSWORD ? "••••" : "(empty)"}") does not match the hashed password in the DB. Re-seed edify-api (npm run seed) so both sides share the same value, or reset the DB.`,
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
    tokenCache.set(email, { token: data.accessToken, exp: Date.now() + 10 * 60 * 1000 });
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
  | { ok: false; error: string };

/** The backend API base — used by the SSE proxy route to stream realtime events. */
export function backendApiBase(): string {
  return API;
}

/** Resolve the backend bearer token for a user (for the SSE proxy, which can't
 *  use backendFetch because it streams an open connection). */
export async function backendTokenFor(user: BackendUser): Promise<string | null> {
  const r = await loginToBackend(backendEmailFor(user));
  return r.ok ? r.token : null;
}

/** Fetch a scoped backend endpoint as the current edify-web user. */
export async function backendFetch<T>(path: string, user: BackendUser, init?: RequestInit): Promise<BackendResult<T>> {
  const misconfigured = apiBaseMisconfigured();
  if (misconfigured) return { ok: false, error: misconfigured };

  const email = backendEmailFor(user);
  const login = await loginToBackend(email);
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
